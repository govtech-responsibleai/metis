"""logs/events.jsonl: the progress of a run, one JSON event per line.

The engine appends one ``RunEvent`` per line while ``simulate``, ``evaluate`` or ``run``
works on a run folder. A reader, such as a browser that shows the run, can follow the file
as it grows.

Each line has three common fields:

- ``seq`` numbers the lines of the file from 1, one more on each line. A resumed run
  appends to the same file and continues the count, so ``seq`` identifies one event in
  the file for good. A reader that has seen up to ``seq`` N reads on from N + 1.
- ``at`` is the UTC time at which the engine wrote the event.
- ``type`` names the event and selects its other fields.

A run writes ``run_started``, then ``phase_started`` for each phase it runs, then the
events of each trial, then ``run_ended``. The simulating phase writes ``trial_started``,
``turn``, ``trial_retry`` and ``trial_ended``. The evaluating phase writes
``trace_wait_started``, ``trace_wait_ended``, ``grade`` and ``trial_graded``. ``trial``
is the trial's folder name under ``outputs/trials/``, the one key that names a trial in
both phases.

An event holds IDs, counts, statuses and short reasons only. It never holds a key, a
prompt or a model reply. A reason is cut to ``REASON_MAX_LENGTH`` characters by
``short_reason``.

The published schema is ``schemas/run-event.schema.json``. Its version constant is
``_RUN_EVENT_VERSION``, which ``run_started`` records.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypeVar

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    ValidationError,
)

from metis.core.execution_layout import EVENTS_FILE, LOGS
from metis.core.logging import get_logger

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger(__name__)

_RUN_EVENT_VERSION = 1
REASON_MAX_LENGTH = 300

Phase = Literal["simulating", "evaluating"]
Reason = Annotated[str, Field(max_length=REASON_MAX_LENGTH)]


def short_reason(text: str | None) -> str | None:
    """``text`` on one line and cut to ``REASON_MAX_LENGTH`` characters, or ``None``."""
    if not text:
        return None
    flat = " ".join(text.split())
    if len(flat) <= REASON_MAX_LENGTH:
        return flat
    return flat[: REASON_MAX_LENGTH - 3] + "..."


def _require_common_fields(schema: dict[str, Any]) -> None:
    """Every line has ``type``, so the schema requires it, though the models default it."""
    required = schema.get("required", [])
    schema["required"] = ["type", *(name for name in required if name != "type")]


class _Event(BaseModel):
    model_config = ConfigDict(json_schema_extra=_require_common_fields)

    seq: int = Field(ge=1, description="Line number of the event in the file, from 1.")
    at: AwareDatetime = Field(
        description="UTC time at which the engine wrote the event."
    )


class _TrialEvent(_Event):
    trial: str = Field(description="The trial's folder name under outputs/trials/.")


class RunStarted(_Event):
    """A command started work on the run folder. A resumed run writes a new one."""

    type: Literal["run_started"] = "run_started"
    schema_version: Literal[1] = _RUN_EVENT_VERSION
    command: Literal["simulate", "evaluate", "run"]
    resumed: bool = False


class PhaseStarted(_Event):
    """A phase started. ``run`` writes one for simulating, then one for evaluating."""

    type: Literal["phase_started"] = "phase_started"
    phase: Phase
    total: int = Field(ge=0, description="Trials in the phase, done ones included.")
    done: int = Field(
        default=0, ge=0, description="Trials that an earlier run already finished."
    )
    trials: list[str] = Field(
        default_factory=list, description="Trials that this phase works on, in order."
    )


class TrialStarted(_TrialEvent):
    """A simulated trial started its first attempt."""

    type: Literal["trial_started"] = "trial_started"
    task_id: str
    persona_id: str
    trial_index: int = Field(ge=1)


class Turn(_TrialEvent):
    """A simulated turn finished: the user agent acted and the runner reported back."""

    type: Literal["turn"] = "turn"
    turn: int = Field(ge=1)
    max_turns: int = Field(ge=1)


class TrialRetry(_TrialEvent):
    """An attempt failed and the trial starts another one."""

    type: Literal["trial_retry"] = "trial_retry"
    attempt: int = Field(ge=1, description="The attempt that failed.")
    max_attempts: int = Field(ge=1)
    failure_type: str
    reason: Reason | None = None


class TrialEnded(_TrialEvent):
    """A simulated trial ended and its record.json was written."""

    type: Literal["trial_ended"] = "trial_ended"
    status: Literal["completed", "failed", "interrupted"]
    stop_reason: str
    turns: int = Field(ge=0)
    duration_seconds: float = Field(ge=0)
    failure_reason: Reason | None = None


class TraceWaitStarted(_TrialEvent):
    """The engine started to wait for the trial's traces in Langfuse."""

    type: Literal["trace_wait_started"] = "trace_wait_started"
    timeout_seconds: float = Field(ge=0)


class TraceWaitEnded(_TrialEvent):
    """The wait for the trial's traces ended."""

    type: Literal["trace_wait_ended"] = "trace_wait_ended"
    outcome: Literal["found", "not_found", "error"]
    traces: int = Field(default=0, ge=0)
    seconds: float = Field(ge=0)


class Grade(_TrialEvent):
    """One criterion's grader ran on the trial. The counts are of its results."""

    type: Literal["grade"] = "grade"
    criterion_id: str
    passed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)
    errored: int = Field(default=0, ge=0)


class TrialGraded(_TrialEvent):
    """The evaluating phase finished one trial."""

    type: Literal["trial_graded"] = "trial_graded"
    status: Literal["graded", "failed"]
    failure_reason: Reason | None = None


class RunEnded(_Event):
    """The command that wrote the last ``run_started`` stopped."""

    type: Literal["run_ended"] = "run_ended"
    status: Literal["completed", "failed", "interrupted"]
    reason: Reason | None = None


AnyRunEvent = Annotated[
    RunStarted
    | PhaseStarted
    | TrialStarted
    | Turn
    | TrialRetry
    | TrialEnded
    | TraceWaitStarted
    | TraceWaitEnded
    | Grade
    | TrialGraded
    | RunEnded,
    Field(discriminator="type"),
]


class RunEvent(RootModel[AnyRunEvent]):
    """One line of ``logs/events.jsonl``. Validate a line with ``RunEvent.parse_line``."""

    @classmethod
    def parse_line(cls, line: str) -> AnyRunEvent:
        """The event that one line of the file holds."""
        return cls.model_validate_json(line).root


E = TypeVar("E", bound=_Event)


class RunEventLog:
    """Appends events to one ``events.jsonl`` file and numbers them.

    Each event continues the ``seq`` of the last line in the file, so a resumed run, or
    the evaluating phase after the simulating one, numbers on from where the file ends.
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
    def for_run_folder(cls, root: Path) -> RunEventLog:
        """The log of the run folder ``root``, at ``logs/events.jsonl``."""
        return cls(root / LOGS / EVENTS_FILE)

    def emit(self, event_type: type[E], **fields: Any) -> E:
        """Write one event of ``event_type`` with the next ``seq``, and return it."""
        with self._lock:
            prefix = ""
            try:
                if self._size != _size(self.path):
                    self._seq, ended = _read_end(self.path)
                    prefix = "" if ended else "\n"
            except OSError as exc:
                self._file_failed(exc)
            event = event_type(seq=self._seq + 1, at=datetime.now(UTC), **fields)
            line = prefix + event.model_dump_json(exclude_none=True) + "\n"
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
                "[run_events] cannot write %s; progress events are dropped: %s: %s",
                self.path,
                type(exc).__name__,
                exc,
            )


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
            return RunEvent.parse_line(line).seq, ended
        except ValidationError:
            continue
    return 0, ended


__all__ = [
    "EVENTS_FILE",
    "REASON_MAX_LENGTH",
    "AnyRunEvent",
    "Grade",
    "Phase",
    "PhaseStarted",
    "RunEnded",
    "RunEvent",
    "RunEventLog",
    "RunStarted",
    "TraceWaitEnded",
    "TraceWaitStarted",
    "TrialEnded",
    "TrialGraded",
    "TrialRetry",
    "TrialStarted",
    "Turn",
    "short_reason",
]
