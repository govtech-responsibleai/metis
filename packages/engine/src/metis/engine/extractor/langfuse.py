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
grades nothing until Langfuse has stored no new data for the session for the quiet window
(see ``wait_for_settled_traces``).

The fetch is asynchronous, on ``langfuse.async_api``, so a session waiting on Langfuse holds
no thread and many sessions can be fetched at once.

Input/output arrive as raw strings (``parse_io_as_json`` is rejected with HTTP 400), and
``metis.core.traces.Observation`` parses JSON-looking values itself.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

import httpx
from langfuse import Langfuse
from langfuse.api.core.api_error import ApiError

from metis.core import Artifact, resolve_artifact_path
from metis.core.logging import get_logger
from metis.core.traces import GradingInput, Observation, Trace

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from pathlib import Path

logger = get_logger(__name__)

_FIELDS = "core,basic,time,io,metadata"
"""``time`` holds ``updatedAt``, which the trace wait reads."""
_PAGE_SIZE = 1000
_TRUNCATION_LIMIT = 200
"""Langfuse truncates metadata values longer than this unless the key is expanded."""
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
_MAX_RETRIES = 3
"""How many times one page request is retried after its first try."""
_RETRY_BASE_SECONDS = 0.5
_RETRY_CAP_SECONDS = 10
_RETRYABLE_ERRORS = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
)
"""Transport failures worth another try: a timeout, a refused or dropped connection."""
_RETRYABLE_STATUSES = frozenset({408, 409, 429})
"""Statuses below 500 worth another try, the same set the Langfuse SDK retries."""


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
    if os.environ.get("LANGFUSE_BASE_URL") and not os.environ.get("LANGFUSE_HOST"):
        os.environ["LANGFUSE_HOST"] = os.environ["LANGFUSE_BASE_URL"]
    return Langfuse()


def _retry_delay(retry: int) -> float:
    """Exponential backoff with jitter, the same shape the Langfuse SDK uses for statuses."""
    delay = min(_RETRY_BASE_SECONDS * 2.0**retry, _RETRY_CAP_SECONDS)
    return delay * (1 - 0.25 * random.random())


def _is_retryable(exc: Exception) -> bool:
    """A transport failure, or a response with status 408, 409, 429 or 5xx."""
    if isinstance(exc, _RETRYABLE_ERRORS):
        return True
    if isinstance(exc, ApiError) and exc.status_code is not None:
        return exc.status_code in _RETRYABLE_STATUSES or exc.status_code >= 500
    return False


async def _get_page(langfuse: Langfuse, **request: Any) -> Any:
    """One ``get_many`` call, retried when Langfuse or the network is briefly unavailable.

    With ``--concurrency N`` several sessions call Langfuse at once, so a rate limit or a slow
    reply is expected now and then. This loop retries, up to ``_MAX_RETRIES`` times with the
    growing wait of ``_retry_delay``, both a response with status 408, 409, 429 or 5xx and a
    timeout or connection error. Any other failure, such as a 401 for a bad key, is raised
    at once.

    ``request_options`` is never passed, so the SDK's own retries stay off. With it set, the
    SDK sends a JSON body ``{}`` with the GET, which a proxy in front of Langfuse may reject
    with HTTP 400 (issue #122). ``Retry-After`` is not honoured: the SDK's ``ApiError`` keeps
    only the status and body, not the response headers.
    """
    for retry in range(_MAX_RETRIES + 1):
        try:
            return await langfuse.async_api.observations_v_2.get_many(**request)
        except (*_RETRYABLE_ERRORS, ApiError) as exc:
            if retry == _MAX_RETRIES or not _is_retryable(exc):
                raise
            reason = (
                f"HTTP {exc.status_code}"
                if isinstance(exc, ApiError)
                else type(exc).__name__
            )
            logger.warning(
                "[langfuse] %s on an observations request; retrying (%d/%d)",
                reason,
                retry + 1,
                _MAX_RETRIES,
            )
            await asyncio.sleep(_retry_delay(retry))
    raise AssertionError("unreachable")  # the loop always returns or raises


async def _page_through_observations(
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
        response = await _get_page(
            langfuse,
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


async def _fetch_trace(langfuse: Langfuse, trace_id: str) -> list[Observation]:
    """Every observation in one trace, with metadata never truncated.

    Must back each trace's observation set; never the session-filtered list (issue #435).
    """
    observations = await _page_through_observations(langfuse, "traceId", trace_id)
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
    return await _page_through_observations(
        langfuse, "traceId", trace_id, expand_metadata=keys
    )


async def _session_trace_ids(langfuse: Langfuse, session_id: str) -> list[str]:
    """The ids of every trace in the session, in first-seen order."""
    observations = await _page_through_observations(langfuse, "sessionId", session_id)
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


async def _check_session(
    langfuse: Langfuse, session_id: str
) -> dict[str, list[Observation]]:
    """One check: every trace in the session, each fetched in full."""
    return {
        trace_id: await _fetch_trace(langfuse, trace_id)
        for trace_id in await _session_trace_ids(langfuse, session_id)
    }


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class TraceWaitSettings:
    """How long to wait for a trial's traces.

    The quiet window is how long Langfuse must store nothing new for the session before
    METIS grades it. The timeout is the longest time that METIS waits for the session. The
    timeout must be at least as long as the quiet window, because a trial that has just
    finished needs the full quiet window before it can be graded.

    The Langfuse SDK sends finished spans in batches about every 5 seconds, so the default
    quiet window of 30 seconds covers several batches.
    """

    timeout_seconds: float
    quiet_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.timeout_seconds < self.quiet_seconds:
            raise ValueError(
                f"The Langfuse timeout is {self.timeout_seconds:g} seconds, but the quiet "
                f"window (LANGFUSE_METIS_QUIET_SECONDS) is {self.quiet_seconds:g} seconds. "
                "A trial that has just finished needs the full quiet window before it can "
                f"be graded. Set the timeout to {self.quiet_seconds:g} seconds or more."
            )

    @classmethod
    def from_env(
        cls, timeout_seconds: float, environ: Mapping[str, str] = os.environ
    ) -> TraceWaitSettings:
        """Read the quiet window from ``LANGFUSE_METIS_QUIET_SECONDS``, 30 when it is not set.

        METIS reads this variable, and the Langfuse SDK does not.

        :raises ValueError: When the value is not a number, or when the timeout is shorter
            than the quiet window.
        """
        value = environ.get("LANGFUSE_METIS_QUIET_SECONDS", "30")
        try:
            quiet = float(value)
        except ValueError:
            raise ValueError(
                f"LANGFUSE_METIS_QUIET_SECONDS must be a number of seconds, got {value!r}"
            ) from None
        return cls(timeout_seconds=timeout_seconds, quiet_seconds=quiet)


async def wait_for_settled_traces(
    langfuse: Langfuse,
    session_id: str,
    *,
    settings: TraceWaitSettings,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    utc_now: Callable[[], datetime] = _utc_now,
) -> TraceWait:
    """Check the session until Langfuse has stored nothing new for the quiet window.

    ``settings`` gives the quiet window and the timeout.

    METIS cannot know when a conversation has ended. It can only see when Langfuse last stored
    data for it. So each check fetches the whole session and reads the newest stored time of
    any row (see ``_stored_age``). The traces are ready when the session has a trace, no
    trace is empty, and that time is at least as old as the quiet window. Old traces are
    ready on the first check. An observation with no end time does not hold the wait.
    ``TraceWait.open_observations`` lists it.

    When the traces are not ready, the next check is made when the newest row will be as
    old as the quiet window. New data in the meantime makes that check wait again. While there
    is no stored time to count from, the pause is ``_RETRY_SECONDS``. Every pause is cut
    short at the timeout, so the last check is made at the timeout.
    """
    quiet = settings.quiet_seconds
    started = clock()
    deadline = started + settings.timeout_seconds
    checks = 0
    while True:
        traces = await _check_session(langfuse, session_id)
        checks += 1
        now = clock()
        has_every_trace = bool(traces) and all(traces.values())
        age = _stored_age(traces, utc_now())
        if has_every_trace and age >= quiet:
            return TraceWait(
                "settled", checks, now - started, traces, _open_observations(traces)
            )
        if now >= deadline:
            status = "still_changing" if traces else "no_traces"
            return TraceWait(
                status, checks, now - started, traces, _open_observations(traces)
            )
        pause = quiet - age if has_every_trace else _RETRY_SECONDS
        await sleep(min(pause, deadline - now))


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


async def fetch_session(
    session_id: str,
    langfuse: Langfuse,
    *,
    experiment_root: Path,
    artifacts: list[Artifact] | None = None,
    settings: TraceWaitSettings,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    utc_now: Callable[[], datetime] = _utc_now,
    on_wait: Callable[[TraceWait], None] | None = None,
) -> GradingInput:
    """Fetch one session as the ``GradingInput`` every grader run on it shares.

    Waits until Langfuse has stored nothing new for the session for the quiet window (see
    ``wait_for_settled_traces``). Data that Langfuse stores after that is not graded.
    Holds every trace in the session, oldest root first, including traces whose root has no
    output: a crashed or timed-out exchange is part of what the target did. The run's
    artifacts are attached with their paths resolved against ``experiment_root``.

    :param settings: The quiet window and the timeout of the trace wait.
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
    wait = await wait_for_settled_traces(
        langfuse,
        session_id,
        settings=settings,
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
