"""Each record belongs to one user account, and a user reads only the records of that account."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from metis.api.store import LOCAL_USER_ID, Store
from metis.api.tables import targets, users
from tests.fixtures.api.records import done_state, put_interview, ref, web_record

ADMIN = {"Authorization": "Bearer workshop-admin-token"}
TARGET = "20261114-101500-interview-k7mwp"
OTHER_TARGET = "20261114-101500-interview-x3r9t"
EXPERIMENT = "bank-bot-20261114-101500"
MakeClient = Callable[..., TestClient]


@pytest.fixture
def login_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("METIS_LOGIN", "1")
    monkeypatch.setenv("METIS_ADMIN_TOKEN", "workshop-admin-token")
    monkeypatch.delenv("HOST", raising=False)


def _user(make_client: MakeClient) -> tuple[TestClient, str]:
    """A browser of a new user account in a login session, and the id of the account."""
    client = make_client()
    client.__enter__()
    user = client.post("/api/v1/users", headers=ADMIN).json()
    login = client.post(
        "/api/v1/auth/login",
        json={"username": user["username"], "password": user["password"]},
    )
    assert login.status_code == 200
    return client, user["id"]


@pytest.fixture
def two_users(
    login_on: None, make_client: MakeClient
) -> tuple[tuple[TestClient, str], tuple[TestClient, str]]:
    first, second = _user(make_client), _user(make_client)
    yield first, second
    for client, _ in (first, second):
        client.__exit__(None, None, None)


def _save(client: TestClient, title: str, content: bytes, target: str = TARGET) -> None:
    record = web_record(
        target,
        done_state(),
        fixtures=[ref("policy.pdf", content, "application/pdf")],
    )
    record["title"] = title
    response = put_interview(
        client, record, [("files", ("policy.pdf", content, "application/pdf"))]
    )
    assert response.status_code == 204, response.text


def test_each_user_has_their_own_targets_and_project_folder(
    two_users, project_dir: Path, store: Store
) -> None:
    (alice, alice_id), (bob, bob_id) = two_users

    _save(alice, "Bank bot", b"policy of alice", TARGET)
    _save(bob, "Shop bot", b"policy of bob", OTHER_TARGET)

    for client, user_id, target, title, content in (
        (alice, alice_id, TARGET, "Bank bot", b"policy of alice"),
        (bob, bob_id, OTHER_TARGET, "Shop bot", b"policy of bob"),
    ):
        base = f"/api/v1/targets/{target}"
        listed = client.get("/api/v1/targets").json()["targets"]
        assert [(row["id"], row["title"]) for row in listed] == [(target, title)]
        assert client.get(f"{base}/interview").json()["title"] == title
        assert client.get(f"{base}/interview/files/policy.pdf").content == content
        folder = project_dir / "users" / user_id / "experiments" / "design" / target
        assert (folder / "inputs" / "documents" / "policy.pdf").read_bytes() == content
    assert not (project_dir / "experiments").exists()
    with store.engine.connect() as connection:
        rows = connection.execute(select(targets.c.user_id, targets.c.id)).all()
    assert sorted(rows) == sorted([(alice_id, TARGET), (bob_id, OTHER_TARGET)])


def test_a_save_with_the_target_id_of_another_user_changes_nothing(
    two_users, project_dir: Path
) -> None:
    (alice, _), (bob, bob_id) = two_users
    _save(alice, "Bank bot", b"policy of alice")

    record = web_record(TARGET, done_state())
    record["created_at"] += 1
    refused = put_interview(bob, record, [])

    assert refused.status_code == 409
    assert refused.json()["code"] == "target_exists"
    assert bob.get("/api/v1/targets").json()["targets"] == []
    assert not (project_dir / "users" / bob_id).exists()
    assert (
        alice.get(f"/api/v1/targets/{TARGET}/interview").json()["title"] == "Bank bot"
    )


def test_a_record_of_another_user_is_a_record_that_does_not_exist(two_users) -> None:
    (alice, _), (bob, _) = two_users
    _save(alice, "Bank bot", b"policy of alice")
    base = f"/api/v1/targets/{TARGET}"

    assert bob.get("/api/v1/targets").json() == {"targets": [], "problems": []}
    for path in (
        f"{base}/interview",
        f"{base}/interview/files/policy.pdf",
        f"{base}/specification",
        f"{base}/experiments",
    ):
        response = bob.get(path)
        assert response.status_code == 404, path
        assert response.json()["code"] == "not_found"
    assert bob.delete(base).status_code == 404

    assert alice.get(f"{base}/interview").json()["title"] == "Bank bot"
    assert alice.get(f"{base}/specification").status_code == 200


def test_two_users_can_each_have_an_experiment_folder_with_the_same_name(
    two_users, project_dir: Path
) -> None:
    (alice, alice_id), (bob, bob_id) = two_users
    for client, user_id, title, target in (
        (alice, alice_id, "Bank bot", TARGET),
        (bob, bob_id, "Shop bot", OTHER_TARGET),
    ):
        _save(client, title, b"policy", target)
        folder = project_dir / "users" / user_id / "experiments" / "execute"
        (folder / EXPERIMENT).mkdir(parents=True)

    path = f"/api/v1/experiments/{EXPERIMENT}"
    first = alice.put(path, json={"target_id": TARGET, "step": "simulate"})
    second = bob.put(path, json={"target_id": OTHER_TARGET, "step": "evaluate"})

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert alice.get(path).json()["step"] == "simulate"
    assert bob.get(path).json()["step"] == "evaluate"

    assert bob.delete(path).status_code == 204

    assert bob.get(path).status_code == 404
    assert alice.get(path).json()["step"] == "simulate"


def test_a_user_reaches_only_the_experiment_folders_of_their_account(
    two_users, project_dir: Path
) -> None:
    (alice, alice_id), (bob, _) = two_users
    _save(alice, "Bank bot", b"policy")
    _save(bob, "Shop bot", b"policy", OTHER_TARGET)
    folder = project_dir / "users" / alice_id / "experiments" / "execute"
    (folder / EXPERIMENT).mkdir(parents=True)
    path = f"/api/v1/experiments/{EXPERIMENT}"
    assert (
        alice.put(path, json={"target_id": TARGET, "step": "simulate"}).status_code
        == 200
    )

    saved = bob.put(path, json={"target_id": OTHER_TARGET, "step": "simulate"})
    report = bob.get(f"{path}/report")

    assert saved.status_code == 400
    assert "does not exist" in saved.json()["message"]
    assert bob.get(path).status_code == 404
    assert report.status_code == 404
    assert report.json()["code"] == "experiment_not_found"
    assert alice.get(f"{path}/report").json()["code"] == "results_missing"


def test_a_user_sees_their_records_from_a_new_browser(
    login_on: None, make_client: MakeClient
) -> None:
    with make_client() as first, make_client() as second:
        user = first.post("/api/v1/users", headers=ADMIN).json()
        credentials = {"username": user["username"], "password": user["password"]}
        assert first.post("/api/v1/auth/login", json=credentials).status_code == 200
        _save(first, "Bank bot", b"policy")

        assert second.post("/api/v1/auth/login", json=credentials).status_code == 200

        assert second.get(f"/api/v1/targets/{TARGET}/interview").json()["title"] == (
            "Bank bot"
        )


def test_with_login_off_the_records_belong_to_the_local_user_account(
    client: TestClient, project_dir: Path, store: Store
) -> None:
    with client:
        _save(client, "Bank bot", b"policy")

        assert client.get(f"/api/v1/targets/{TARGET}/interview").status_code == 200

    folder = project_dir / "experiments" / "design" / TARGET
    assert (folder / "inputs" / "documents" / "policy.pdf").is_file()
    assert not (project_dir / "users").exists()
    with store.engine.connect() as connection:
        assert connection.execute(select(targets.c.user_id)).scalars().all() == [
            LOCAL_USER_ID
        ]
        local = connection.execute(select(users)).one()
    assert (local.id, local.username, local.password_hash) == ("local", "local", None)


def test_a_user_does_not_see_the_records_of_the_local_user_account(
    make_client: MakeClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client() as laptop:
        _save(laptop, "Bank bot", b"policy")
    monkeypatch.setenv("METIS_LOGIN", "1")
    monkeypatch.setenv("METIS_ADMIN_TOKEN", "workshop-admin-token")
    client, _ = _user(make_client)
    with client:
        assert client.get("/api/v1/targets").json()["targets"] == []
        assert client.get(f"/api/v1/targets/{TARGET}/interview").status_code == 404
        local = client.post(
            "/api/v1/auth/login", json={"username": "local", "password": ""}
        )
        assert local.status_code == 401
