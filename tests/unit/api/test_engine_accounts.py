"""The engine routes with login on: each user account reaches only its own project folder."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from metis.core import execution_layout, project_layout
from tests.fixtures.api.engine import wait_until, write_input_dir
from tests.unit.engine.test_cli_simulate import MINIMAL_EXPERIMENT

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from tests.fixtures.api.engine import FakeEngine

ADMIN = {"Authorization": "Bearer workshop-admin-token"}
EXPERIMENT = "test-exp-20260101-000000"
INPUT_DIR = "experiments/design/t1/outputs"


class User:
    """A browser in a login session of one user account, and its project folder."""

    def __init__(self, client: TestClient, user_id: str, project_dir: Path) -> None:
        self.client = client
        self.folder = project_dir / "users" / user_id

    def experiment(self, name: str = EXPERIMENT) -> str:
        """Make an experiment folder in the project folder of this user account."""
        write_input_dir(
            self.folder
            / project_layout.EXPERIMENTS
            / name
            / execution_layout.SPECIFICATION_DIR
        )
        return name


@pytest.fixture
def users(
    monkeypatch: pytest.MonkeyPatch,
    make_engine_client: Callable[..., TestClient],
    project_dir: Path,
) -> Iterator[tuple[User, User]]:
    """Two user accounts in login sessions on one server, each with its project folder.

    Both browsers use one app, as on a real server, so they share its one engine run.
    """
    monkeypatch.setenv("METIS_LOGIN", "1")
    monkeypatch.setenv("METIS_ADMIN_TOKEN", "workshop-admin-token")
    monkeypatch.delenv("HOST", raising=False)
    server = make_engine_client()
    made: list[User] = []
    for client in (server, TestClient(server.app)):
        account = client.post("/api/v1/users", headers=ADMIN).json()
        login = client.post(
            "/api/v1/auth/login",
            json={"username": account["username"], "password": account["password"]},
        )
        assert login.status_code == 200
        user = User(client, account["id"], project_dir)
        user.folder.mkdir(parents=True)
        made.append(user)
    yield made[0], made[1]


def test_an_input_dir_is_relative_to_the_project_folder_of_the_user(
    users: tuple[User, User],
) -> None:
    alice, bob = users
    write_input_dir(alice.folder / INPUT_DIR)

    started = alice.client.post(
        "/api/v1/engine/simulate", json={"input_dir": INPUT_DIR}
    )
    refused = bob.client.post("/api/v1/engine/simulate", json={"input_dir": INPUT_DIR})

    assert started.status_code == 202
    experiment_id = started.json()["experiment_id"]
    assert (alice.folder / project_layout.EXPERIMENTS / experiment_id).is_dir()
    assert refused.status_code == 422
    assert refused.json()["code"] == "invalid_inputs"
    assert str(bob.folder / INPUT_DIR) in refused.json()["message"]


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("../{user}/" + INPUT_DIR, id="from-the-user-folder"),
        pytest.param("users/{user}/" + INPUT_DIR, id="from-the-server-folder"),
    ],
)
def test_an_input_dir_of_another_user_cannot_start_a_run(
    users: tuple[User, User], fake_engine: FakeEngine, path: str
) -> None:
    alice, bob = users
    write_input_dir(bob.folder / INPUT_DIR)

    response = alice.client.post(
        "/api/v1/engine/simulate", json={"input_dir": path.format(user=bob.folder.name)}
    )

    assert response.status_code == 422
    assert response.json()["code"] in ("input_dir_outside_project", "invalid_inputs")
    assert fake_engine.calls == []
    assert not (bob.folder / project_layout.EXPERIMENTS).exists()


ID_ROUTES = [
    ("post", "/api/v1/engine/simulate/{id}/resume", 202),
    ("post", "/api/v1/engine/evaluate/{id}", 202),
    ("post", "/api/v1/engine/evaluate/{id}/resume", 202),
    ("post", "/api/v1/engine/{id}/stop", 409),
    ("get", "/api/v1/engine/{id}", 200),
    ("get", "/api/v1/engine/{id}/events", 200),
]


@pytest.mark.parametrize(("method", "route", "status"), ID_ROUTES)
def test_each_route_finds_an_experiment_of_the_user(
    users: tuple[User, User], method: str, route: str, status: int
) -> None:
    alice, _ = users
    experiment_id = alice.experiment()

    response = getattr(alice.client, method)(route.format(id=experiment_id))

    assert response.status_code == status, response.text


@pytest.mark.parametrize(("method", "route", "status"), ID_ROUTES)
def test_an_experiment_of_another_user_is_not_found(
    users: tuple[User, User],
    fake_engine: FakeEngine,
    method: str,
    route: str,
    status: int,
) -> None:
    alice, bob = users
    experiment_id = bob.experiment()

    response = getattr(alice.client, method)(route.format(id=experiment_id))

    assert response.status_code == 404
    assert response.json()["code"] == "experiment_not_found"
    assert fake_engine.calls == []


def test_a_start_while_another_user_runs_names_no_experiment(
    users: tuple[User, User], fake_engine: FakeEngine
) -> None:
    alice, bob = users
    fake_engine.mode = "hold"
    running = alice.experiment("test-exp-20260101-000001")
    alice.client.post(f"/api/v1/engine/simulate/{running}/resume")
    other = bob.experiment("test-exp-20260101-000002")

    response = bob.client.post(f"/api/v1/engine/simulate/{other}/resume")

    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "engine_busy"
    assert body["retryable"] is True
    assert body["message"] == (
        "The engine runs an experiment of another user account. "
        "Start this run when that run ends."
    )
    assert running not in body["message"]


def test_the_same_name_as_the_run_of_another_user_is_not_that_run(
    users: tuple[User, User], fake_engine: FakeEngine
) -> None:
    alice, bob = users
    fake_engine.mode = "hold"
    alice.experiment()
    bob.experiment()
    alice.client.post(f"/api/v1/engine/simulate/{EXPERIMENT}/resume")
    wait_until(
        lambda: alice.client.get(f"/api/v1/engine/{EXPERIMENT}").json()["total"] == 2
    )

    status = bob.client.get(f"/api/v1/engine/{EXPERIMENT}").json()
    stop = bob.client.post(f"/api/v1/engine/{EXPERIMENT}/stop")
    resume = bob.client.post(f"/api/v1/engine/simulate/{EXPERIMENT}/resume")

    assert (status["status"], status["last_seq"]) == ("not_started", 0)
    assert stop.status_code == 409
    assert stop.json()["code"] == "no_run"
    assert resume.status_code == 503
    assert resume.json()["code"] == "engine_busy"
    assert alice.client.get(f"/api/v1/engine/{EXPERIMENT}").json()["status"] == (
        "running"
    )


def test_a_specification_id_that_names_the_folder_of_another_user_is_refused(
    users: tuple[User, User], fake_engine: FakeEngine
) -> None:
    alice, bob = users
    escape = f"../../../{bob.folder.name}/evaluations/experiments/planted"
    write_input_dir(
        alice.folder / INPUT_DIR,
        MINIMAL_EXPERIMENT.replace("id: test-exp\n", f"id: {escape}\n"),
    )

    response = alice.client.post(
        "/api/v1/engine/simulate", json={"input_dir": INPUT_DIR}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_inputs"
    assert "must be one folder name" in response.json()["message"]
    assert fake_engine.calls == []
    assert not (bob.folder / "experiments").exists()
    assert not (alice.folder / project_layout.EXPERIMENTS).exists()
