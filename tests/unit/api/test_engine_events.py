"""`GET /api/v1/engine/{id}/events`: the lines of logs/events.jsonl after a seq."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from metis.core import execution_layout
from metis.core.phase_events import EVENTS_FILE, PhaseEvent, PhaseEventLog

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from fastapi.testclient import TestClient


@pytest.fixture
def experiment_dir(make_experiment_dir: Callable[..., Path]) -> Path:
    return make_experiment_dir()


def _events_file(experiment_dir: Path) -> Path:
    return experiment_dir / execution_layout.LOGS / EVENTS_FILE


def _write_three(experiment_dir: Path) -> list[str]:
    events = PhaseEventLog.for_experiment_dir(experiment_dir)
    events.emit("simulating", "started", total=1, done=0)
    events.emit("simulating", "started", trial="TC-001-alice-1", attempt=1)
    events.emit("simulating", "completed")
    return _events_file(experiment_dir).read_text(encoding="utf-8").splitlines()


def _get(
    client: TestClient, experiment_id: str, **params: object
) -> list[dict[str, object]]:
    response = client.get(f"/api/v1/engine/{experiment_id}/events", params=params)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    return response.json()


def test_the_events_after_a_seq_are_the_lines_as_the_engine_wrote_them(
    engine_client: TestClient, experiment_dir: Path
) -> None:
    lines = _write_three(experiment_dir)

    events = _get(engine_client, experiment_dir.name, after=1)

    assert events == [json.loads(line) for line in lines[1:]]
    assert [e["seq"] for e in events] == [2, 3]
    assert "reason" not in events[1]
    for event in events:
        PhaseEvent.model_validate(event)


def test_with_no_after_every_event_is_returned(
    engine_client: TestClient, experiment_dir: Path
) -> None:
    _write_three(experiment_dir)

    assert [e["seq"] for e in _get(engine_client, experiment_dir.name)] == [1, 2, 3]


def test_a_last_line_with_no_newline_is_skipped_even_when_it_parses(
    engine_client: TestClient, experiment_dir: Path
) -> None:
    lines = _write_three(experiment_dir)
    whole = lines[-1].replace('"seq":3', '"seq":4')
    PhaseEvent.parse_line(whole)
    with _events_file(experiment_dir).open("a", encoding="utf-8") as handle:
        handle.write(whole)

    assert [e["seq"] for e in _get(engine_client, experiment_dir.name)] == [1, 2, 3]


def test_a_line_that_does_not_parse_in_the_middle_is_skipped(
    engine_client: TestClient, experiment_dir: Path
) -> None:
    path = _events_file(experiment_dir)
    path.parent.mkdir(parents=True)
    events = PhaseEventLog(path)
    events.emit("simulating", "started", total=1, done=0)
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"seq":2,"at":"2026-11-16T00:00:\n')
    events.emit("simulating", "completed")

    assert [e["seq"] for e in _get(engine_client, experiment_dir.name)] == [1, 2]
    assert path.read_text(encoding="utf-8").count("\n") == 3


def test_a_known_experiment_with_no_events_file_has_no_events(
    engine_client: TestClient, experiment_dir: Path
) -> None:
    assert _get(engine_client, experiment_dir.name, after=5) == []


def test_the_events_of_an_unknown_experiment_are_not_found(
    engine_client: TestClient,
) -> None:
    response = engine_client.get("/api/v1/engine/no-such-experiment/events")

    assert response.status_code == 404
    assert response.json()["code"] == "experiment_not_found"


def test_an_after_below_zero_is_a_validation_error(
    engine_client: TestClient, experiment_dir: Path
) -> None:
    response = engine_client.get(
        f"/api/v1/engine/{experiment_dir.name}/events", params={"after": -1}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
