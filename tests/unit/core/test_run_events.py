"""The run event log: one numbered RunEvent per line of logs/events.jsonl."""

from __future__ import annotations

import json
import threading
from typing import TYPE_CHECKING

import jsonschema
import pytest
import structlog
from pydantic import ValidationError

from metis.core.run_events import (
    REASON_MAX_LENGTH,
    RunEnded,
    RunEvent,
    RunEventLog,
    RunStarted,
    Turn,
    short_reason,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def schema(repo_root: Path) -> dict:
    path = repo_root / "packages/core/schemas/run-event.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_events_are_numbered_from_one_and_parse_back(tmp_path: Path) -> None:
    log = RunEventLog.for_run_folder(tmp_path)
    log.emit(RunStarted, command="simulate")
    log.emit(Turn, trial="TC-001-alice-1", turn=1, max_turns=5)

    path = tmp_path / "logs" / "events.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert [RunEvent.parse_line(line).seq for line in lines] == [1, 2]
    turn = RunEvent.parse_line(lines[1])
    assert isinstance(turn, Turn)
    assert turn.at.tzinfo is not None


def test_a_new_log_on_the_same_file_continues_the_sequence(tmp_path: Path) -> None:
    RunEventLog.for_run_folder(tmp_path).emit(RunStarted, command="simulate")
    first = RunEventLog.for_run_folder(tmp_path)
    second = RunEventLog.for_run_folder(tmp_path)

    first.emit(RunEnded, status="interrupted")
    second.emit(RunStarted, command="simulate", resumed=True)
    first.emit(RunEnded, status="completed")

    seqs = [line["seq"] for line in _lines(tmp_path / "logs" / "events.jsonl")]
    assert seqs == [1, 2, 3, 4]


def test_a_line_cut_off_by_a_crash_is_closed_and_skipped(tmp_path: Path) -> None:
    log = RunEventLog.for_run_folder(tmp_path)
    log.emit(RunStarted, command="run")
    with log.path.open("a", encoding="utf-8") as handle:
        handle.write('{"seq": 2, "type": "tu')

    RunEventLog.for_run_folder(tmp_path).emit(RunStarted, command="run", resumed=True)

    lines = log.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert RunEvent.parse_line(lines[2]).seq == 2


def test_threads_that_share_a_log_write_whole_numbered_lines(tmp_path: Path) -> None:
    log = RunEventLog.for_run_folder(tmp_path)

    def write_turns(trial: str) -> None:
        for turn in range(1, 51):
            log.emit(Turn, trial=trial, turn=turn, max_turns=50)

    threads = [
        threading.Thread(target=write_turns, args=(f"trial-{i}",)) for i in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    lines = log.path.read_text(encoding="utf-8").splitlines()
    assert [RunEvent.parse_line(line).seq for line in lines] == list(range(1, 401))


def test_a_file_that_cannot_be_written_drops_events_and_warns_once(
    tmp_path: Path,
) -> None:
    (tmp_path / "logs").write_text("a file where the logs folder should be")
    log = RunEventLog.for_run_folder(tmp_path)

    with structlog.testing.capture_logs() as logs:
        first = log.emit(RunStarted, command="run")
        log.emit(Turn, trial="TC-001-alice-1", turn=1, max_turns=5)

    assert first.seq == 1
    assert [entry["log_level"] for entry in logs] == ["warning"]

    (tmp_path / "logs").unlink()
    log.emit(RunEnded, status="completed")

    assert [line["seq"] for line in _lines(log.path)] == [1]


def test_short_reason_keeps_one_short_line() -> None:
    reason = short_reason("Timeout\n  waiting " + "x" * 1000)
    assert reason is not None
    assert "\n" not in reason
    assert len(reason) == REASON_MAX_LENGTH
    assert reason.endswith("...")
    assert short_reason("") is None


def test_an_unknown_event_type_is_rejected(schema: dict) -> None:
    line = {"seq": 1, "at": "2026-01-01T00:00:00Z", "type": "secret_dump"}
    with pytest.raises(ValidationError):
        RunEvent.parse_line(json.dumps(line))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=line, schema=schema)


def test_published_schema_requires_the_common_fields(schema: dict) -> None:
    assert schema["title"] == "RunEvent v1"
    assert schema["discriminator"]["propertyName"] == "type"
    for definition in schema["$defs"].values():
        if "seq" in definition.get("properties", {}):
            assert {"type", "seq", "at"} <= set(definition["required"])
