"""What a grader reads: the Langfuse traces of one session.

METIS supports Langfuse v4 only. In v4 a trace is not stored as an object of its own: it is the
set of observations sharing a ``traceId``, and its input and output are those of its logical
root observation. ``Observation`` is one row of Observations API v2, ``Trace`` is the group METIS
builds from those rows, and ``GradingInput`` is the whole session plus the artifacts the run
produced.

These live in ``metis-core`` because the engine, the saved traces and ``metis-insights`` all read
them, and ``insights`` may depend only on ``core``. Holding Langfuse's SDK type instead would make
``core`` depend on ``langfuse``.

Every model here is frozen and every collection is a tuple, because one ``GradingInput`` is
shared by every grader run on a session, and those runs execute concurrently. A grader that
tries to reassign or reorder its input fails on its own line. ``input``/``output``/``metadata``
are ``Any`` and usually hold parsed dicts, which freezing does not protect, so graders must
treat them as read-only too.
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import cached_property
from typing import TYPE_CHECKING, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

from metis.core.artifacts import Artifact
from metis.core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

logger = get_logger(__name__)


def _maybe_json(value: object) -> object:
    """Parse *value* as JSON only when it looks like an object or array.

    Langfuse rejects ``parse_io_as_json`` on the v2 endpoint and returns input/output as raw
    strings. A string is parsed only when it starts with ``{`` or ``[``, and the parse is kept
    only if it produced a dict or list, so a plain-text answer like ``"42"`` or ``"true"`` stays
    a string.
    """
    if not isinstance(value, str) or value.lstrip()[:1] not in ("{", "["):
        return value
    try:
        parsed = json.loads(value)
    except ValueError:
        return value
    return parsed if isinstance(parsed, (dict, list)) else value


class Observation(BaseModel):
    """One Langfuse observation, as returned by Observations API v2.

    Holds the subset of Observations API v2 fields that graders read, under the same names.
    Fields METIS does not use are not fields here, but the whole row is kept in ``raw`` so it
    can be saved without loss. A raw API row validates directly: its
    camelCase keys (``traceId``) map onto the snake_case fields, and every field except the two
    ids may be missing. A field is ``None`` both when it is empty and when its field group was
    not requested, so the fetch requests every group these fields come from.
    """

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="ignore", frozen=True
    )

    id: str
    trace_id: str
    session_id: str | None = None
    parent_observation_id: str | None = None
    is_root_observation: bool | None = None
    """Langfuse's logical-root flag; see ``Trace.root``. May be absent on every observation in a
    trace at once."""
    type: str | None = None
    """E.g. ``"SPAN"``, ``"GENERATION"``, ``"TOOL"``. A ``str``, not a ``Literal``: Langfuse has
    added observation types before, and a ``Literal`` would reject every observation of a type
    METIS does not know yet."""
    name: str | None = None
    level: str | None = None
    """Langfuse's severity: ``"DEBUG"``, ``"DEFAULT"``, ``"WARNING"`` or ``"ERROR"``."""
    status_message: str | None = None
    """Langfuse's ``statusMessage``, usually the error text when ``level`` is ``"ERROR"``."""
    start_time: datetime | None = None
    end_time: datetime | None = None
    input: Any = None
    """A JSON object or array string is parsed; see ``_maybe_json``."""
    output: Any = None
    """Parsed the same way as ``input``."""
    metadata: Any = None
    """Fetched with ``expandMetadata``, so never truncated."""
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True, repr=False)
    """The row this observation was validated from, untouched: every key the API sent, the
    original input/output strings and the original timestamp strings. It exists so the
    observation can be saved without loss (``SessionTraces``), and so the trace processor
    (``metis.core.trace_processing``) can show a payload exactly as the application sent it.
    Nothing outside the trace processor reads it. It is left out of ``model_dump`` and
    ``repr`` so no log line or judge prompt picks up a second copy of every payload. An
    observation built from keyword arguments holds those arguments here, not a Langfuse row."""

    @model_validator(mode="before")
    @classmethod
    def _keep_row(cls, data: object) -> object:
        if isinstance(data, dict) and "raw" not in data:
            return {**data, "raw": data}
        return data

    @field_validator("input", "output", mode="before")
    @classmethod
    def _parse_io(cls, value: object) -> object:
        return _maybe_json(value)


def _oldest_first(observation: Observation) -> tuple[bool, float]:
    """Sort key for storage order: by ``start_time``, missing times last.

    The placeholder ``0.0`` keeps the key comparable when two observations both lack a time;
    ``sorted`` is stable, so those keep their relative order.
    """
    start = observation.start_time
    return (start is None, start.timestamp() if start else 0.0)


def _earliest_with_missing_first(observation: Observation) -> tuple[bool, float]:
    """Tie-break key for ``Trace.root``: a missing ``start_time`` counts as earliest."""
    start = observation.start_time
    return (start is not None, start.timestamp() if start else 0.0)


class Trace(BaseModel, frozen=True):
    """One exchange between persona and target.

    ``Trace`` has no ``input``/``output`` of its own. Langfuse's default is that a trace's input
    and output are the root observation's, but an application can override that per trace, so a
    grader reads them from whichever observation it considers authoritative, which is usually
    ``trace.root.input`` / ``trace.root.output``.
    """

    id: str
    """The Langfuse ``traceId`` shared by every observation in ``observations``."""

    session_id: str
    """The Langfuse ``sessionId``; every trace of one simulated conversation shares it."""

    observations: tuple[Observation, ...] = Field(min_length=1)
    """Every observation with this ``traceId``, oldest first by ``start_time``, with any
    observation lacking a ``start_time`` last. Never empty, since a trace is only known through
    one of its observations."""

    @field_validator("observations")
    @classmethod
    def _sort_oldest_first(
        cls, observations: tuple[Observation, ...]
    ) -> tuple[Observation, ...]:
        return tuple(sorted(observations, key=_oldest_first))

    @classmethod
    def from_observations(
        cls, trace_id: str, session_id: str, observations: Iterable[Observation]
    ) -> Trace:
        """Build a trace from one ``traceId``'s rows, in any order."""
        return cls(id=trace_id, session_id=session_id, observations=tuple(observations))

    @cached_property
    def root(self) -> Observation:
        """The observation Langfuse marks as this trace's logical root.

        Found by ``is_root_observation`` when any observation in the trace has it set. If no
        observation has it set, falls back to the observation with no
        ``parent_observation_id``. The flag can mean an SDK-detected "app root" rather than a
        parentless span, so the fallback applies only when the flag is absent from the whole
        trace, not when it is merely false.

        Several flagged candidates narrow to the one with no ``parent_observation_id``, because
        a flagged observation with a parent is not the top of its trace. Some applications flag
        a sub-agent's own top span as a root as well as the turn's span.

        Zero or several candidates that this does not resolve (an ingestion gap, or a retry
        that re-emitted a root) fall back to the earliest ``start_time``, with a missing time
        counted as earliest, and a warning logged. This does not raise, so one malformed trace
        cannot crash an evaluation run.
        """
        observations = self.observations
        if any(o.is_root_observation is not None for o in observations):
            candidates = [o for o in observations if o.is_root_observation]
            parentless = [o for o in candidates if o.parent_observation_id is None]
            if len(candidates) > 1 and len(parentless) == 1:
                return parentless[0]
        else:
            candidates = [o for o in observations if o.parent_observation_id is None]

        if len(candidates) == 1:
            return candidates[0]

        logger.warning(
            "[traces] trace %s has %d root candidates; falling back to earliest start_time",
            self.id,
            len(candidates),
        )
        return min(candidates or observations, key=_earliest_with_missing_first)


class GradingInput(BaseModel, frozen=True):
    """Everything one grader run sees: the whole session and the run's artifacts."""

    traces: tuple[Trace, ...]
    """The whole session, in order, including traces whose root has no output (the target
    crashed or timed out mid-answer). A missing reply is the target failing, so it is evidence
    to grade: ``Turn.target_errors`` records it."""

    artifacts: tuple[Artifact, ...] = ()
    """Every artifact the run produced, with ``path`` already resolved to a local file path.
    ``()`` when the run produced none. Not tied to individual traces (see issue #428, "Open
    questions and known gaps")."""


_SESSION_TRACES_VERSION = 1
_SESSION_TRACES_SOURCE = "langfuse-observations-v2"


class SavedTrace(BaseModel, frozen=True):
    """One trace as saved: its id and the Langfuse rows of its observations."""

    id: str
    observations: tuple[dict[str, Any], ...]


class SessionTraces(BaseModel, frozen=True):
    """A session's traces as `metis engine evaluate` saved them, for `metis insights report`.

    Holds the rows Langfuse returned (``Observation.raw``), not a dump of the typed models, so
    nothing that was fetched is lost and no payload is written twice. Loading validates each row
    through ``Observation`` again, which refills ``raw``, so a load followed by a save writes the
    same file. Artifacts are not saved: their paths are local to the machine that ran evaluate.
    """

    schema_version: Literal[1] = _SESSION_TRACES_VERSION
    source: Literal["langfuse-observations-v2"] = _SESSION_TRACES_SOURCE
    """The API the rows come from. Rows of another API shape would validate as observations with
    nothing in them, so the file names its source to be recognised instead of misread."""
    session_id: str
    traces: tuple[SavedTrace, ...]

    @model_validator(mode="before")
    @classmethod
    def _check_supported(cls, data: object) -> object:
        """Reject an explicit version or source we cannot read; a missing key takes the default."""
        if not isinstance(data, dict):
            return data
        version = data.get("schema_version")
        if version is not None and version != _SESSION_TRACES_VERSION:
            raise ValueError(
                f"Unsupported schema_version {version!r} (expected {_SESSION_TRACES_VERSION}). "
                "This file was saved by a different version of metis-engine."
            )
        source = data.get("source")
        if source is not None and source != _SESSION_TRACES_SOURCE:
            raise ValueError(
                f"Unsupported source {source!r} (expected {_SESSION_TRACES_SOURCE!r}). "
                "These rows come from a Langfuse API this version of METIS does not read."
            )
        return data

    @classmethod
    def from_traces(cls, session_id: str, traces: Iterable[Trace]) -> Self:
        """The traces as saved rows, in the order given."""
        return cls(
            session_id=session_id,
            traces=tuple(
                SavedTrace(
                    id=trace.id,
                    observations=tuple(
                        observation.raw for observation in trace.observations
                    ),
                )
                for trace in traces
            ),
        )

    def to_traces(self) -> tuple[Trace, ...]:
        """The saved rows built back into ``Trace``s, in the order saved."""
        return tuple(
            Trace.from_observations(
                saved.id,
                self.session_id,
                [Observation.model_validate(row) for row in saved.observations],
            )
            for saved in self.traces
        )

    @classmethod
    def load_file(cls, path: Path) -> Self:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, path: Path) -> None:
        """Write the file as UTF-8 JSON, creating the parent directory."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=1) + "\n", encoding="utf-8")
