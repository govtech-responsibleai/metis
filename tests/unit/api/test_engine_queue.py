"""Up to N runs at once, and a first-in-first-out queue for the starts beyond N."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import pytest
import structlog

from metis.api import engine_runs
from metis.api.errors import RouteError
from metis.core import execution_layout
from metis.core.phase_events import EVENTS_FILE, PhaseEventLog
from tests.fixtures.api.engine import wait_until

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from fastapi.testclient import TestClient
    from rich.console import Console

    from tests.fixtures.api.engine import FakeEngine


def _resume(client: TestClient, experiment_id: str) -> int:
    return client.post(f"/api/v1/engine/simulate/{experiment_id}/resume").status_code


def _stop(client: TestClient, experiment_id: str) -> int:
    return client.post(f"/api/v1/engine/{experiment_id}/stop").status_code


def _called(fake_engine: FakeEngine) -> list[str]:
    return [call.experiment_dir.name for call in fake_engine.calls]


@pytest.fixture
def folders(make_experiment_dir: Callable[..., Path]) -> list[Path]:
    return [make_experiment_dir(f"test-exp-20260101-00000{n}") for n in range(4)]


def test_a_start_beyond_the_limit_is_accepted_and_queued(
    make_engine_client: Callable[..., TestClient],
    fake_engine: FakeEngine,
    folders: list[Path],
) -> None:
    client = make_engine_client(max_runs=2)
    fake_engine.mode = "hold"

    codes = [_resume(client, folder.name) for folder in folders[:3]]

    assert codes == [202, 202, 202]
    wait_until(lambda: len(fake_engine.calls) == 2)
    time.sleep(0.1)
    assert sorted(_called(fake_engine)) == [folders[0].name, folders[1].name]


def test_the_queue_is_first_in_first_out(
    make_engine_client: Callable[..., TestClient],
    fake_engine: FakeEngine,
    folders: list[Path],
) -> None:
    client = make_engine_client(max_runs=1)
    fake_engine.mode = "hold"
    for folder in folders:
        assert _resume(client, folder.name) == 202

    for count, folder in enumerate(folders[:-1], start=1):
        wait_until(lambda count=count: len(fake_engine.calls) == count)
        assert _stop(client, folder.name) == 202

    wait_until(lambda: len(fake_engine.calls) == 4)
    assert _called(fake_engine) == [folder.name for folder in folders]


def test_a_stop_of_a_queued_run_takes_it_out_of_the_queue(
    make_engine_client: Callable[..., TestClient],
    fake_engine: FakeEngine,
    folders: list[Path],
) -> None:
    client = make_engine_client(max_runs=2)
    fake_engine.mode = "hold"
    for folder in folders[:3]:
        _resume(client, folder.name)
    wait_until(lambda: len(fake_engine.calls) == 2)

    assert _stop(client, folders[2].name) == 202
    assert _stop(client, folders[2].name) == 409
    fake_engine.release.set()
    wait_until(
        lambda: all(
            client.get(f"/api/v1/engine/{folder.name}").json()["status"] == "completed"
            for folder in folders[:2]
        )
    )
    time.sleep(0.1)

    assert folders[2].name not in _called(fake_engine)
    assert not (folders[2] / execution_layout.LOGS / EVENTS_FILE).exists()


def test_a_start_of_a_queued_experiment_is_run_in_progress(
    make_engine_client: Callable[..., TestClient],
    fake_engine: FakeEngine,
    folders: list[Path],
) -> None:
    client = make_engine_client(max_runs=1)
    fake_engine.mode = "hold"
    _resume(client, folders[0].name)
    _resume(client, folders[1].name)

    response = client.post(f"/api/v1/engine/evaluate/{folders[1].name}")

    assert response.status_code == 409
    assert response.json()["code"] == "run_in_progress"


def test_a_crash_frees_the_slot_for_the_next_job(
    make_engine_client: Callable[..., TestClient],
    fake_engine: FakeEngine,
    folders: list[Path],
) -> None:
    client = make_engine_client(max_runs=1)
    fake_engine.mode = "crash"

    _resume(client, folders[0].name)
    _resume(client, folders[1].name)

    wait_until(lambda: len(fake_engine.calls) == 2)
    assert _called(fake_engine) == [folders[0].name, folders[1].name]


def test_shutdown_starts_no_queued_run_and_waits_at_most_the_stop_time(
    make_engine_client: Callable[..., TestClient],
    fake_engine: FakeEngine,
    folders: list[Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("METIS_API_STOP_TIMEOUT", "1")
    client = make_engine_client(max_runs=1)
    fake_engine.mode = "stubborn"
    _resume(client, folders[0].name)
    _resume(client, folders[1].name)
    wait_until(lambda: len(fake_engine.calls) == 1)

    began = time.monotonic()
    with structlog.testing.capture_logs() as logs:
        client.__exit__(None, None, None)
    waited = time.monotonic() - began
    # The stubborn run ends now. Its slot must not start the queued run.
    fake_engine.release.set()
    time.sleep(0.2)

    assert waited < 2.5
    assert [log["event"] for log in logs].count("engine_run_did_not_stop") == 1
    assert _called(fake_engine) == [folders[0].name]


def test_shutdown_waits_for_every_running_run_against_one_time_limit(
    make_engine_client: Callable[..., TestClient],
    fake_engine: FakeEngine,
    folders: list[Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("METIS_API_STOP_TIMEOUT", "1")
    client = make_engine_client(max_runs=3)
    fake_engine.mode = "stubborn"
    for folder in folders[:3]:
        _resume(client, folder.name)
    wait_until(lambda: len(fake_engine.calls) == 3)

    began = time.monotonic()
    with structlog.testing.capture_logs() as logs:
        client.__exit__(None, None, None)
    waited = time.monotonic() - began

    assert waited < 2.5
    warned = [log for log in logs if log["event"] == "engine_run_did_not_stop"]
    assert sorted(log["experiment_id"] for log in warned) == [
        folder.name for folder in folders[:3]
    ]


def _status(client: TestClient, experiment_id: str) -> dict[str, object]:
    return client.get(f"/api/v1/engine/{experiment_id}").json()


def test_a_queued_run_shows_its_place(
    make_engine_client: Callable[..., TestClient],
    fake_engine: FakeEngine,
    folders: list[Path],
) -> None:
    client = make_engine_client(max_runs=1)
    fake_engine.mode = "hold"
    for folder in folders[:3]:
        _resume(client, folder.name)
    wait_until(lambda: _status(client, folders[0].name)["total"] == 2)

    running, next_one, last = (_status(client, f.name) for f in folders[:3])

    assert (running["status"], running["queue_ahead"]) == ("running", None)
    assert next_one == {
        "experiment_id": folders[1].name,
        "phase": "simulating",
        "status": "queued",
        "queue_ahead": 0,
        "total": None,
        "done": None,
        "reason": None,
        "last_seq": 0,
    }
    assert (last["status"], last["queue_ahead"]) == ("queued", 1)


def test_a_place_moves_up_when_a_run_ahead_leaves_the_queue(
    make_engine_client: Callable[..., TestClient],
    fake_engine: FakeEngine,
    folders: list[Path],
) -> None:
    client = make_engine_client(max_runs=1)
    fake_engine.mode = "hold"
    for folder in folders[:3]:
        _resume(client, folder.name)

    _stop(client, folders[1].name)

    assert _status(client, folders[2].name)["queue_ahead"] == 0


def test_a_queued_evaluate_shows_the_phase_of_its_first_step(
    make_engine_client: Callable[..., TestClient],
    fake_engine: FakeEngine,
    folders: list[Path],
) -> None:
    client = make_engine_client(max_runs=1)
    fake_engine.mode = "hold"
    _resume(client, folders[0].name)
    client.post(f"/api/v1/engine/evaluate/{folders[1].name}")

    status = _status(client, folders[1].name)

    assert (status["phase"], status["status"]) == ("evaluating", "queued")


def test_queue_ahead_is_null_when_no_run_is_alive(
    engine_client: TestClient, folders: list[Path]
) -> None:
    assert _status(engine_client, folders[0].name)["queue_ahead"] is None
    _resume(engine_client, folders[0].name)
    wait_until(
        lambda: (
            _status(engine_client, folders[0].name)["status"] == "completed"
            and _status(engine_client, folders[0].name)["phase"] == "evaluating"
        )
    )

    assert _status(engine_client, folders[0].name)["queue_ahead"] is None


def test_a_job_that_moves_to_evaluate_reports_evaluating(
    engine_client: TestClient,
    fake_engine: FakeEngine,
    folders: list[Path],
) -> None:
    held = threading.Event()
    release = threading.Event()

    def evaluate(experiment_dir: Path, **_: object) -> None:
        events = PhaseEventLog.for_experiment_dir(experiment_dir)
        events.emit("evaluating", "started", total=5, done=1)
        held.set()
        release.wait(5)
        events.emit("evaluating", "completed")

    engine_client.app.state.engine_runs.functions = fake_engine.functions(
        resume_evaluation=evaluate
    )
    _resume(engine_client, folders[0].name)
    assert held.wait(5)

    status = _status(engine_client, folders[0].name)
    release.set()

    assert (status["phase"], status["status"]) == ("evaluating", "running")
    assert (status["total"], status["done"]) == (5, 1)


def test_a_job_whose_thread_cannot_start_frees_its_slot(
    fake_engine: FakeEngine,
    folders: list[Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs = engine_runs.EngineRuns(fake_engine.functions(), max_runs=1)
    real_thread = threading.Thread
    refused: list[str] = []

    class NoThread(real_thread):
        def start(self) -> None:
            if not refused:
                refused.append(self.name)
                raise RuntimeError("can't start new thread")
            super().start()

    monkeypatch.setattr(engine_runs.threading, "Thread", NoThread)

    resume = fake_engine.functions().resume_simulation

    def work(experiment_dir: Path, stop: threading.Event, console: Console) -> None:
        resume(experiment_dir, concurrency=1, stop=stop, console=console)

    def start(folder: Path) -> str:
        return runs.start(
            project_dir=folder.parent.parent.parent,
            experiment_id=folder.name,
            prepare=lambda: folder,
            steps=[engine_runs.Step("simulating", work)],
        )

    with structlog.testing.capture_logs() as logs:
        start(folders[0])
    project_dir = folders[0].parent.parent.parent

    # The job is gone, so the experiment shows the state of its folder, and can start again.
    assert runs.current(project_dir, folders[0].name) is None
    assert [log["event"] for log in logs].count("engine_run_not_started") == 1
    start(folders[0])
    wait_until(
        lambda: [call.experiment_dir for call in fake_engine.calls] == [folders[0]]
    )
    runs.shutdown(5)


def test_a_start_after_shutdown_is_refused_and_makes_no_folder(
    fake_engine: FakeEngine, folders: list[Path]
) -> None:
    runs = engine_runs.EngineRuns(fake_engine.functions(), max_runs=1)
    runs.shutdown(1)
    prepared: list[Path] = []

    def prepare() -> Path:
        prepared.append(folders[0])
        return folders[0]

    with pytest.raises(RouteError) as refused:
        runs.start(
            project_dir=folders[0].parent.parent.parent,
            experiment_id=None,
            prepare=prepare,
            steps=[engine_runs.Step("simulating", lambda *_: None)],
        )

    assert (refused.value.status, refused.value.code) == (503, "engine_stopping")
    assert refused.value.retryable is True
    assert prepared == []
    assert fake_engine.calls == []
