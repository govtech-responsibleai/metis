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

Input/output arrive as raw strings (``parse_io_as_json`` is rejected with HTTP 400), and
``metis.core.traces.Observation`` parses JSON-looking values itself.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from langfuse import Langfuse

from metis.core import Artifact, resolve_artifact_path
from metis.core.logging import get_logger
from metis.core.traces import GradingInput, Observation, Trace

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger(__name__)

_FIELDS = "core,basic,io,metadata"
_PAGE_SIZE = 1000
_TRUNCATION_LIMIT = 200
"""Langfuse truncates metadata values longer than this unless the key is expanded."""
_RETRY_SECONDS = 10


class UnsupportedTraceError(RuntimeError):
    """A session has a trace recorded before its Langfuse server's v4 upgrade (issue #469)."""


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
    retry_timeout: int = 0,
) -> GradingInput:
    """Fetch one session as the ``GradingInput`` every grader run on it shares.

    Holds every trace in the session, oldest root first, including traces whose root has no
    output: a crashed or timed-out exchange is part of what the target did. The run's
    artifacts are attached with their paths resolved against ``experiment_root``.

    :param retry_timeout: Seconds to keep polling while Langfuse returns no traces for the
        session (ingestion can lag a finished run); ``0`` asks once.
    :raises UnsupportedTraceError: When a trace was recorded before the server's v4 upgrade.
    :returns: A ``GradingInput`` with ``traces=()`` when the session has none, so the
        caller can tell "nothing ingested" apart from an error.
    """
    deadline = time.time() + retry_timeout
    while True:
        trace_ids = _session_trace_ids(langfuse, session_id)
        if trace_ids or time.time() >= deadline:
            break
        time.sleep(_RETRY_SECONDS)

    traces: list[Trace] = []
    for trace_id in trace_ids:
        observations = _fetch_trace(langfuse, trace_id)
        if not observations:
            # Found by the session filter but empty by traceId: an ingestion race. A trace
            # with no observations cannot be built, and there is nothing in it to grade.
            logger.warning(
                "[langfuse] trace %s in session %s returned no observations; skipping",
                trace_id,
                session_id,
            )
            continue
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
