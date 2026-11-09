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
grades nothing until Langfuse has stored no new data for the session for
``DEFAULT_QUIET_SECONDS``, or the number of seconds that the caller sets (see
``wait_for_settled_traces``).

Input/output arrive as raw strings (``parse_io_as_json`` is rejected with HTTP 400), and
``metis.core.traces.Observation`` parses JSON-looking values itself.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from langfuse import Langfuse

from metis.core import Artifact, resolve_artifact_path
from metis.core.logging import get_logger
from metis.core.traces import GradingInput, Observation, Trace

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = get_logger(__name__)

_FIELDS = "core,basic,time,io,metadata"
"""``time`` holds ``updatedAt``, which the trace wait reads."""
_PAGE_SIZE = 1000
_TRUNCATION_LIMIT = 200
"""Langfuse truncates metadata values longer than this unless the key is expanded."""
DEFAULT_QUIET_SECONDS = 30.0
"""The traces are ready when Langfuse has stored nothing new for this long. The Langfuse SDK
sends finished spans in batches about every 5 seconds, so the default covers several batches."""
_RETRY_SECONDS = 5.0
"""The pause before the next check while the session has no trace or an empty trace, so there
is no stored time to count from."""
_POINT_IN_TIME_TYPES = frozenset({"EVENT"})
"""Observation types that record one moment. Langfuse can store them with no end time, so
they never count as open."""

NO_TRACES = "no traces in Langfuse"
"""Failure reason: Langfuse returned no trace for the session before the timeout."""
TRACES_CHANGING = "traces still changing in Langfuse"
"""Failure reason: traces arrived, but Langfuse kept storing new data for the session until
the timeout."""


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


@dataclass(frozen=True)
class OpenObservation:
    """An observation that Langfuse stores with no end time."""

    trace_id: str
    id: str
    name: str | None


@dataclass(frozen=True)
class TraceWait:
    """The result of ``wait_for_settled_traces``.

    ``status`` is ``"settled"`` when Langfuse had stored nothing new for the quiet window.
    Otherwise the timeout passed, and ``reason`` says why the session cannot be graded.
    """

    status: Literal["settled", "no_traces", "still_changing"]
    checks: int
    waited_seconds: float
    traces: dict[str, list[Observation]] = field(default_factory=dict)
    """Each trace id in first-seen order, with its observations from the last check."""
    open_observations: tuple[OpenObservation, ...] = ()
    """Observations with no end time in the last check. They do not hold the wait: a target
    that crashed never ends them, and its traces are graded as Langfuse stores them."""

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


def _stored_at(observation: Observation) -> datetime | None:
    """When Langfuse last stored this row: ``updatedAt``, else the end or start time."""
    stamp = observation.updated_at or observation.end_time or observation.start_time
    if stamp is not None and stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return stamp


def _stored_age(traces: dict[str, list[Observation]], now: datetime) -> float:
    """Seconds since Langfuse last stored any row of the session, ``0`` if a row has no time.

    The age compares Langfuse's times with this machine's clock, so a clock that is off
    moves the result by the same amount.
    """
    stamps = [_stored_at(o) for observations in traces.values() for o in observations]
    if not stamps or any(stamp is None for stamp in stamps):
        return 0.0
    newest = max(stamp for stamp in stamps if stamp is not None)
    return max(0.0, (now - newest).total_seconds())


def _open_observations(
    traces: dict[str, list[Observation]],
) -> tuple[OpenObservation, ...]:
    return tuple(
        OpenObservation(trace_id, o.id, o.name)
        for trace_id, observations in traces.items()
        for o in observations
        if _is_open(o)
    )


def _check_session(langfuse: Langfuse, session_id: str) -> dict[str, list[Observation]]:
    """One check: every trace in the session, each fetched in full."""
    return {
        trace_id: _fetch_trace(langfuse, trace_id)
        for trace_id in _session_trace_ids(langfuse, session_id)
    }


def _utc_now() -> datetime:
    return datetime.now(UTC)


def wait_for_settled_traces(
    langfuse: Langfuse,
    session_id: str,
    *,
    timeout: float,
    quiet_seconds: float = DEFAULT_QUIET_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    utc_now: Callable[[], datetime] = _utc_now,
) -> TraceWait:
    """Check the session until Langfuse has stored nothing new for ``quiet_seconds``.

    METIS cannot know when a conversation has ended. It can only see when Langfuse last stored
    data for it. So each check fetches the whole session and reads the newest stored time of
    any row (see ``_stored_age``). The traces are ready when the session has a trace, no
    trace is empty, and that time is at least ``quiet_seconds`` old. Old traces are ready on
    the first check. An observation with no end time does not hold the wait.
    ``TraceWait.open_observations`` lists it.

    When the traces are not ready, the next check is made when the newest row will be
    ``quiet_seconds`` old. New data in the meantime makes that check wait again. While there
    is no stored time to count from, the pause is ``_RETRY_SECONDS``. Every pause is cut
    short at the timeout, so the last check is made at the timeout. A ``timeout`` of ``0``
    checks once.
    """
    started = clock()
    deadline = started + timeout
    checks = 0
    while True:
        traces = _check_session(langfuse, session_id)
        checks += 1
        now = clock()
        has_every_trace = bool(traces) and all(traces.values())
        age = _stored_age(traces, utc_now())
        if has_every_trace and age >= quiet_seconds:
            return TraceWait(
                "settled", checks, now - started, traces, _open_observations(traces)
            )
        if now >= deadline:
            status = "still_changing" if traces else "no_traces"
            return TraceWait(
                status, checks, now - started, traces, _open_observations(traces)
            )
        pause = quiet_seconds - age if has_every_trace else _RETRY_SECONDS
        sleep(min(pause, deadline - now))


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
    quiet_seconds: float = DEFAULT_QUIET_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    utc_now: Callable[[], datetime] = _utc_now,
    on_wait: Callable[[TraceWait], None] | None = None,
) -> GradingInput:
    """Fetch one session as the ``GradingInput`` every grader run on it shares.

    Waits until Langfuse has stored nothing new for the session for ``quiet_seconds`` (see
    ``wait_for_settled_traces``). Data that Langfuse stores after that is not graded.
    Holds every trace in the session, oldest root first, including traces whose root has no
    output: a crashed or timed-out exchange is part of what the target did. The run's
    artifacts are attached with their paths resolved against ``experiment_root``.

    :param retry_timeout: Seconds to wait for the traces to settle. ``0`` checks once.
    :param quiet_seconds: How long Langfuse must store nothing new before the traces count as
        ready.
    :param clock: Seconds from a monotonic clock. Tests pass a fake one.
    :param sleep: The pause between checks. Tests pass a fake one.
    :param utc_now: The current UTC time, compared with Langfuse's ``updatedAt``. Tests pass
        a fake one.
    :param on_wait: Called with the ``TraceWait`` before the traces are graded or the error
        is raised, so the caller can log the checks, the time waited and any open
        observations.
    :raises TracesNotReadyError: When the traces are missing or still changing at the
        timeout. Its message is ``NO_TRACES`` or ``TRACES_CHANGING``.
    :raises UnsupportedTraceError: When a trace was recorded before the server's v4 upgrade.
    """
    wait = wait_for_settled_traces(
        langfuse,
        session_id,
        timeout=retry_timeout,
        quiet_seconds=quiet_seconds,
        clock=clock,
        sleep=sleep,
        utc_now=utc_now,
    )
    if on_wait is not None:
        on_wait(wait)
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
