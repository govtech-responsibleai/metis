"""User accounts, the admin token, login sessions, and the guard of the other routes."""

from __future__ import annotations

import json
import re
import stat
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from metis.api.accounts import Accounts, hash_password, verify_password
from metis.api.main import create_app
from metis.api.settings import Settings, SettingsError
from metis.api.store import Store
from metis.api.tables import login_sessions, users

ADMIN = {"Authorization": "Bearer workshop-admin-token"}
USERS = "/api/v1/users"
LOGIN = "/api/v1/auth/login"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"

MakeClient = Callable[..., TestClient]


@pytest.fixture
def login_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """A server with login on and an admin token."""
    monkeypatch.setenv("METIS_LOGIN", "1")
    monkeypatch.setenv("METIS_ADMIN_TOKEN", "workshop-admin-token")
    monkeypatch.delenv("HOST", raising=False)


@pytest.fixture
def browser(login_on: None, make_client: MakeClient) -> TestClient:
    """One browser of a server with login on. It keeps the cookies that it gets."""
    with make_client() as client:
        yield client


def _new_user(client: TestClient) -> dict[str, str]:
    response = client.post(USERS, headers=ADMIN)
    assert response.status_code == 201
    return response.json()


def _log_in(client: TestClient, user: dict[str, str]):
    return client.post(
        LOGIN, json={"username": user["username"], "password": user["password"]}
    )


def test_the_admin_token_makes_user_accounts_and_lists_them_without_a_password(
    browser: TestClient, store: Store
) -> None:
    first = _new_user(browser)
    second = _new_user(browser)

    assert re.fullmatch(r"[a-z]+-[a-z]+", first["username"])
    assert re.fullmatch(r"[a-hj-km-np-z2-9]{5}-[a-hj-km-np-z2-9]{5}", first["password"])
    with store.engine.connect() as connection:
        saved = connection.execute(select(users).where(users.c.id == first["id"])).one()
    assert first["password"] not in saved.password_hash
    assert verify_password(first["password"], saved.password_hash)

    listed = browser.get(USERS, headers=ADMIN)

    assert listed.status_code == 200
    assert listed.json()["users"] == [
        {key: user[key] for key in ("id", "username", "created_at")}
        for user in (first, second)
    ]


def test_a_taken_username_gets_another_name(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    names = iter(["calm-otter"] * 2 + ["calm-heron"] * 10)
    monkeypatch.setattr("metis.api.accounts.new_username", lambda: next(names))
    accounts = Accounts(store.engine)

    made = [accounts.create().account.username for _ in range(3)]

    assert made[:2] == ["calm-otter", "calm-heron"]
    assert re.fullmatch(r"calm-heron-\d{3}", made[2])


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong-token"},
        {"Authorization": "Basic workshop-admin-token"},
        {"Authorization": "workshop-admin-token"},
    ],
)
def test_the_user_routes_refuse_a_request_without_the_admin_token(
    browser: TestClient, headers: dict[str, str]
) -> None:
    for response in (
        browser.post(USERS, headers=headers),
        browser.get(USERS, headers=headers),
    ):
        assert response.status_code == 401
        assert response.json()["code"] == "invalid_admin_token"
        assert response.headers["WWW-Authenticate"] == "Bearer"
    assert browser.get(USERS, headers=ADMIN).json() == {"users": []}


def test_the_api_description_names_the_admin_token_for_the_user_routes(
    browser: TestClient,
) -> None:
    schema = browser.app.openapi()

    assert schema["components"]["securitySchemes"]["AdminToken"]["scheme"] == "bearer"
    for method in ("post", "get"):
        assert schema["paths"][USERS][method]["security"] == [{"AdminToken": []}]
    assert "security" not in schema["paths"][LOGIN]["post"]


def test_the_user_routes_are_off_when_the_server_has_no_admin_token(
    make_client: MakeClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("METIS_LOGIN", "1")
    with make_client() as client:
        for response in (
            client.post(USERS, headers=ADMIN),
            client.get(USERS, headers=ADMIN),
        ):
            assert response.status_code == 404
            assert response.json()["code"] == "not_found"


def test_the_admin_token_does_not_open_the_other_routes(browser: TestClient) -> None:
    response = browser.get("/api/v1/targets", headers=ADMIN)

    assert response.status_code == 401
    assert response.json()["code"] == "login_required"


def test_a_route_needs_a_login_session_when_login_is_on(browser: TestClient) -> None:
    for path in ("/api/v1/targets", "/api/v1/graders", "/api/v1/wizard/config", ME):
        response = browser.get(path)
        assert response.status_code == 401, path
        assert response.json() == {
            "type": "failure",
            "code": "login_required",
            "message": "Log in to use this METIS server.",
            "retryable": False,
        }
    assert browser.get("/health").status_code == 200


def test_a_login_gives_a_cookie_that_opens_the_routes_until_logout(
    browser: TestClient,
) -> None:
    user = _new_user(browser)

    logged_in = _log_in(browser, user)

    assert logged_in.status_code == 200
    account = {key: user[key] for key in ("id", "username", "created_at")}
    assert logged_in.json() == {"login": True, "user": account}
    cookie = logged_in.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Max-Age=2592000" in cookie
    assert "Secure" not in cookie
    assert browser.get(ME).json() == {"login": True, "user": account}
    assert browser.get("/api/v1/targets").status_code == 200

    assert browser.post(LOGOUT).status_code == 204

    assert browser.get("/api/v1/targets").status_code == 401


def test_the_store_keeps_only_a_hash_of_the_cookie_value(
    browser: TestClient, store: Store
) -> None:
    token = _log_in(browser, _new_user(browser)).cookies["metis_login"]

    with store.engine.connect() as connection:
        saved = connection.execute(select(login_sessions)).one()

    assert token not in saved.token_hash
    assert len(saved.token_hash) == 64


def test_a_login_session_ends_after_its_lifetime(
    browser: TestClient, store: Store
) -> None:
    user = _new_user(browser)
    _log_in(browser, user)
    past = datetime.now(UTC) - timedelta(seconds=1)
    with store.engine.begin() as connection:
        connection.execute(update(login_sessions).values(expires_at=past))

    assert browser.get(ME).status_code == 401

    logged_out = browser.post(LOGOUT)
    assert logged_out.status_code == 204
    assert 'metis_login=""' in logged_out.headers["set-cookie"]
    assert "metis_login" not in browser.cookies

    assert _log_in(browser, user).status_code == 200
    with store.engine.connect() as connection:
        assert len(connection.execute(select(login_sessions)).all()) == 1


def test_the_cookie_is_secure_on_a_server_that_other_computers_reach(
    login_on: None, make_client: MakeClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOST", "0.0.0.0")
    with make_client() as client:
        cookie = _log_in(client, _new_user(client)).headers["set-cookie"]

    assert "Secure" in cookie


def test_a_user_file_names_the_user_account_and_its_last_login(
    browser: TestClient, project_dir: Path
) -> None:
    user = _new_user(browser)
    path = project_dir / "users" / user["id"] / "user.json"

    made = json.loads(path.read_text())
    assert {key: made[key] for key in ("id", "username", "password")} == {
        key: user[key] for key in ("id", "username", "password")
    }
    assert datetime.fromisoformat(made["created_at"]) == datetime.fromisoformat(
        user["created_at"]
    )
    assert made["last_login_at"] is None
    assert stat.S_IMODE(path.stat().st_mode) == 0o600

    assert _log_in(browser, user).status_code == 200

    logged_in = json.loads(path.read_text())
    assert logged_in["password"] == user["password"]
    assert logged_in["last_login_at"] is not None
    assert logged_in["created_at"] == made["created_at"]
    assert logged_in["updated_at"] >= made["updated_at"]
    assert sorted(p.name for p in path.parent.iterdir()) == ["user.json"]


def test_a_wrong_login_does_not_change_the_user_file(
    browser: TestClient, project_dir: Path
) -> None:
    user = _new_user(browser)
    path = project_dir / "users" / user["id"] / "user.json"
    before = path.read_text()

    wrong = browser.post(
        LOGIN, json={"username": user["username"], "password": "wrong-guess"}
    )

    assert wrong.status_code == 401
    assert path.read_text() == before


def test_a_user_file_that_cannot_be_written_does_not_stop_the_user_account(
    store: Store, tmp_path: Path
) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("a file where the users folder should be")

    new = Accounts(store.engine, server_dir=blocked).create()

    assert Accounts(store.engine).login(new.account.username, new.password) is not None


@pytest.mark.parametrize(
    "credentials",
    [
        {"username": "no-such-user", "password": "aaaaa-aaaaa"},
        {"username": None, "password": "aaaaa-aaaaa"},
    ],
)
def test_wrong_credentials_get_one_answer(
    browser: TestClient, credentials: dict[str, str | None]
) -> None:
    user = _new_user(browser)
    body = {**credentials, "username": credentials["username"] or user["username"]}

    response = browser.post(LOGIN, json=body)

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"
    assert response.json()["message"] == "The username or the password is not correct."
    assert "set-cookie" not in response.headers


def test_a_login_ignores_case_and_space_around_the_credentials(
    browser: TestClient,
) -> None:
    user = _new_user(browser)

    response = browser.post(
        LOGIN,
        json={
            "username": f"  {user['username'].upper()} ",
            "password": f" {user['password'].upper()}\n",
        },
    )

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({"Sec-Fetch-Site": "same-origin"}, 200),
        ({"Sec-Fetch-Site": "none"}, 200),
        ({"Sec-Fetch-Site": "same-site"}, 403),
        ({"Sec-Fetch-Site": "cross-site"}, 403),
        # A proxy can change the host, so the browser header decides.
        (
            {
                "Sec-Fetch-Site": "same-origin",
                "Origin": "https://metis.example",
                "Host": "127.0.0.1:8001",
            },
            200,
        ),
        # An old browser sends only the origin.
        ({"Origin": "http://testserver"}, 200),
        ({"Origin": "https://walkthrough.example"}, 403),
    ],
)
def test_a_request_that_changes_data_must_come_from_a_page_of_the_server(
    browser: TestClient, headers: dict[str, str], status: int
) -> None:
    user = _new_user(browser)
    body = {"username": user["username"], "password": user["password"]}

    response = browser.post(LOGIN, json=body, headers=headers)

    assert response.status_code == status
    if status == 403:
        assert response.json()["code"] == "cross_site_request"


def test_with_login_off_each_route_is_open_and_no_user_is_current(
    client: TestClient,
) -> None:
    with client:
        assert client.get("/api/v1/targets").status_code == 200
        assert client.get(ME).json() == {"login": False, "user": None}
        assert client.post(LOGOUT).status_code == 204
        login = client.post(LOGIN, json={"username": "a", "password": "b"})
        assert login.status_code == 404
        assert client.get(USERS, headers=ADMIN).status_code == 404


def test_the_server_does_not_start_with_login_settings_that_are_wrong(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("METIS_ADMIN_TOKEN", "workshop-admin-token")
    with (
        pytest.raises(SettingsError, match="METIS_LOGIN=1"),
        TestClient(create_app(store=store)),
    ):
        pass

    monkeypatch.setenv("METIS_LOGIN", "yes")
    with pytest.raises(SettingsError, match="METIS_LOGIN must be 1 or 0"):
        Settings.from_env()


def test_a_user_account_without_a_password_hash_accepts_no_password() -> None:
    assert not verify_password("aaaaa-aaaaa", None)
    assert not verify_password("aaaaa-aaaaa", "not-a-hash")
    assert verify_password("aaaaa-aaaaa", hash_password("aaaaa-aaaaa"))
