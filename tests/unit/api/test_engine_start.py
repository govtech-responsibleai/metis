"""Start a simulation: process setup, the input folder, and the errors before the run starts."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from metis.core import execution_layout
from metis.engine.run import ExperimentExistsError
from tests.fixtures.api.engine import SPECIFICATION_ID, wait_until, write_input_dir

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from fastapi.testclient import TestClient

    from tests.fixtures.api.engine import FakeEngine

SIMULATE = "/api/v1/engine/simulate"


def _relative(project_dir: Path, folder: Path) -> str:
    return folder.relative_to(project_dir).as_posix()


def _executions(project_dir: Path) -> list[str]:
    folder = project_dir / execution_layout.EXECUTIONS
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def test_the_app_sets_up_the_process_one_time_before_a_request(
    make_engine_client: Callable[..., TestClient], fake_engine: FakeEngine
) -> None:
    make_engine_client()

    assert fake_engine.setups == 1


def test_a_start_creates_the_experiment_and_returns_its_id(
    engine_client: TestClient,
    fake_engine: FakeEngine,
    project_dir: Path,
    input_dir: Path,
) -> None:
    response = engine_client.post(
        SIMULATE, json={"input_dir": _relative(project_dir, input_dir)}
    )

    assert response.status_code == 202
    experiment_id = response.json()["experiment_id"]
    assert experiment_id.startswith(f"{SPECIFICATION_ID}-")
    experiment_dir = project_dir / execution_layout.EXECUTIONS / experiment_id
    assert (experiment_dir / execution_layout.SPECIFICATION).is_file()
    wait_until(lambda: len(fake_engine.calls) == 1)
    [call] = fake_engine.calls
    assert call.name == "simulate"
    assert call.experiment_dir == experiment_dir
    assert call.options == {"concurrency": 1}


def test_a_start_passes_the_concurrency_of_the_request(
    engine_client: TestClient,
    fake_engine: FakeEngine,
    project_dir: Path,
    input_dir: Path,
) -> None:
    engine_client.post(
        SIMULATE,
        json={"input_dir": _relative(project_dir, input_dir), "concurrency": 3},
    )

    wait_until(lambda: len(fake_engine.calls) == 1)
    assert fake_engine.calls[0].options == {"concurrency": 3}


@pytest.mark.parametrize("concurrency", [0, 9])
def test_a_concurrency_outside_its_limits_is_refused(
    engine_client: TestClient, project_dir: Path, input_dir: Path, concurrency: int
) -> None:
    response = engine_client.post(
        SIMULATE,
        json={
            "input_dir": _relative(project_dir, input_dir),
            "concurrency": concurrency,
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert "concurrency" in response.json()["message"]
    assert _executions(project_dir) == []


def test_an_absolute_input_dir_is_refused(
    engine_client: TestClient, input_dir: Path, project_dir: Path
) -> None:
    response = engine_client.post(SIMULATE, json={"input_dir": str(input_dir)})

    assert response.status_code == 422
    assert response.json()["code"] == "input_dir_outside_project"
    assert _executions(project_dir) == []


def test_an_input_dir_that_goes_out_with_dot_dot_is_refused(
    engine_client: TestClient, project_dir: Path, tmp_path: Path
) -> None:
    write_input_dir(tmp_path / "outside")

    response = engine_client.post(SIMULATE, json={"input_dir": "../outside"})

    assert response.status_code == 422
    assert response.json()["code"] == "input_dir_outside_project"
    assert _executions(project_dir) == []


def test_an_input_dir_that_links_outside_the_project_is_refused(
    engine_client: TestClient, project_dir: Path, tmp_path: Path
) -> None:
    outside = write_input_dir(tmp_path / "outside")
    os.symlink(outside, project_dir / "linked", target_is_directory=True)

    response = engine_client.post(SIMULATE, json={"input_dir": "linked"})

    assert response.status_code == 422
    assert response.json()["code"] == "input_dir_outside_project"
    assert _executions(project_dir) == []


def test_an_input_dir_that_the_engine_refuses_gives_the_engine_text(
    engine_client: TestClient, project_dir: Path
) -> None:
    (project_dir / "empty").mkdir()

    response = engine_client.post(SIMULATE, json={"input_dir": "empty"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "invalid_inputs"
    assert body["message"] == (
        f"missing required file 'specification.yaml' in {project_dir / 'empty'}"
    )
    assert _executions(project_dir) == []


def test_a_project_folder_that_is_not_a_folder_is_invalid_inputs(
    make_engine_client: Callable[..., TestClient],
    project_dir: Path,
    input_dir: Path,
    tmp_path: Path,
) -> None:
    def prepare(input_dir: Path, *, project_dir: Path, console: object) -> Path:
        from metis.engine.run import prepare_experiment

        return prepare_experiment(
            input_dir, project_dir=tmp_path / "gone", console=console
        )

    client = make_engine_client(prepare_experiment=prepare)

    response = client.post(
        SIMULATE, json={"input_dir": _relative(project_dir, input_dir)}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_inputs"
    assert "is not an existing folder" in response.json()["message"]


def test_a_folder_name_that_is_taken_is_experiment_exists(
    make_engine_client: Callable[..., TestClient],
    fake_engine: FakeEngine,
    project_dir: Path,
    input_dir: Path,
) -> None:
    def prepare(input_dir: Path, *, project_dir: Path, console: object) -> Path:
        raise ExperimentExistsError("the run folder 'x' already exists.")

    client = make_engine_client(prepare_experiment=prepare)

    response = client.post(
        SIMULATE, json={"input_dir": _relative(project_dir, input_dir)}
    )

    assert response.status_code == 409
    assert response.json() == {
        "type": "failure",
        "code": "experiment_exists",
        "message": "the run folder 'x' already exists.",
        "retryable": False,
    }
    assert fake_engine.calls == []


def test_a_start_while_a_run_is_alive_is_engine_busy(
    engine_client: TestClient,
    fake_engine: FakeEngine,
    project_dir: Path,
    input_dir: Path,
) -> None:
    fake_engine.mode = "hold"
    body = {"input_dir": _relative(project_dir, input_dir)}
    first = engine_client.post(SIMULATE, json=body).json()["experiment_id"]

    response = engine_client.post(SIMULATE, json=body)

    assert response.status_code == 503
    assert response.json()["code"] == "engine_busy"
    assert response.json()["retryable"] is True
    assert first in response.json()["message"]
    assert _executions(project_dir) == [first]
