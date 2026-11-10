"""The phase event log: one numbered PhaseEvent per line of logs/events.jsonl."""

from __future__ import annotations

import json
import threading
from typing import TYPE_CHECKING

import jsonschema
import pytest
import structlog
from pydantic import ValidationError

from metis.core.phase_events import (
    REASON_MAX_LENGTH,
    PhaseEvent,
    PhaseEventLog,
    short_reason,
)

if TYPE_CHECKING:
    from pathlib import Path

TRIAL = "TC-001-alice-1"


@pytest.fixture
def schema(repo_root: Path) -> dict:
    path = repo_root / "packages/core/schemas/phase-event.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _line(**fields: object) -> dict:
    return {"seq": 1, "at": "2026-01-01T00:00:00Z", "trial": None, **fields}


def test_events_are_numbered_from_one_and_parse_back(tmp_path: Path) -> None:
    log = PhaseEventLog.for_experiment_dir(tmp_path)
    log.emit("simulating", "started", total=1, done=0)
    log.emit("simulating", "running", trial=TRIAL, attempt=1, turn=1)

    lines = log.path.read_text(encoding="utf-8").splitlines()
    assert [PhaseEvent.parse_line(line).seq for line in lines] == [1, 2]
    turn = PhaseEvent.parse_line(lines[1])
    assert (turn.phase, turn.trial, turn.status, turn.turn) == (
        "simulating",
        TRIAL,
        "running",
        1,
    )
    assert turn.at.tzinfo is not None


def test_every_line_has_the_common_fields_first(tmp_path: Path) -> None:
    log = PhaseEventLog.for_experiment_dir(tmp_path)
    log.emit("simulating", "started", total=1, done=0)
    log.emit("simulating", "running", trial=TRIAL, attempt=1, turn=1)

    for line in _lines(log.path):
        assert list(line)[:5] == ["seq", "at", "phase", "trial", "status"]
    phase_line, trial_line = _lines(log.path)
    assert phase_line == {**phase_line, "trial": None, "total": 1, "done": 0}
    assert list(trial_line)[5:] == ["attempt", "turn"]


def test_a_new_log_on_the_same_file_continues_the_sequence(tmp_path: Path) -> None:
    PhaseEventLog.for_experiment_dir(tmp_path).emit(
        "simulating", "started", total=1, done=0
    )
    first = PhaseEventLog.for_experiment_dir(tmp_path)
    second = PhaseEventLog.for_experiment_dir(tmp_path)

    first.emit("simulating", "interrupted")
    second.emit("simulating", "started", total=1, done=0)
    first.emit("simulating", "completed")

    seqs = [line["seq"] for line in _lines(tmp_path / "logs" / "events.jsonl")]
    assert seqs == [1, 2, 3, 4]


def test_a_line_cut_off_by_a_crash_is_closed_and_skipped(tmp_path: Path) -> None:
    log = PhaseEventLog.for_experiment_dir(tmp_path)
    log.emit("simulating", "started", total=1, done=0)
    with log.path.open("a", encoding="utf-8") as handle:
        handle.write('{"seq": 2, "at": "20')

    PhaseEventLog.for_experiment_dir(tmp_path).emit(
        "simulating", "started", total=1, done=0
    )

    lines = log.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert PhaseEvent.parse_line(lines[2]).seq == 2


def test_threads_that_share_a_log_write_whole_numbered_lines(tmp_path: Path) -> None:
    log = PhaseEventLog.for_experiment_dir(tmp_path)

    def write_turns(trial: str) -> None:
        for turn in range(1, 51):
            log.emit("simulating", "running", trial=trial, attempt=1, turn=turn)

    threads = [
        threading.Thread(target=write_turns, args=(f"trial-{i}",)) for i in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    lines = log.path.read_text(encoding="utf-8").splitlines()
    assert [PhaseEvent.parse_line(line).seq for line in lines] == list(range(1, 401))


def test_a_file_that_cannot_be_written_drops_events_and_warns_once(
    tmp_path: Path,
) -> None:
    (tmp_path / "logs").write_text("a file where the logs folder should be")
    log = PhaseEventLog.for_experiment_dir(tmp_path)

    with structlog.testing.capture_logs() as logs:
        first = log.emit("simulating", "started", total=1, done=0)
        log.emit("simulating", "running", trial=TRIAL, attempt=1, turn=1)

    assert first.seq == 1
    assert [entry["log_level"] for entry in logs] == ["warning"]

    (tmp_path / "logs").unlink()
    log.emit("simulating", "completed")

    assert [line["seq"] for line in _lines(log.path)] == [1]


def test_emit_cuts_a_long_reason_to_one_short_line(tmp_path: Path) -> None:
    log = PhaseEventLog.for_experiment_dir(tmp_path)

    event = log.emit("simulating", "failed", reason="Timeout\n  waiting " + "x" * 1000)

    assert event.reason is not None
    assert "\n" not in event.reason
    assert len(event.reason) == REASON_MAX_LENGTH
    assert event.reason.endswith("...")
    assert short_reason("") is None


@pytest.mark.parametrize(
    ("line", "message"),
    [
        (_line(phase="simulating", status="running", trial=TRIAL, attempt=1), "turn"),
        (_line(phase="evaluating", status="running", trial=TRIAL), "running"),
        (_line(phase="simulating", status="started", trial=TRIAL), "attempt"),
        (_line(phase="evaluating", status="completed", turn=1), "turn"),
        (_line(phase="simulating", status="running", attempt=1, turn=1), "running"),
        (
            _line(phase="simulating", status="skipped", trial=TRIAL, attempt=1),
            "skipped",
        ),
        (_line(phase="simulating", status="started"), "total"),
    ],
    ids=[
        "running-without-turn",
        "running-in-evaluation",
        "simulating-trial-without-attempt",
        "phase-line-with-turn",
        "running-phase-line",
        "skipped-trial",
        "phase-started-without-total",
    ],
)
def test_a_line_that_does_not_fit_its_status_is_rejected(
    line: dict, message: str, schema: dict
) -> None:
    with pytest.raises(ValidationError, match=message):
        PhaseEvent.parse_line(json.dumps(line))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=line, schema=schema)


def test_an_unknown_status_is_rejected(schema: dict) -> None:
    line = _line(phase="simulating", status="secret_dump")
    with pytest.raises(ValidationError):
        PhaseEvent.parse_line(json.dumps(line))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=line, schema=schema)


def test_published_schema_requires_the_common_fields(schema: dict) -> None:
    assert schema["title"] == "PhaseEvent v1"
    assert {"seq", "at", "phase", "trial", "status"} <= set(schema["required"])
