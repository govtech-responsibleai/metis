"""The job of each start: the steps that one thread runs, and the evaluate after a simulate."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

import pytest

from metis.core import execution_layout, project_layout
from metis.core.phase_events import PhaseEventLog
from metis.engine import run as engine_run
from metis.engine.run._common import clear_evaluation_outputs
from tests.fixtures.api.engine import wait_until
from tests.unit.engine.test_cli_simulate import _write_record

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from fastapi.testclient import TestClient
    from rich.console import Console

    from tests.fixtures.api.engine import FakeEngine

SIMULATE = "/api/v1/engine/simulate"


def _relative(project_dir: Path, folder: Path) -> str:
    return folder.relative_to(project_dir).as_posix()


def _experiments(project_dir: Path) -> list[str]:
    folder = project_dir / project_layout.EXPERIMENTS
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def _status(client: TestClient, experiment_id: str) -> dict[str, Any]:
    return client.get(f"/api/v1/engine/{experiment_id}").json()


def _ended(client: TestClient, experiment_id: str) -> bool:
    return _status(client, experiment_id)["status"] not in ("running", "stopping")


def _write_results(experiment_dir: Path) -> Path:
    results = experiment_dir / execution_layout.RESULTS
    results.parent.mkdir(parents=True, exist_ok=True)
    results.write_text('{"run_id": "r1"}')
    return results


def _names(fake_engine: FakeEngine) -> list[str]:
    return [call.name for call in fake_engine.calls]


@pytest.fixture
def experiment_dir(make_experiment_dir: Callable[..., Path]) -> Path:
    return make_experiment_dir()


def test_a_simulate_start_evaluates_on_the_same_job(
    engine_client: TestClient,
    fake_engine: FakeEngine,
    project_dir: Path,
    input_dir: Path,
) -> None:
    response = engine_client.post(
        SIMULATE,
        json={"input_dir": _relative(project_dir, input_dir), "concurrency": 3},
    )
    experiment_id = response.json()["experiment_id"]

    wait_until(
        lambda: len(fake_engine.calls) == 2 and _ended(engine_client, experiment_id)
    )

    assert _names(fake_engine) == ["simulate", "resume_evaluation"]
    simulate, evaluate = fake_engine.calls
    assert simulate.options == {"concurrency": 3}
    # The simulate request has no evaluate settings, so the evaluate takes the defaults.
    assert evaluate.options["concurrency"] == 1
    assert evaluate.options["trace_wait"].timeout_seconds == 180
    assert evaluate.options["command"] == "run"
    assert evaluate.experiment_dir == simulate.experiment_dir
    status = _status(engine_client, experiment_id)
    assert (status["phase"], status["status"]) == ("evaluating", "completed")


def test_a_resume_of_a_simulation_evaluates_on_the_same_job(
    engine_client: TestClient, fake_engine: FakeEngine, experiment_dir: Path
) -> None:
    engine_client.post(f"{SIMULATE}/{experiment_dir.name}/resume")

    wait_until(
        lambda: (
            len(fake_engine.calls) == 2 and _ended(engine_client, experiment_dir.name)
        )
    )

    assert _names(fake_engine) == ["resume_simulation", "resume_evaluation"]
    assert fake_engine.calls[1].options["command"] == "run"


@pytest.mark.parametrize("mode", ["fail", "crash", "stop"])
def test_a_simulate_that_stops_or_fails_runs_no_evaluate(
    engine_client: TestClient,
    fake_engine: FakeEngine,
    experiment_dir: Path,
    mode: str,
) -> None:
    fake_engine.mode = "hold" if mode == "stop" else mode
    engine_client.post(f"{SIMULATE}/{experiment_dir.name}/resume")
    wait_until(lambda: len(fake_engine.calls) == 1)
    if mode == "stop":
        wait_until(lambda: _status(engine_client, experiment_dir.name)["total"] == 2)
        engine_client.post(f"/api/v1/engine/{experiment_dir.name}/stop")

    wait_until(lambda: _ended(engine_client, experiment_dir.name))

    assert _names(fake_engine) == ["resume_simulation"]


def test_a_stop_while_the_evaluate_runs_ends_the_job(
    engine_client: TestClient, fake_engine: FakeEngine, experiment_dir: Path
) -> None:
    held = threading.Event()

    def evaluate(experiment_dir: Path, *, stop: threading.Event, **_: Any) -> None:
        events = PhaseEventLog.for_experiment_dir(experiment_dir)
        events.emit("evaluating", "started", total=2, done=0)
        held.set()
        stop.wait(5)
        events.emit("evaluating", "interrupted", reason="stopped")
        raise engine_run.RunStopped("stopped")

    client = engine_client
    client.app.state.engine_runs.functions = fake_engine.functions(
        resume_evaluation=evaluate
    )
    client.post(f"{SIMULATE}/{experiment_dir.name}/resume")
    assert held.wait(5)

    assert client.post(f"/api/v1/engine/{experiment_dir.name}/stop").status_code == 202
    wait_until(lambda: _ended(client, experiment_dir.name))

    status = _status(client, experiment_dir.name)
    assert (status["phase"], status["status"]) == ("evaluating", "interrupted")


def test_the_evaluate_after_a_simulate_needs_no_regrade(
    make_engine_client: Callable[..., TestClient],
    fake_engine: FakeEngine,
    experiment_dir: Path,
) -> None:
    # A complete evaluation, then a resume that runs a trial again: the real
    # resume_simulation deletes the evaluation outputs before it runs the trial.
    _write_results(experiment_dir)
    resume = fake_engine.functions().resume_simulation

    def resume_simulation(experiment_dir: Path, **options: Any) -> None:
        clear_evaluation_outputs(experiment_dir)
        resume(experiment_dir, **options)

    client = make_engine_client(
        resume_simulation=resume_simulation,
        resume_evaluation=engine_run.resume_evaluation,
    )
    _write_record(experiment_dir, "TC-001-alice-1")

    response = client.post(f"{SIMULATE}/{experiment_dir.name}/resume")

    assert response.status_code == 202
    wait_until(lambda: _ended(client, experiment_dir.name))
    status = _status(client, experiment_dir.name)
    # The real evaluate graded the trial again and wrote a new results.json.
    assert (status["phase"], status["status"], status["reason"]) == (
        "evaluating",
        "completed",
        None,
    )
    results = experiment_dir / execution_layout.RESULTS
    assert results.read_text() != '{"run_id": "r1"}'
    assert engine_run.evaluation_is_complete(experiment_dir)


def test_the_evaluate_after_a_resume_that_ran_no_trial_keeps_a_complete_evaluation(
    make_engine_client: Callable[..., TestClient],
    fake_engine: FakeEngine,
    experiment_dir: Path,
) -> None:
    _write_record(experiment_dir, "TC-001-alice-1")
    results = _write_results(experiment_dir)
    before = results.read_bytes()

    def nothing_to_redo(experiment_dir: Path, *, console: Console, **_: Any) -> None:
        events = PhaseEventLog.for_experiment_dir(experiment_dir)
        events.emit("simulating", "started", total=1, done=1)
        events.emit("simulating", "completed")

    client = make_engine_client(
        resume_simulation=nothing_to_redo,
        resume_evaluation=engine_run.resume_evaluation,
    )

    response = client.post(f"{SIMULATE}/{experiment_dir.name}/resume")

    assert response.status_code == 202
    wait_until(
        lambda: (
            _status(client, experiment_dir.name)["phase"] == "evaluating"
            and _ended(client, experiment_dir.name)
        )
    )
    assert results.read_bytes() == before
    assert _status(client, experiment_dir.name)["status"] == "completed"


def test_a_queued_job_that_stops_can_resume(
    make_engine_client: Callable[..., TestClient],
    fake_engine: FakeEngine,
    make_experiment_dir: Callable[..., Path],
) -> None:
    client = make_engine_client(max_runs=1)
    running = make_experiment_dir("test-exp-20260101-000001")
    queued = make_experiment_dir("test-exp-20260101-000002")
    fake_engine.mode = "hold"
    client.post(f"{SIMULATE}/{running.name}/resume")
    client.post(f"{SIMULATE}/{queued.name}/resume")

    assert client.post(f"/api/v1/engine/{queued.name}/stop").status_code == 202
    assert _status(client, queued.name)["status"] == "not_started"
    assert client.post(f"{SIMULATE}/{queued.name}/resume").status_code == 202


def test_a_bad_quiet_window_fails_a_simulate_start(
    engine_client: TestClient,
    fake_engine: FakeEngine,
    project_dir: Path,
    input_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGFUSE_METIS_QUIET_SECONDS", "abc")

    response = engine_client.post(
        SIMULATE, json={"input_dir": _relative(project_dir, input_dir)}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_langfuse_timeout"
    assert _experiments(project_dir) == []
    assert fake_engine.calls == []


def test_a_bad_quiet_window_fails_a_resume_of_a_simulation_after_the_folder_check(
    engine_client: TestClient,
    fake_engine: FakeEngine,
    experiment_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGFUSE_METIS_QUIET_SECONDS", "abc")

    missing = engine_client.post(f"{SIMULATE}/no-such-experiment/resume")
    response = engine_client.post(f"{SIMULATE}/{experiment_dir.name}/resume")

    assert missing.json()["code"] == "experiment_not_found"
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_langfuse_timeout"
    assert fake_engine.calls == []
