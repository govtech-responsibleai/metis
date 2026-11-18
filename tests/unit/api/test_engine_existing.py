"""Resume and evaluate an experiment folder: the library call and the errors before it starts."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from metis.core import execution_layout, project_layout
from metis.engine.extractor import TraceWaitSettings
from tests.fixtures.api.engine import wait_until

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from fastapi.testclient import TestClient

    from tests.fixtures.api.engine import FakeEngine

ROUTES = {
    "resume_simulation": "/api/v1/engine/simulate/{id}/resume",
    "evaluate": "/api/v1/engine/evaluate/{id}",
    "resume_evaluation": "/api/v1/engine/evaluate/{id}/resume",
}
EVALUATIONS = ("evaluate", "resume_evaluation")


@pytest.fixture
def experiment_dir(make_experiment_dir: Callable[..., Path]) -> Path:
    return make_experiment_dir()


def _write_results(experiment_dir: Path) -> None:
    results = experiment_dir / execution_layout.RESULTS
    results.parent.mkdir(parents=True)
    results.write_text('{"run_id": "r1"}')


def test_a_resume_of_a_simulation_runs_with_the_default_concurrency(
    engine_client: TestClient, fake_engine: FakeEngine, experiment_dir: Path
) -> None:
    url = ROUTES["resume_simulation"].format(id=experiment_dir.name)

    response = engine_client.post(url)

    assert response.status_code == 202
    assert response.json() == {"experiment_id": experiment_dir.name}
    wait_until(lambda: len(fake_engine.calls) == 1)
    [call] = fake_engine.calls
    assert (call.name, call.experiment_dir) == ("resume_simulation", experiment_dir)
    assert call.options == {"concurrency": 1}


@pytest.mark.parametrize("name", EVALUATIONS)
def test_an_evaluation_gets_the_trace_wait_and_the_concurrency_of_the_request(
    engine_client: TestClient,
    fake_engine: FakeEngine,
    experiment_dir: Path,
    name: str,
) -> None:
    response = engine_client.post(
        ROUTES[name].format(id=experiment_dir.name),
        json={"concurrency": 2, "langfuse_timeout": 45},
    )

    assert response.status_code == 202
    wait_until(lambda: len(fake_engine.calls) == 1)
    [call] = fake_engine.calls
    assert call.name == name
    assert call.options == {
        "concurrency": 2,
        "trace_wait": TraceWaitSettings(timeout_seconds=45, quiet_seconds=30),
    }


@pytest.mark.parametrize("name", EVALUATIONS)
def test_an_evaluation_with_no_timeout_waits_the_default_time(
    engine_client: TestClient,
    fake_engine: FakeEngine,
    experiment_dir: Path,
    name: str,
) -> None:
    engine_client.post(ROUTES[name].format(id=experiment_dir.name), json={})

    wait_until(lambda: len(fake_engine.calls) == 1)
    assert fake_engine.calls[0].options["trace_wait"].timeout_seconds == 180


@pytest.mark.parametrize("name", list(ROUTES))
def test_an_unknown_experiment_is_not_found(
    engine_client: TestClient, experiment_dir: Path, name: str
) -> None:
    response = engine_client.post(ROUTES[name].format(id="no-such-experiment"))

    assert response.status_code == 404
    assert response.json()["code"] == "experiment_not_found"


@pytest.mark.parametrize("name", list(ROUTES))
def test_a_folder_with_no_snapshot_is_an_invalid_experiment(
    engine_client: TestClient,
    fake_engine: FakeEngine,
    project_dir: Path,
    name: str,
) -> None:
    folder = project_dir / project_layout.EXPERIMENTS / "bare"
    folder.mkdir(parents=True)

    response = engine_client.post(ROUTES[name].format(id="bare"))

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "invalid_experiment"
    assert body["message"] == (
        f"'{folder}' is not a simulation output directory (no 'specification/' snapshot). "
        "Run 'metis engine simulate' first."
    )
    assert fake_engine.calls == []
    assert sorted(p.name for p in folder.iterdir()) == []


@pytest.mark.parametrize("name", list(ROUTES))
def test_a_folder_of_the_earlier_layout_is_an_invalid_experiment(
    engine_client: TestClient,
    fake_engine: FakeEngine,
    experiment_dir: Path,
    name: str,
) -> None:
    (experiment_dir / "trials").mkdir()

    response = engine_client.post(ROUTES[name].format(id=experiment_dir.name))

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "invalid_experiment"
    assert "earlier folder layout" in body["message"]
    assert fake_engine.calls == []


@pytest.mark.parametrize("name", EVALUATIONS)
def test_a_timeout_shorter_than_the_quiet_window_is_refused(
    engine_client: TestClient,
    fake_engine: FakeEngine,
    experiment_dir: Path,
    name: str,
) -> None:
    response = engine_client.post(
        ROUTES[name].format(id=experiment_dir.name), json={"langfuse_timeout": 10}
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "invalid_langfuse_timeout"
    assert "Set the timeout to 30 seconds or more." in body["message"]
    assert fake_engine.calls == []


@pytest.mark.parametrize("name", EVALUATIONS)
def test_a_quiet_window_that_is_not_a_number_is_refused(
    engine_client: TestClient,
    experiment_dir: Path,
    name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGFUSE_METIS_QUIET_SECONDS", "abc")

    response = engine_client.post(ROUTES[name].format(id=experiment_dir.name))

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_langfuse_timeout"
    assert "LANGFUSE_METIS_QUIET_SECONDS" in response.json()["message"]


@pytest.mark.parametrize("name", EVALUATIONS)
def test_a_langfuse_timeout_above_its_maximum_is_a_validation_error(
    engine_client: TestClient, experiment_dir: Path, name: str
) -> None:
    response = engine_client.post(
        ROUTES[name].format(id=experiment_dir.name), json={"langfuse_timeout": 601}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert "langfuse_timeout" in response.json()["message"]


def test_a_resume_of_a_complete_evaluation_is_refused(
    engine_client: TestClient, fake_engine: FakeEngine, experiment_dir: Path
) -> None:
    _write_results(experiment_dir)

    response = engine_client.post(
        ROUTES["resume_evaluation"].format(id=experiment_dir.name)
    )

    assert response.status_code == 409
    assert response.json()["code"] == "evaluation_complete"
    assert fake_engine.calls == []


def test_an_evaluate_of_a_complete_evaluation_is_refused(
    engine_client: TestClient, fake_engine: FakeEngine, experiment_dir: Path
) -> None:
    _write_results(experiment_dir)

    response = engine_client.post(ROUTES["evaluate"].format(id=experiment_dir.name))

    assert response.status_code == 409
    assert response.json()["code"] == "evaluation_complete"
    assert "regrade" in response.json()["message"]
    assert fake_engine.calls == []
    assert (experiment_dir / execution_layout.RESULTS).exists()


def test_an_evaluate_with_regrade_grades_a_complete_evaluation_again(
    engine_client: TestClient, fake_engine: FakeEngine, experiment_dir: Path
) -> None:
    _write_results(experiment_dir)

    response = engine_client.post(
        ROUTES["evaluate"].format(id=experiment_dir.name), json={"regrade": True}
    )

    assert response.status_code == 202
    wait_until(lambda: len(fake_engine.calls) == 1)
    assert fake_engine.calls[0].name == "evaluate"


def test_an_evaluate_of_an_evaluation_that_did_not_end_grades_every_trial(
    engine_client: TestClient, fake_engine: FakeEngine, experiment_dir: Path
) -> None:
    results = experiment_dir / execution_layout.RESULTS
    results.parent.mkdir(parents=True)
    results.write_text("{")  # a results.json that does not load

    response = engine_client.post(ROUTES["evaluate"].format(id=experiment_dir.name))

    assert response.status_code == 202
    wait_until(lambda: len(fake_engine.calls) == 1)
    assert fake_engine.calls[0].name == "evaluate"


def test_regrade_is_not_an_option_of_an_evaluate_resume(
    engine_client: TestClient, fake_engine: FakeEngine, experiment_dir: Path
) -> None:
    response = engine_client.post(
        ROUTES["resume_evaluation"].format(id=experiment_dir.name),
        json={"regrade": True},
    )

    assert response.status_code == 422
    assert fake_engine.calls == []


@pytest.mark.parametrize("name", list(ROUTES))
def test_a_start_for_the_experiment_that_runs_is_run_in_progress(
    engine_client: TestClient,
    fake_engine: FakeEngine,
    experiment_dir: Path,
    name: str,
) -> None:
    fake_engine.mode = "hold"
    engine_client.post(ROUTES["resume_simulation"].format(id=experiment_dir.name))

    response = engine_client.post(ROUTES[name].format(id=experiment_dir.name))

    assert response.status_code == 409
    assert response.json()["code"] == "run_in_progress"


@pytest.mark.parametrize("name", list(ROUTES))
def test_a_start_while_every_slot_is_taken_waits_for_a_slot(
    make_engine_client: Callable[..., TestClient],
    fake_engine: FakeEngine,
    make_experiment_dir: Callable[..., Path],
    name: str,
) -> None:
    client = make_engine_client(max_runs=1)
    running = make_experiment_dir("test-exp-20260101-000001")
    other = make_experiment_dir("test-exp-20260101-000002")
    fake_engine.mode = "hold"
    client.post(ROUTES["resume_simulation"].format(id=running.name))
    wait_until(lambda: len(fake_engine.calls) == 1)

    response = client.post(ROUTES[name].format(id=other.name))

    assert response.status_code == 202
    assert len(fake_engine.calls) == 1
    fake_engine.release.set()
    wait_until(lambda: len(fake_engine.calls) == 2)
    assert (fake_engine.calls[1].name, fake_engine.calls[1].experiment_dir) == (
        name,
        other,
    )


def test_a_bad_timeout_is_checked_after_the_folder_and_the_run(
    make_engine_client: Callable[..., TestClient],
    fake_engine: FakeEngine,
    project_dir: Path,
    make_experiment_dir: Callable[..., Path],
) -> None:
    bad = {"langfuse_timeout": 10}
    bare = project_dir / project_layout.EXPERIMENTS / "bare"
    bare.mkdir(parents=True)
    running = make_experiment_dir("test-exp-20260101-000001")
    other = make_experiment_dir("test-exp-20260101-000002")
    engine_client = make_engine_client(max_runs=1)
    fake_engine.mode = "hold"
    engine_client.post(ROUTES["resume_simulation"].format(id=running.name))

    codes = [
        engine_client.post(ROUTES["evaluate"].format(id=name), json=bad).json()["code"]
        for name in ("no-such-experiment", running.name, other.name)
    ]
    fake_engine.release.set()
    wait_until(
        lambda: (
            engine_client.get(f"/api/v1/engine/{running.name}").json()["status"]
            != "running"
        )
    )
    codes.append(
        engine_client.post(ROUTES["evaluate"].format(id="bare"), json=bad).json()[
            "code"
        ]
    )

    assert codes == [
        "experiment_not_found",
        "run_in_progress",
        "invalid_langfuse_timeout",
        "invalid_experiment",
    ]
