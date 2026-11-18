"""The life of a run: its status, a stop, a failure on its thread, its text, and shutdown."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import structlog

from metis.api.engine_runs import CONSOLE_FILE, read_events
from metis.core import execution_layout
from metis.core.phase_events import PhaseEventLog
from metis.engine import run as engine_run
from tests.fixtures.api.engine import wait_until, write_input_dir
from tests.unit.engine.test_cli_simulate import _with_factory

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from fastapi.testclient import TestClient

    from tests.fixtures.api.engine import FakeEngine

FAILING_FACTORY = "tests.unit.engine.test_cli_simulate._FailingSpecFactory"


@pytest.fixture
def experiment_dir(make_experiment_dir: Callable[..., Path]) -> Path:
    return make_experiment_dir()


def _resume(client: TestClient, experiment_id: str) -> int:
    return client.post(f"/api/v1/engine/simulate/{experiment_id}/resume").status_code


def _status(client: TestClient, experiment_id: str) -> dict[str, object]:
    response = client.get(f"/api/v1/engine/{experiment_id}")
    assert response.status_code == 200
    return response.json()


def _statuses(experiment_dir: Path) -> list[tuple[str, str]]:
    return [
        (event.phase, event.status)
        for event, _ in read_events(experiment_dir)
        if event.trial is None
    ]


def _not_running(client: TestClient, experiment_id: str) -> bool:
    return _status(client, experiment_id)["status"] not in ("running", "stopping")


# --- status --------------------------------------------------------------------------


def test_a_run_is_running_with_no_counts_before_its_started_line(
    engine_client: TestClient, fake_engine: FakeEngine, experiment_dir: Path
) -> None:
    PhaseEventLog.for_experiment_dir(experiment_dir).emit(
        "simulating", "started", total=9, done=1
    )
    fake_engine.begin.clear()

    assert _resume(engine_client, experiment_dir.name) == 202

    assert _status(engine_client, experiment_dir.name) == {
        "experiment_id": experiment_dir.name,
        "phase": "simulating",
        "status": "running",
        "total": None,
        "done": None,
        "reason": None,
        "last_seq": 1,
    }


def test_a_run_shows_the_counts_of_its_own_started_line(
    engine_client: TestClient, fake_engine: FakeEngine, experiment_dir: Path
) -> None:
    fake_engine.mode = "hold"
    _resume(engine_client, experiment_dir.name)
    wait_until(lambda: _statuses(experiment_dir) == [("simulating", "started")])

    status = _status(engine_client, experiment_dir.name)

    assert (status["status"], status["total"], status["done"]) == ("running", 2, 0)
    assert status["last_seq"] == 1


def test_a_stop_gives_stopping_while_the_run_ends(
    engine_client: TestClient, fake_engine: FakeEngine, experiment_dir: Path
) -> None:
    fake_engine.mode = "stubborn"
    _resume(engine_client, experiment_dir.name)
    wait_until(lambda: len(_statuses(experiment_dir)) == 1)

    response = engine_client.post(f"/api/v1/engine/{experiment_dir.name}/stop")

    assert response.status_code == 202
    assert response.json() == {"experiment_id": experiment_dir.name}
    assert _status(engine_client, experiment_dir.name)["status"] == "stopping"


def test_a_stop_ends_the_run_with_interrupted(
    engine_client: TestClient, fake_engine: FakeEngine, experiment_dir: Path
) -> None:
    fake_engine.mode = "hold"
    _resume(engine_client, experiment_dir.name)
    wait_until(lambda: len(_statuses(experiment_dir)) == 1)

    engine_client.post(f"/api/v1/engine/{experiment_dir.name}/stop")

    wait_until(lambda: _not_running(engine_client, experiment_dir.name))
    status = _status(engine_client, experiment_dir.name)
    assert (status["phase"], status["status"]) == ("simulating", "interrupted")
    assert status["reason"] is None


def test_a_run_that_ends_is_completed(
    engine_client: TestClient, experiment_dir: Path
) -> None:
    engine_client.post(f"/api/v1/engine/evaluate/{experiment_dir.name}")

    wait_until(lambda: _not_running(engine_client, experiment_dir.name))
    status = _status(engine_client, experiment_dir.name)
    assert (status["phase"], status["status"]) == ("evaluating", "completed")
    assert (status["total"], status["done"], status["last_seq"]) == (2, 0, 2)


def test_a_stop_with_no_run_is_no_run(
    engine_client: TestClient, experiment_dir: Path
) -> None:
    response = engine_client.post(f"/api/v1/engine/{experiment_dir.name}/stop")

    assert response.status_code == 409
    assert response.json()["code"] == "no_run"


def test_a_stop_of_an_experiment_that_is_not_the_run_is_no_run(
    engine_client: TestClient,
    fake_engine: FakeEngine,
    make_experiment_dir: Callable[..., Path],
) -> None:
    running = make_experiment_dir("test-exp-20260101-000001")
    other = make_experiment_dir("test-exp-20260101-000002")
    fake_engine.mode = "hold"
    _resume(engine_client, running.name)

    response = engine_client.post(f"/api/v1/engine/{other.name}/stop")

    assert response.status_code == 409
    assert response.json()["code"] == "no_run"
    assert _status(engine_client, running.name)["status"] == "running"


def test_a_stop_of_an_unknown_experiment_is_not_found(
    engine_client: TestClient,
) -> None:
    response = engine_client.post("/api/v1/engine/no-such-experiment/stop")

    assert response.status_code == 404
    assert response.json()["code"] == "experiment_not_found"


def test_a_folder_with_no_events_is_not_started(
    engine_client: TestClient, experiment_dir: Path
) -> None:
    assert _status(engine_client, experiment_dir.name) == {
        "experiment_id": experiment_dir.name,
        "phase": None,
        "status": "not_started",
        "total": None,
        "done": None,
        "reason": None,
        "last_seq": 0,
    }


def test_a_log_that_ends_with_started_and_no_run_is_unfinished(
    engine_client: TestClient, experiment_dir: Path
) -> None:
    events = PhaseEventLog.for_experiment_dir(experiment_dir)
    events.emit("simulating", "started", total=3, done=0)
    events.emit("simulating", "completed")
    events.emit("evaluating", "started", total=3, done=1)

    status = _status(engine_client, experiment_dir.name)

    assert (status["phase"], status["status"]) == ("evaluating", "unfinished")
    assert (status["total"], status["done"], status["last_seq"]) == (3, 1, 3)


def test_a_failed_line_gives_its_reason(
    engine_client: TestClient, experiment_dir: Path
) -> None:
    events = PhaseEventLog.for_experiment_dir(experiment_dir)
    events.emit("simulating", "started", total=3, done=0)
    events.emit("simulating", "failed", reason="No trial records found.")

    status = _status(engine_client, experiment_dir.name)

    assert (status["status"], status["reason"]) == ("failed", "No trial records found.")


def test_the_status_of_an_unknown_experiment_is_not_found(
    engine_client: TestClient,
) -> None:
    response = engine_client.get("/api/v1/engine/no-such-experiment")

    assert response.status_code == 404
    assert response.json()["code"] == "experiment_not_found"


# --- runs on their thread --------------------------------------------------------------


def test_a_run_that_fails_on_its_thread_ends_with_failed_and_frees_the_engine(
    make_engine_client: Callable[..., TestClient],
    project_dir: Path,
) -> None:
    client = make_engine_client(simulate=engine_run.simulate)
    write_input_dir(project_dir / "failing", _with_factory(FAILING_FACTORY))

    response = client.post("/api/v1/engine/simulate", json={"input_dir": "failing"})

    assert response.status_code == 202
    experiment_id = response.json()["experiment_id"]
    wait_until(lambda: _not_running(client, experiment_id))
    status = _status(client, experiment_id)
    assert (status["phase"], status["status"]) == ("simulating", "failed")
    assert status["reason"] == "targets/app.yaml: target binding file not found"
    assert _resume(client, experiment_id) == 202


def test_an_unexpected_error_on_the_thread_is_logged_and_frees_the_engine(
    engine_client: TestClient,
    fake_engine: FakeEngine,
    make_experiment_dir: Callable[..., Path],
) -> None:
    first = make_experiment_dir("test-exp-20260101-000001")
    second = make_experiment_dir("test-exp-20260101-000002")
    fake_engine.mode = "crash"

    with structlog.testing.capture_logs() as logs:
        _resume(engine_client, first.name)
        wait_until(lambda: _not_running(engine_client, first.name))

    assert _status(engine_client, first.name)["status"] == "failed"
    [failure] = [log for log in logs if log["event"] == "engine_run_failed"]
    assert failure["experiment_id"] == first.name
    fake_engine.mode = "complete"
    assert _resume(engine_client, second.name) == 202


def test_a_run_error_is_not_logged_as_unexpected(
    engine_client: TestClient, fake_engine: FakeEngine, experiment_dir: Path
) -> None:
    fake_engine.mode = "fail"

    with structlog.testing.capture_logs() as logs:
        _resume(engine_client, experiment_dir.name)
        wait_until(lambda: _not_running(engine_client, experiment_dir.name))

    assert _status(engine_client, experiment_dir.name)["reason"] == "boom"
    assert [log for log in logs if log["event"] == "engine_run_failed"] == []


def test_engine_text_goes_to_the_console_file_and_not_to_stdout(
    engine_client: TestClient,
    experiment_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _resume(engine_client, experiment_dir.name)
    wait_until(lambda: _not_running(engine_client, experiment_dir.name))

    wait_until(
        lambda: _status(engine_client, experiment_dir.name)["phase"] == "evaluating"
    )
    wait_until(lambda: _not_running(engine_client, experiment_dir.name))

    # One console file for the whole job: the simulate, then the evaluate after it.
    console_file = experiment_dir / execution_layout.LOGS / CONSOLE_FILE
    expected = [
        f"fake resume_simulation of {experiment_dir.name}",
        f"fake resume_evaluation of {experiment_dir.name}",
    ]
    assert console_file.read_text(encoding="utf-8").splitlines() == expected
    out = capsys.readouterr().out
    assert not any(line in out for line in expected)


# --- shutdown --------------------------------------------------------------------------


def test_shutdown_stops_the_run_and_waits_for_it(
    make_engine_client: Callable[..., TestClient],
    fake_engine: FakeEngine,
    experiment_dir: Path,
) -> None:
    client = make_engine_client()
    fake_engine.mode = "slow_stop"
    _resume(client, experiment_dir.name)
    wait_until(lambda: len(_statuses(experiment_dir)) == 1)

    client.__exit__(None, None, None)

    assert _statuses(experiment_dir) == [
        ("simulating", "started"),
        ("simulating", "interrupted"),
    ]


def test_shutdown_gives_up_after_the_stop_time_limit(
    make_engine_client: Callable[..., TestClient],
    fake_engine: FakeEngine,
    experiment_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("METIS_API_STOP_TIMEOUT", "1")
    client = make_engine_client()
    fake_engine.mode = "stubborn"
    _resume(client, experiment_dir.name)
    wait_until(lambda: len(_statuses(experiment_dir)) == 1)

    with structlog.testing.capture_logs() as logs:
        client.__exit__(None, None, None)

    [warning] = [log for log in logs if log["event"] == "engine_run_did_not_stop"]
    assert warning["experiment_id"] == experiment_dir.name
    assert _statuses(experiment_dir) == [("simulating", "started")]
