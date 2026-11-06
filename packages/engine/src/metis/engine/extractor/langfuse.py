"""Fetching one session's Langfuse traces as a ``GradingInput``.

METIS supports Langfuse v4 only, through Observations API v2. A session is fetched in two
steps:

1. A ``sessionId``-filtered call, following every cursor page, finds which trace ids exist.
2. Each trace is then fetched in full with a ``traceId`` filter.

The second step is required. Some agent frameworks, Agno among them, break the session filter:
OpenInference's Agno instrumentation writes its own session id to the ``session.id`` attribute of agent-run spans
(``*.arun``), overwriting the Langfuse session id. A few other observations, such as a
GENERATION ending a delegated subagent run, carry no session id at all. A ``sessionId`` filter
silently drops both. A trace's own id and parent links are never touched, so a ``traceId``
filter always returns the complete tree, and the trace's root span always carries the right
session id, which is why step 1 is reliable for finding which traces exist.

Langfuse truncates any metadata value over 200 characters unless its key is named in
``expandMetadata``, and the keys are not known before the first fetch. So a trace whose
metadata may have been truncated is fetched a second time with every key it carries
expanded (see ``_fetch_trace``).

A trace recorded while its Langfuse server was moving to v4 comes back with every observation
duplicated and a synthetic root with id ``t-<traceId>``, and the stored set changes with page
size (issue #469). METIS does not repair such a trace; ``fetch_session`` raises
``UnsupportedTraceError`` for it, so the session fails and the trial must be re-run.

Langfuse can still be ingesting a session when ``evaluate`` starts. So ``fetch_session``
grades nothing until the session's traces stop changing (see ``wait_for_settled_traces``).

Input/output arrive as raw strings (``parse_io_as_json`` is rejected with HTTP 400), and
``metis.core.traces.Observation`` parses JSON-looking values itself.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from langfuse import Langfuse

from metis.core import Artifact, resolve_artifact_path
from metis.core.logging import get_logger
from metis.core.traces import GradingInput, Observation, Trace

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path

logger = get_logger(__name__)

_FIELDS = "core,basic,time,io,metadata"
"""``time`` holds ``updatedAt``, which the trace wait compares between checks."""
_PAGE_SIZE = 1000
_TRUNCATION_LIMIT = 200
"""Langfuse truncates metadata values longer than this unless the key is expanded."""
_BACKOFF_SECONDS = (1.0, 2.0, 4.0, 8.0, 15.0)
"""The pause before each next check. The last pause repeats until the timeout."""
_POINT_IN_TIME_TYPES = frozenset({"EVENT"})
"""Observation types that record one moment. Langfuse can store them with no end time, so
they never count as open."""

NO_TRACES = "no traces in Langfuse"
"""Failure reason: Langfuse returned no trace for the session before the timeout."""
TRACES_CHANGING = "traces still changing in Langfuse"
"""Failure reason: traces arrived but did not settle before the timeout."""


class UnsupportedTraceError(RuntimeError):
    """A session has a trace recorded before its Langfuse server's v4 upgrade (issue #469)."""


class TracesNotReadyError(RuntimeError):
    """A session's traces were missing or still changing when the trace wait timed out.

    The message is the failure reason, ``NO_TRACES`` or ``TRACES_CHANGING``.
    """

    def __init__(self, wait: TraceWait) -> None:
        super().__init__(wait.reason)
        self.wait = wait


def get_langfuse_client() -> Langfuse:
    """Return a configured Langfuse client (never None)."""
    import os

    if os.environ.get("LANGFUSE_BASE_URL") and not os.environ.get("LANGFUSE_HOST"):
        os.environ["LANGFUSE_HOST"] = os.environ["LANGFUSE_BASE_URL"]
    return Langfuse()


def _page_through_observations(
    langfuse: Langfuse,
    column: str,
    value: str,
    *,
    expand_metadata: list[str] | None = None,
) -> list[Observation]:
    """Every observation matching ``column = value``, following every cursor page.

    Never passes ``parse_io_as_json``: the v2 endpoint rejects it with HTTP 400.
    """
    observation_filter = json.dumps(
        [{"type": "string", "column": column, "operator": "=", "value": value}]
    )
    observations: list[Observation] = []
    cursor: str | None = None
    while True:
        response = langfuse.api.observations_v_2.get_many(
            fields=_FIELDS,
            filter=observation_filter,
            limit=_PAGE_SIZE,
            cursor=cursor,
            expand_metadata=",".join(expand_metadata) if expand_metadata else None,
        )
        observations.extend(Observation.model_validate(raw) for raw in response.data)
        cursor = response.meta.cursor
        if not cursor:
            return observations


def _may_be_truncated(observations: list[Observation]) -> list[str]:
    """The metadata keys whose values may have been cut at the truncation limit.

    Langfuse truncates per top-level key, and a truncated value comes back as a string, so a
    string at least as long as the limit is the signal. A value that is exactly that long and
    complete costs one unnecessary refetch, never a wrong answer.
    """
    keys: set[str] = set()
    for observation in observations:
        if isinstance(observation.metadata, dict):
            keys.update(
                key
                for key, value in observation.metadata.items()
                if isinstance(value, str) and len(value) >= _TRUNCATION_LIMIT
            )
    return sorted(keys)


def _fetch_trace(langfuse: Langfuse, trace_id: str) -> list[Observation]:
    """Every observation in one trace, with metadata never truncated.

    Must back each trace's observation set; never the session-filtered list (issue #435).
    """
    observations = _page_through_observations(langfuse, "traceId", trace_id)
    truncated = _may_be_truncated(observations)
    if not truncated:
        return observations
    keys = sorted(
        {
            key
            for observation in observations
            if isinstance(observation.metadata, dict)
            for key in observation.metadata
        }
    )
    logger.debug(
        "[langfuse] trace %s has metadata over %d chars (%s); refetching expanded",
        trace_id,
        _TRUNCATION_LIMIT,
        ", ".join(truncated),
    )
    return _page_through_observations(
        langfuse, "traceId", trace_id, expand_metadata=keys
    )


def _session_trace_ids(langfuse: Langfuse, session_id: str) -> list[str]:
    """The ids of every trace in the session, in first-seen order."""
    observations = _page_through_observations(langfuse, "sessionId", session_id)
    return list(dict.fromkeys(observation.trace_id for observation in observations))


Fingerprint = tuple[tuple[str, tuple[tuple[str, str | None, str | None], ...]], ...]
"""Each trace id with, for each observation, its id, end time and last update time."""


@dataclass(frozen=True)
class TraceWait:
    """The result of ``wait_for_settled_traces``.

    ``status`` is ``"settled"`` when two checks in a row matched and the traces were complete.
    Otherwise the timeout passed, and ``reason`` says why the session cannot be graded.
    """

    status: Literal["settled", "no_traces", "still_changing"]
    checks: int
    waited_seconds: float
    traces: dict[str, list[Observation]] = field(default_factory=dict)
    """Each trace id in first-seen order, with its observations from the last check."""

    @property
    def reason(self) -> str | None:
        """``NO_TRACES``, ``TRACES_CHANGING``, or ``None`` when the traces settled."""
        if self.status == "no_traces":
            return NO_TRACES
        if self.status == "still_changing":
            return TRACES_CHANGING
        return None


def _is_open(observation: Observation) -> bool:
    """True for an observation that has no end time yet."""
    return observation.end_time is None and observation.type not in _POINT_IN_TIME_TYPES


def _when(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _fingerprint(traces: dict[str, list[Observation]]) -> Fingerprint:
    return tuple(
        (
            trace_id,
            tuple(
                sorted(
                    (o.id, _when(o.end_time), _when(o.updated_at)) for o in observations
                )
            ),
        )
        for trace_id, observations in sorted(traces.items())
    )


def _is_complete(traces: dict[str, list[Observation]]) -> bool:
    """True when the session has a trace, no trace is empty and no observation is open."""
    return bool(traces) and all(
        observations and not any(_is_open(o) for o in observations)
        for observations in traces.values()
    )


def _check_session(langfuse: Langfuse, session_id: str) -> dict[str, list[Observation]]:
    """One check: every trace in the session, each fetched in full."""
    return {
        trace_id: _fetch_trace(langfuse, trace_id)
        for trace_id in _session_trace_ids(langfuse, session_id)
    }


def wait_for_settled_traces(
    langfuse: Langfuse,
    session_id: str,
    *,
    timeout: float,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> TraceWait:
    """Check the session until its traces stop changing, or until ``timeout`` seconds pass.

    Each check fetches the whole session again and makes a ``Fingerprint`` of it. The traces
    are settled when two checks in a row give the same fingerprint and the traces are
    complete: the session has a trace, no trace is empty and no observation is still open.
    The pause between checks grows as ``_BACKOFF_SECONDS`` says, so a run with many trials
    does not overload Langfuse. The last pause is cut short so that the final check is made
    at the timeout. There are always at least two checks, so a ``timeout`` of ``0`` checks
    twice with no pause.
    """
    started = clock()
    deadline = started + timeout
    previous: Fingerprint | None = None
    checks = 0
    while True:
        traces = _check_session(langfuse, session_id)
        checks += 1
        current = _fingerprint(traces)
        if current == previous and _is_complete(traces):
            return TraceWait("settled", checks, clock() - started, traces)
        now = clock()
        if checks >= 2 and now >= deadline:
            status = "still_changing" if traces else "no_traces"
            return TraceWait(status, checks, now - started, traces)
        previous = current
        pause = _BACKOFF_SECONDS[min(checks - 1, len(_BACKOFF_SECONDS) - 1)]
        sleep(max(0.0, min(pause, deadline - now)))


def _check_supported(
    session_id: str, trace_id: str, observations: list[Observation]
) -> None:
    """Raise ``UnsupportedTraceError`` if the trace shows the signs of a pre-v4 recording."""
    ids = [observation.id for observation in observations]
    synthetic_root = f"t-{trace_id}"
    reasons: list[str] = []
    if synthetic_root in ids:
        reasons.append(f"synthetic root `{synthetic_root}`")
    duplicated = len(ids) - len(set(ids))
    if duplicated:
        noun = "observation" if duplicated == 1 else "observations"
        reasons.append(f"{duplicated} duplicated {noun}")
    if reasons:
        raise UnsupportedTraceError(
            f"Session `{session_id}` can't be graded: trace `{trace_id}` was recorded "
            f"before this Langfuse server's v4 upgrade ({', '.join(reasons)}). "
            "Re-run the trial to grade it."
        )


def _resolve_artifacts(
    artifacts: list[Artifact], experiment_root: Path
) -> tuple[Artifact, ...]:
    """Artifacts with ``path`` rewritten from experiment-relative to a local file path."""
    resolved: list[Artifact] = []
    for artifact in artifacts:
        local = resolve_artifact_path(experiment_root, artifact.path)
        resolved.append(
            artifact.model_copy(update={"path": str(local) if local else None})
        )
    return tuple(resolved)


def fetch_session(
    session_id: str,
    langfuse: Langfuse,
    *,
    experiment_root: Path,
    artifacts: list[Artifact] | None = None,
    retry_timeout: float = 0,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> GradingInput:
    """Fetch one session as the ``GradingInput`` every grader run on it shares.

    Waits until the session's traces stop changing (see ``wait_for_settled_traces``), so a
    trial is never graded on part of a conversation. Holds every trace in the session, oldest
    root first, including traces whose root has no output: a crashed or timed-out exchange
    is part of what the target did. The run's artifacts are attached with their paths
    resolved against ``experiment_root``.

    :param retry_timeout: Seconds to wait for the traces to settle. ``0`` checks twice with
        no pause.
    :param clock: Seconds from a monotonic clock. Tests pass a fake one.
    :param sleep: The pause between checks. Tests pass a fake one.
    :raises TracesNotReadyError: When the traces are missing or still changing at the
        timeout. Its message is ``NO_TRACES`` or ``TRACES_CHANGING``.
    :raises UnsupportedTraceError: When a trace was recorded before the server's v4 upgrade.
    """
    wait = wait_for_settled_traces(
        langfuse, session_id, timeout=retry_timeout, clock=clock, sleep=sleep
    )
    logger.debug(
        "[langfuse] session %s: %s after %d checks in %.1fs",
        session_id,
        wait.status,
        wait.checks,
        wait.waited_seconds,
    )
    if wait.status != "settled":
        raise TracesNotReadyError(wait)

    traces: list[Trace] = []
    for trace_id, observations in wait.traces.items():
        _check_supported(session_id, trace_id, observations)
        traces.append(Trace.from_observations(trace_id, session_id, observations))
    traces.sort(key=_root_start)
    return GradingInput(
        traces=tuple(traces),
        artifacts=_resolve_artifacts(artifacts or [], experiment_root),
    )


def _root_start(trace: Trace) -> tuple[bool, float]:
    """Session order: by the root's ``start_time``, a trace with no time last."""
    start = trace.root.start_time
    return (start is None, start.timestamp() if start else 0.0)
