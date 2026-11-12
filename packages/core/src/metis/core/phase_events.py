"""logs/events.jsonl: the progress of an experiment, one JSON event per line.

The engine appends one ``PhaseEvent`` per line while ``simulate``, ``evaluate`` or ``run``
works on an experiment folder. A reader, such as a browser that shows the progress, can
follow the file as it grows.

Every line has the same five fields, in this order:

- ``seq`` numbers the lines of the file from 1, one more on each line. A resumed command
  appends to the same file and continues the count, so ``seq`` identifies one event in
  the file for good. A reader that has seen up to ``seq`` N reads on from N + 1.
- ``at`` is the UTC time at which the engine wrote the event.
- ``phase`` is ``simulating`` or ``evaluating``.
- ``trial`` is the trial's folder name under ``outputs/trials/``, the one key that names a
  trial in both phases. It is ``null`` on a line about the whole phase.
- ``status`` is what happened.

A line can also have some of ``total``, ``done``, ``attempt``, ``turn`` and ``reason``.
``_SHAPES`` says which of them each kind of line has.

Each phase starts with a phase line ``started`` and ends with a phase line ``completed``,
``failed`` or ``interrupted``. A simulation that stops before it counts its trials
writes only its end line. The last phase line of a command gives how the command
ended. When a phase fails or is interrupted, the command ends, and each later phase that
it did not start gets a phase line ``skipped``.

An event holds IDs, counts, statuses and short reasons only. It never holds a key, a
prompt or a model reply. ``emit`` cuts a reason to ``REASON_MAX_LENGTH`` characters.

The published schema is ``schemas/phase-event.schema.json``, versioned by
``_PHASE_EVENT_VERSION``.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from metis.core.execution_layout import EVENTS_FILE, LOGS
from metis.core.logging import get_logger

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger(__name__)

_PHASE_EVENT_VERSION = 1
REASON_MAX_LENGTH = 300
INTERRUPTED_REASON = "Stopped by Ctrl-C"

Phase = Literal["simulating", "evaluating"]
Status = Literal[
    "started", "running", "retrying", "completed", "failed", "interrupted", "skipped"
]
Reason = Annotated[str, Field(max_length=REASON_MAX_LENGTH)]

_EXTRAS = ("total", "done", "attempt", "turn", "reason")


@dataclass(frozen=True)
class _Shape:
    """One kind of line: its phase (``None`` for either), whether it names a trial, its
    status, and the extra fields that it must have and may have."""

    phase: Phase | None
    on_trial: bool
    status: Status
    required: frozenset[str] = frozenset()
    optional: frozenset[str] = frozenset()


def _shape(
    phase: Phase | None,
    on_trial: bool,
    status: Status,
    required: tuple[str, ...] = (),
    optional: tuple[str, ...] = (),
) -> _Shape:
    return _Shape(phase, on_trial, status, frozenset(required), frozenset(optional))


_SHAPES = (
    _shape(None, False, "started", required=("total", "done")),
    _shape(None, False, "completed"),
    _shape(None, False, "failed", optional=("reason",)),
    _shape(None, False, "interrupted", optional=("reason",)),
    _shape(None, False, "skipped"),
    _shape("simulating", True, "started", required=("attempt",)),
    _shape("simulating", True, "running", required=("attempt", "turn")),
    _shape("simulating", True, "retrying", required=("attempt",), optional=("reason",)),
    _shape("simulating", True, "completed", required=("attempt",)),
    _shape("simulating", True, "failed", required=("attempt",), optional=("reason",)),
    _shape(
        "simulating", True, "interrupted", required=("attempt",), optional=("reason",)
    ),
    _shape("evaluating", True, "started"),
    _shape("evaluating", True, "completed"),
    _shape("evaluating", True, "failed", optional=("reason",)),
)


def short_reason(text: str | None) -> str | None:
    """``text`` on one line and cut to ``REASON_MAX_LENGTH`` characters, or ``None``."""
    if not text:
        return None
    flat = " ".join(text.split())
    if len(flat) <= REASON_MAX_LENGTH:
        return flat
    return flat[: REASON_MAX_LENGTH - 3] + "..."


def _publish_shapes(schema: dict[str, Any]) -> None:
    """Each line must match one entry of ``_SHAPES``, so the schema lists them all."""
    shapes = []
    for shape in _SHAPES:
        properties: dict[str, Any] = {
            "status": {"const": shape.status},
            "trial": {"type": "string" if shape.on_trial else "null"},
        }
        if shape.phase:
            properties["phase"] = {"const": shape.phase}
        entry: dict[str, Any] = {
            "properties": properties,
            "required": sorted(shape.required),
        }
        forbidden = [
            name
            for name in _EXTRAS
            if name not in shape.required and name not in shape.optional
        ]
        if forbidden:
            entry["not"] = {"anyOf": [{"required": [name]} for name in forbidden]}
        shapes.append(entry)
    schema["oneOf"] = shapes


class PhaseEvent(BaseModel):
    """One line of ``logs/events.jsonl``. Validate a line with ``PhaseEvent.parse_line``."""

    model_config = ConfigDict(json_schema_extra=_publish_shapes)

    seq: int = Field(ge=1, description="Line number of the event in the file, from 1.")
    at: AwareDatetime = Field(
        description="UTC time at which the engine wrote the event."
    )
    phase: Phase
    trial: str | None = Field(
        description="The trial's folder name under outputs/trials/, or null for the phase."
    )
    status: Status
    total: int | None = Field(
        default=None, ge=0, description="Trials in the phase, done ones included."
    )
    done: int | None = Field(
        default=None,
        ge=0,
        description="Trials that an earlier command already finished in this phase.",
    )
    attempt: int | None = Field(
        default=None,
        ge=1,
        description="The attempt of the trial, from 1. On retrying, the one that failed.",
    )
    turn: int | None = Field(
        default=None, ge=1, description="Turns of the attempt that are done."
    )
    reason: Reason | None = None

    @model_validator(mode="after")
    def _has_the_fields_of_its_shape(self) -> PhaseEvent:
        on_trial = self.trial is not None
        shape = next(
            (
                shape
                for shape in _SHAPES
                if shape.on_trial == on_trial
                and shape.status == self.status
                and shape.phase in (None, self.phase)
            ),
            None,
        )
        line = f"{self.phase} {'trial' if on_trial else 'phase'} line"
        if shape is None:
            raise ValueError(f"A {line} cannot be {self.status}.")
        present = {name for name in _EXTRAS if getattr(self, name) is not None}
        if missing := shape.required - present:
            raise ValueError(f"A {self.status} {line} needs {sorted(missing)}.")
        if extra := present - shape.required - shape.optional:
            raise ValueError(f"A {self.status} {line} cannot have {sorted(extra)}.")
        return self

    @classmethod
    def parse_line(cls, line: str) -> PhaseEvent:
        """The event that one line of the file holds."""
        return cls.model_validate_json(line)


class PhaseEventLog:
    """Appends events to one ``events.jsonl`` file and numbers them.

    Each event continues the ``seq`` of the last line in the file, so a resumed command, or
    an ``evaluate`` after a ``simulate``, numbers on from where the file ends.
    Each event is one write of one whole line, flushed at once, under a lock, so worker
    threads that share a log never split or reorder a line. When the file changed since
    the log last wrote to it, the log reads the last ``seq`` from the file again.

    The file is a progress feed, so a failed read or write never stops the work that it
    reports. On an ``OSError``, ``emit`` drops the line and returns the event. The log
    writes one warning for the first failure, and each later ``emit`` tries the file again.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._seq = 0
        self._size: int | None = None
        """The file size after the last write, or ``None`` before the first one."""
        self._warned = False

    @classmethod
    def for_experiment_dir(cls, root: Path) -> PhaseEventLog:
        """The log of the experiment folder ``root``, at ``logs/events.jsonl``."""
        return cls(root / LOGS / EVENTS_FILE)

    def emit(
        self,
        phase: Phase,
        status: Status,
        *,
        trial: str | None = None,
        total: int | None = None,
        done: int | None = None,
        attempt: int | None = None,
        turn: int | None = None,
        reason: str | None = None,
    ) -> PhaseEvent:
        """Write one event with the next ``seq``, and return it."""
        with self._lock:
            prefix = ""
            try:
                if self._size != _size(self.path):
                    self._seq, ended = _read_end(self.path)
                    prefix = "" if ended else "\n"
            except OSError as exc:
                self._file_failed(exc)
            event = PhaseEvent(
                seq=self._seq + 1,
                at=datetime.now(UTC),
                phase=phase,
                trial=trial,
                status=status,
                total=total,
                done=done,
                attempt=attempt,
                turn=turn,
                reason=short_reason(reason),
            )
            line = prefix + _line(event) + "\n"
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
                    handle.flush()
                    self._size = handle.tell()
            except OSError as exc:
                self._file_failed(exc)
                return event
            self._seq = event.seq
            return event

    def _file_failed(self, exc: OSError) -> None:
        """Warn about the first failure, and read the end of the file on the next emit.

        A write that stopped part of the way can leave a cut line. The next read closes
        that line and skips it.
        """
        self._size = -1
        if not self._warned:
            self._warned = True
            logger.warning(
                "[phase_events] cannot write %s; progress events are dropped: %s: %s",
                self.path,
                type(exc).__name__,
                exc,
            )


def _line(event: PhaseEvent) -> str:
    """The JSON line of ``event``. The five common fields are always there, ``trial``
    as ``null`` on a phase line. An extra field is there only when it has a value."""
    fields = event.model_dump(mode="json")
    for name in _EXTRAS:
        if fields[name] is None:
            del fields[name]
    return json.dumps(fields, ensure_ascii=False, separators=(",", ":"))


def _size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return None


def _read_end(path: Path) -> tuple[int, bool]:
    """The ``seq`` of the last valid line in ``path`` (0 when there is none), and whether
    the file ends with a newline. A file that a crash cut off mid-line does not."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return 0, True
    ended = not text or text.endswith("\n")
    for line in reversed(text.splitlines()):
        try:
            return PhaseEvent.parse_line(line).seq, ended
        except ValidationError:
            continue
    return 0, ended


__all__ = [
    "EVENTS_FILE",
    "INTERRUPTED_REASON",
    "REASON_MAX_LENGTH",
    "Phase",
    "PhaseEvent",
    "PhaseEventLog",
    "Status",
    "short_reason",
]
