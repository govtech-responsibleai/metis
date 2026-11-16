"""Start an Experiment of a Target: the input folder of its Specification, the run, and the row."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from metis.core import execution_layout
from metis.wizard import InterviewState
from tests.fixtures.api.engine import wait_until
from tests.fixtures.api.records import done_state, put_interview, ref, web_record

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from tests.fixtures.api.engine import FakeEngine

TARGET = "20261112-101500-interview"
POLICY = b"policy bytes"
ADMIN = {"Authorization": "Bearer workshop-admin-token"}


def _start(client: TestClient, target_id: str = TARGET, **body: object):
    return client.post(f"/api/v1/targets/{target_id}/experiments", json=body)


def _save_done_target(client: TestClient, target_id: str = TARGET) -> None:
    record = web_record(
        target_id, done_state(), fixtures=[ref("policy.pdf", POLICY, "application/pdf")]
    )
    response = put_interview(
        client, record, [("files", ("policy.pdf", POLICY, "application/pdf"))]
    )
    assert response.status_code == 204, response.text


def test_a_start_runs_the_specification_and_saves_the_experiment_row(
    engine_client: TestClient, fake_engine: FakeEngine, project_dir: Path
) -> None:
    _save_done_target(engine_client)

    response = _start(engine_client, concurrency=2)

    assert response.status_code == 202, response.text
    row = response.json()
    assert row["target_id"] == TARGET
    assert row["step"] == "simulate"
    experiment_dir = project_dir / execution_layout.EXECUTIONS / row["experiment_id"]
    assert (experiment_dir / execution_layout.SPECIFICATION).is_file()
    assert (experiment_dir / execution_layout.FIXTURES / "policy.pdf").read_bytes() == (
        POLICY
    )
    wait_until(lambda: len(fake_engine.calls) == 1)
    [call] = fake_engine.calls
    assert (call.name, call.experiment_dir, call.options) == (
        "simulate",
        experiment_dir,
        {"concurrency": 2},
    )
    listed = engine_client.get(f"/api/v1/targets/{TARGET}/experiments").json()
    assert listed["experiments"] == [row]


def test_a_target_has_one_experiment_row_for_each_start(
    engine_client: TestClient,
) -> None:
    _save_done_target(engine_client)

    first = _start(engine_client).json()["experiment_id"]
    wait_until(
        lambda: (
            engine_client.get(f"/api/v1/engine/{first}").json()["status"] == "completed"
        )
    )
    # Experiment folders are named to the second, so a second start in the same second
    # would get 409 experiment_exists.
    wait_until(lambda: _start(engine_client).status_code == 202, timeout=3)

    listed = engine_client.get(f"/api/v1/targets/{TARGET}/experiments").json()
    ids = [row["experiment_id"] for row in listed["experiments"]]
    assert len(ids) == 2
    assert first in ids


def test_a_target_whose_interview_is_not_done_gets_404_and_starts_nothing(
    engine_client: TestClient, fake_engine: FakeEngine, project_dir: Path
) -> None:
    unfinished = InterviewState.model_validate(
        {**done_state().model_dump(mode="json"), "confirmed": False}
    )
    put_interview(engine_client, web_record(TARGET, unfinished))

    response = _start(engine_client)
    unknown = _start(engine_client, "no-such-target")

    assert (response.status_code, response.json()["code"]) == (404, "not_found")
    assert unknown.status_code == 404
    assert not (project_dir / execution_layout.EXECUTIONS).exists()
    assert fake_engine.calls == []


def test_a_start_while_the_engine_runs_gets_503_and_saves_no_row(
    engine_client: TestClient, fake_engine: FakeEngine
) -> None:
    _save_done_target(engine_client)
    fake_engine.mode = "hold"
    running = _start(engine_client).json()["experiment_id"]

    response = _start(engine_client)

    assert response.status_code == 503
    assert response.json()["code"] == "engine_busy"
    assert response.json()["retryable"] is True
    listed = engine_client.get(f"/api/v1/targets/{TARGET}/experiments").json()
    assert [row["experiment_id"] for row in listed["experiments"]] == [running]


def test_a_start_refuses_a_concurrency_above_the_setting(
    engine_client: TestClient, fake_engine: FakeEngine
) -> None:
    _save_done_target(engine_client)

    response = _start(engine_client, concurrency=99)

    assert (response.status_code, response.json()["code"]) == (422, "validation_error")
    assert fake_engine.calls == []


def test_with_login_on_a_start_runs_in_the_folder_of_the_user_account(
    monkeypatch: pytest.MonkeyPatch,
    make_engine_client: Callable[..., TestClient],
    project_dir: Path,
) -> None:
    monkeypatch.setenv("METIS_LOGIN", "1")
    monkeypatch.setenv("METIS_ADMIN_TOKEN", "workshop-admin-token")
    monkeypatch.delenv("HOST", raising=False)
    server = make_engine_client()
    browsers: list[tuple[TestClient, str]] = []
    for client in (server, TestClient(server.app)):
        account = client.post("/api/v1/users", headers=ADMIN).json()
        client.post(
            "/api/v1/auth/login",
            json={"username": account["username"], "password": account["password"]},
        )
        browsers.append((client, account["id"]))
    (owner, owner_id), (other, _) = browsers
    _save_done_target(owner)

    response = _start(owner)
    refused = _start(other)

    assert response.status_code == 202, response.text
    experiment_id = response.json()["experiment_id"]
    folder = project_dir / "users" / owner_id / execution_layout.EXECUTIONS
    assert (folder / experiment_id).is_dir()
    assert refused.status_code == 404
    assert other.get(f"/api/v1/engine/{experiment_id}").status_code == 404
