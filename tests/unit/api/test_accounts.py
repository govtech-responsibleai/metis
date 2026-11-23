"""User accounts, admins, the two tokens, login sessions, and the guard of the other routes."""

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
from metis.api.routes.accounts import users_router
from metis.api.settings import Settings, SettingsError
from metis.api.store import Store
from metis.api.tables import experiments, login_sessions, targets, users
from metis.core import execution_layout, project_layout
from tests.fixtures.api.engine import FakeEngine, write_input_dir
from tests.fixtures.api.records import done_state, put_interview, ref, web_record

pytestmark = pytest.mark.usefixtures("no_demo_target")

JOIN = {"Authorization": "Bearer workshop-join-token"}
ADMIN_TOKEN = {"Authorization": "Bearer facilitator-admin-token"}
ADMIN_USERNAME = "workshop-lead"
ADMIN_PASSWORD = "Lead-Pass-For-The-Workshop"
USERS = "/api/v1/users"
LOGIN = "/api/v1/auth/login"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"

MakeClient = Callable[..., TestClient]


@pytest.fixture
def login_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """A server with login on, a join token, an admin token, and an admin in the environment."""
    monkeypatch.setenv("METIS_LOGIN", "1")
    monkeypatch.setenv("METIS_JOIN_TOKEN", "workshop-join-token")
    monkeypatch.setenv("METIS_ADMIN_TOKEN", "facilitator-admin-token")
    monkeypatch.setenv("METIS_ADMIN_USERNAME", ADMIN_USERNAME)
    monkeypatch.setenv("METIS_ADMIN_PASSWORD", ADMIN_PASSWORD)
    monkeypatch.delenv("HOST", raising=False)


@pytest.fixture
def browser(login_on: None, make_client: MakeClient) -> TestClient:
    """One browser of a server with login on. It keeps the cookies that it gets."""
    with make_client() as client:
        yield client


@pytest.fixture
def admin(login_on: None, make_client: MakeClient) -> TestClient:
    """A browser in a login session of the admin of the environment."""
    with make_client() as client:
        response = client.post(
            LOGIN, json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
        )
        assert response.status_code == 200
        yield client


def _new_user(client: TestClient) -> dict[str, str]:
    response = client.post(USERS, headers=JOIN)
    assert response.status_code == 201
    return response.json()


def _account(user: dict[str, str]) -> dict[str, object]:
    return {key: user[key] for key in ("id", "username", "created_at", "admin")}


def _log_in(client: TestClient, user: dict[str, str]):
    return client.post(
        LOGIN, json={"username": user["username"], "password": user["password"]}
    )


def test_the_join_token_makes_user_accounts_that_are_not_admins(
    browser: TestClient, store: Store
) -> None:
    first = _new_user(browser)
    second = browser.post(USERS, headers=JOIN, json={"admin": False}).json()

    assert re.fullmatch(r"[a-z]+-[a-z]+", first["username"])
    assert re.fullmatch(r"[a-hj-km-np-z2-9]{5}-[a-hj-km-np-z2-9]{5}", first["password"])
    assert first["admin"] is False
    assert second["admin"] is False
    with store.engine.connect() as connection:
        saved = connection.execute(select(users).where(users.c.id == first["id"])).one()
    assert first["password"] not in saved.password_hash
    assert verify_password(first["password"], saved.password_hash)


def test_the_join_token_cannot_make_an_admin(browser: TestClient) -> None:
    response = browser.post(USERS, headers=JOIN, json={"admin": True})

    assert response.status_code == 403
    assert response.json()["code"] == "admin_required"


def test_an_admin_lists_the_user_accounts_and_makes_an_admin(
    admin: TestClient, make_client: MakeClient
) -> None:
    participant = _new_user(admin)

    made = admin.post(USERS, json={"admin": True})

    assert made.status_code == 201
    second_admin = made.json()
    assert second_admin["admin"] is True
    listed = admin.get(USERS)
    assert listed.status_code == 200
    rows = listed.json()["users"]
    assert [row["username"] for row in rows] == [
        ADMIN_USERNAME,
        participant["username"],
        second_admin["username"],
    ]
    assert [row["admin"] for row in rows] == [True, False, True]
    assert all("password" not in row for row in rows)
    with make_client() as other:
        assert _log_in(other, second_admin).json()["user"]["admin"] is True
        assert other.get(USERS).status_code == 200


def test_a_taken_username_gets_another_name(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    names = iter(["calm-otter"] * 2 + ["calm-heron"] * 10)
    monkeypatch.setattr("metis.api.accounts.new_username", lambda: next(names))
    accounts = Accounts(store.engine)

    made = [accounts.create().account.username for _ in range(3)]

    assert made[:2] == ["calm-otter", "calm-heron"]
    assert re.fullmatch(r"calm-heron-\d{3}", made[2])


def _user_routes(username: str) -> tuple[tuple[str, str], ...]:
    return (
        ("get", USERS),
        ("post", USERS),
        ("post", f"{USERS}/{username}/password"),
        ("delete", f"{USERS}/{username}"),
    )


@pytest.mark.parametrize(
    "headers",
    [
        {"Authorization": "Bearer wrong-token"},
        {"Authorization": "Basic facilitator-admin-token"},
        {"Authorization": "facilitator-admin-token"},
        {"Authorization": ""},
    ],
)
def test_a_wrong_token_gets_no_user_route_even_with_the_cookie_of_an_admin(
    admin: TestClient, headers: dict[str, str]
) -> None:
    user = _new_user(admin)

    for method, path in _user_routes(user["username"]):
        response = admin.request(method, path, headers=headers)
        assert response.status_code == 401, path
        assert response.json()["code"] == "invalid_token"
        assert response.headers["WWW-Authenticate"] == "Bearer"
    assert [row["username"] for row in admin.get(USERS).json()["users"]] == [
        ADMIN_USERNAME,
        user["username"],
    ]
    assert _log_in(admin, user).status_code == 200


def test_the_admin_token_opens_each_user_route_with_no_login_session(
    login_on: None, make_client: MakeClient
) -> None:
    with make_client() as script:
        participant = script.post(USERS, headers=ADMIN_TOKEN)
        made_admin = script.post(USERS, headers=ADMIN_TOKEN, json={"admin": True})
        listed = script.get(USERS, headers=ADMIN_TOKEN)
        username = participant.json()["username"]
        reset = script.post(f"{USERS}/{username}/password", headers=ADMIN_TOKEN)
        deleted = script.delete(f"{USERS}/{username}", headers=ADMIN_TOKEN)

        assert script.cookies.get("metis_login") is None
        assert (participant.status_code, participant.json()["admin"]) == (201, False)
        assert (made_admin.status_code, made_admin.json()["admin"]) == (201, True)
        assert listed.status_code == 200
        assert [row["username"] for row in listed.json()["users"]] == [
            ADMIN_USERNAME,
            username,
            made_admin.json()["username"],
        ]
        assert reset.status_code == 200
        assert reset.json()["password"] != participant.json()["password"]
        assert deleted.status_code == 204
        remaining = script.get(USERS, headers=ADMIN_TOKEN).json()["users"]
        assert username not in [row["username"] for row in remaining]


def test_the_join_token_opens_no_user_route_but_the_join(browser: TestClient) -> None:
    user = _new_user(browser)

    for method, path in _user_routes(user["username"]):
        response = browser.request(
            method,
            path,
            headers=JOIN,
            json={"admin": True} if method == "post" else None,
        )
        assert response.status_code == 403, path
        assert response.json()["code"] == "admin_required"
    assert _log_in(browser, user).status_code == 200


def test_the_user_routes_need_the_login_session_of_an_admin(
    browser: TestClient,
) -> None:
    user = _new_user(browser)
    routes = _user_routes(user["username"])
    for method, path in routes:
        response = browser.request(method, path)
        assert response.status_code == 401, path
        assert response.json()["code"] == "login_required"

    assert _log_in(browser, user).status_code == 200

    for method, path in routes:
        response = browser.request(method, path)
        assert response.status_code == 403, path
        assert response.json()["code"] == "admin_required"


def test_each_user_route_refuses_a_request_with_no_credentials(
    browser: TestClient,
) -> None:
    for route in users_router.routes:
        for method in route.methods:
            path = route.path.replace("{username}", ADMIN_USERNAME)
            response = browser.request(method, path)
            assert response.status_code == 401, f"{method} {route.path}"
            assert response.json()["code"] == "login_required"


def test_the_api_description_names_the_credentials_of_the_user_routes(
    browser: TestClient,
) -> None:
    schema = browser.app.openapi()

    schemes = schema["components"]["securitySchemes"]
    assert schemes["JoinToken"]["scheme"] == "bearer"
    assert schemes["AdminToken"]["scheme"] == "bearer"
    assert schemes["LoginSession"] == {
        "type": "apiKey",
        "in": "cookie",
        "name": "metis_login",
        "description": "The cookie of a login session, which the login route sets.",
    }
    assert schema["paths"][USERS]["post"]["security"] == [
        {"JoinToken": []},
        {"LoginSession": []},
        {"AdminToken": []},
    ]
    for path, method in (
        (USERS, "get"),
        (f"{USERS}/{{username}}/password", "post"),
        (f"{USERS}/{{username}}", "delete"),
    ):
        assert schema["paths"][path][method]["security"] == [
            {"LoginSession": []},
            {"AdminToken": []},
        ]
    assert "security" not in schema["paths"][LOGIN]["post"]


def test_a_server_without_tokens_refuses_each_token_and_keeps_the_admin_routes(
    make_client: MakeClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("METIS_LOGIN", "1")
    monkeypatch.setenv("METIS_ADMIN_USERNAME", ADMIN_USERNAME)
    monkeypatch.setenv("METIS_ADMIN_PASSWORD", ADMIN_PASSWORD)
    with make_client() as client:
        for headers in (JOIN, ADMIN_TOKEN, {"Authorization": "Bearer "}):
            joined = client.post(USERS, headers=headers)
            assert joined.status_code == 401
            assert joined.json()["code"] == "invalid_token"

        body = {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
        assert client.post(LOGIN, json=body).status_code == 200
        assert client.post(USERS).status_code == 201
        assert len(client.get(USERS).json()["users"]) == 2


def test_the_tokens_do_not_open_the_other_routes(browser: TestClient) -> None:
    for headers in (JOIN, ADMIN_TOKEN):
        response = browser.get("/api/v1/targets", headers=headers)

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
    account = _account(user)
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
    assert {key: made[key] for key in ("id", "username")} == {
        key: user[key] for key in ("id", "username")
    }
    assert "password" not in made
    assert user["password"] not in path.read_text()
    assert datetime.fromisoformat(made["created_at"]) == datetime.fromisoformat(
        user["created_at"]
    )
    assert made["last_login_at"] is None
    assert stat.S_IMODE(path.stat().st_mode) == 0o600

    assert _log_in(browser, user).status_code == 200

    logged_in = json.loads(path.read_text())
    assert user["password"] not in path.read_text()
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
        assert client.get(USERS, headers=JOIN).status_code == 404
        assert client.post(USERS, headers=JOIN).status_code == 404


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"METIS_JOIN_TOKEN": "workshop-join-token"}, "METIS_LOGIN=1"),
        ({"METIS_ADMIN_TOKEN": "facilitator-admin-token"}, "METIS_LOGIN=1"),
        (
            {
                "METIS_LOGIN": "1",
                "METIS_JOIN_TOKEN": "one-token",
                "METIS_ADMIN_TOKEN": "one-token",
            },
            "are the same",
        ),
        (
            {
                "METIS_ADMIN_USERNAME": ADMIN_USERNAME,
                "METIS_ADMIN_PASSWORD": ADMIN_PASSWORD,
            },
            "METIS_LOGIN=1",
        ),
        (
            {"METIS_LOGIN": "1", "METIS_ADMIN_USERNAME": ADMIN_USERNAME},
            "set METIS_ADMIN_PASSWORD too",
        ),
        (
            {"METIS_LOGIN": "1", "METIS_ADMIN_PASSWORD": ADMIN_PASSWORD},
            "set METIS_ADMIN_USERNAME too",
        ),
        (
            {
                "METIS_LOGIN": "1",
                "METIS_ADMIN_USERNAME": "Workshop Lead",
                "METIS_ADMIN_PASSWORD": ADMIN_PASSWORD,
            },
            "lower-case letters, digits, and hyphens",
        ),
        ({"METIS_LOGIN": "yes"}, "METIS_LOGIN must be 1 or 0"),
    ],
)
def test_the_server_does_not_start_with_login_settings_that_are_wrong(
    store: Store,
    monkeypatch: pytest.MonkeyPatch,
    env: dict[str, str],
    message: str,
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with (
        pytest.raises(SettingsError, match=message),
        TestClient(create_app(store=store)),
    ):
        pass


def test_the_settings_repr_shows_no_login_secret(
    login_on: None,
) -> None:
    settings = Settings.from_env()

    assert "workshop-join-token" not in repr(settings)
    assert "facilitator-admin-token" not in repr(settings)
    assert ADMIN_PASSWORD not in repr(settings)


def test_the_admin_of_the_environment_logs_in_with_the_case_of_its_password(
    browser: TestClient, project_dir: Path
) -> None:
    wrong_case = browser.post(
        LOGIN, json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD.lower()}
    )
    assert wrong_case.status_code == 401

    response = browser.post(
        LOGIN,
        json={"username": ADMIN_USERNAME.upper(), "password": f" {ADMIN_PASSWORD} "},
    )

    assert response.status_code == 200
    user = response.json()["user"]
    assert user["username"] == ADMIN_USERNAME
    assert user["admin"] is True
    assert browser.get(ME).json()["user"]["admin"] is True
    user_file = project_dir / "users" / user["id"] / "user.json"
    assert ADMIN_PASSWORD not in user_file.read_text()


def test_a_new_password_in_the_environment_replaces_the_old_one_at_the_next_start(
    admin: TestClient, make_client: MakeClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_id = admin.get(ME).json()["user"]["id"]
    new_password = "A-New-Pass-For-The-Workshop"
    monkeypatch.setenv("METIS_ADMIN_PASSWORD", new_password)

    with make_client() as restarted:
        assert restarted.get(USERS).status_code == 401
        old = {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
        assert restarted.post(LOGIN, json=old).status_code == 401
        new = {"username": ADMIN_USERNAME, "password": new_password}
        logged_in = restarted.post(LOGIN, json=new)
        assert logged_in.status_code == 200
        assert logged_in.json()["user"]["id"] == first_id
        assert len(restarted.get(USERS).json()["users"]) == 1
    assert admin.get(ME).status_code == 401


def test_a_start_with_the_same_admin_keeps_its_login_sessions(
    admin: TestClient, make_client: MakeClient
) -> None:
    with make_client() as restarted:
        assert restarted.get("/health").status_code == 200

    assert admin.get(ME).status_code == 200


def test_the_environment_makes_an_existing_user_account_an_admin(
    store: Store, make_client: MakeClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    existing = Accounts(store.engine).create()
    monkeypatch.setenv("METIS_LOGIN", "1")
    monkeypatch.setenv("METIS_ADMIN_USERNAME", existing.account.username)
    monkeypatch.setenv("METIS_ADMIN_PASSWORD", ADMIN_PASSWORD)

    with make_client() as client:
        body = {"username": existing.account.username, "password": ADMIN_PASSWORD}
        response = client.post(LOGIN, json=body)

    assert response.json()["user"] == {
        "id": existing.account.id,
        "username": existing.account.username,
        "created_at": existing.account.created_at.isoformat().replace("+00:00", "Z"),
        "admin": True,
    }


def test_an_admin_resets_a_password_and_the_old_login_sessions_end(
    admin: TestClient, make_client: MakeClient
) -> None:
    user = _new_user(admin)
    with make_client() as participant:
        assert _log_in(participant, user).status_code == 200

        reset = admin.post(f"{USERS}/{user['username']}/password")

        assert reset.status_code == 200
        body = reset.json()
        assert _account(body) == _account(user)
        assert re.fullmatch(
            r"[a-hj-km-np-z2-9]{5}-[a-hj-km-np-z2-9]{5}", body["password"]
        )
        assert body["password"] != user["password"]
        assert participant.get(ME).status_code == 401
        assert _log_in(participant, user).status_code == 401
        assert (
            _log_in(participant, {**user, "password": body["password"]}).status_code
            == 200
        )


def test_a_reset_of_an_unknown_username_gets_not_found(admin: TestClient) -> None:
    response = admin.post(f"{USERS}/no-such-user/password")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_a_user_account_without_a_password_hash_accepts_no_password() -> None:
    assert not verify_password("aaaaa-aaaaa", None)
    assert not verify_password("aaaaa-aaaaa", "not-a-hash")
    assert verify_password("aaaaa-aaaaa", hash_password("aaaaa-aaaaa"))


def _save_interview(client: TestClient, target_id: str) -> None:
    """Save a done Interview with its one fixture file, as the web app does."""
    policy = b"policy"
    record = web_record(
        target_id, done_state(), fixtures=[ref("policy.pdf", policy, "application/pdf")]
    )
    files = [("files", ("policy.pdf", policy, "application/pdf"))]
    response = put_interview(client, record, files)
    assert response.status_code == 204, response.text


def _save_target(client: TestClient, target_id: str) -> None:
    """Save a done Interview and an Experiment row for it, in the folder of the user."""
    _save_interview(client, target_id)
    user_id = client.get(ME).json()["user"]["id"]
    experiment = "test-exp-20260101-000000"
    folder = client.app.state.project_dir / "users" / user_id
    (folder / project_layout.EXPERIMENTS / experiment).mkdir(parents=True)
    saved = client.put(
        f"/api/v1/engine/experiments/{experiment}",
        json={"target_id": target_id, "step": "simulate"},
    )
    assert saved.status_code == 200, saved.text


def test_an_admin_deletes_a_user_account_with_its_records_and_folder(
    admin: TestClient, make_client: MakeClient, project_dir: Path, store: Store
) -> None:
    deleted = _new_user(admin)
    kept = _new_user(admin)
    with make_client() as participant, make_client() as other:
        assert _log_in(participant, deleted).status_code == 200
        assert _log_in(other, kept).status_code == 200
        _save_target(participant, "20261114-101500-interview-k7mwp")
        _save_target(other, "20261114-101500-interview-x3r9t")

        response = admin.delete(f"{USERS}/{deleted['username']}")

        assert response.status_code == 204
        assert participant.get(ME).status_code == 401
        assert _log_in(participant, deleted).status_code == 401
        assert [row["username"] for row in admin.get(USERS).json()["users"]] == [
            ADMIN_USERNAME,
            kept["username"],
        ]
        assert not (project_dir / "users" / deleted["id"]).exists()
        with store.engine.connect() as connection:
            assert connection.execute(select(targets.c.user_id)).scalars().all() == [
                kept["id"]
            ]
            assert connection.execute(
                select(experiments.c.target_id)
            ).scalars().all() == ["20261114-101500-interview-x3r9t"]
        assert other.get("/api/v1/targets").json()["targets"][0]["id"] == (
            "20261114-101500-interview-x3r9t"
        )
        assert (project_dir / "users" / kept["id"] / "user.json").is_file()


def test_a_delete_of_an_unknown_username_gets_not_found(admin: TestClient) -> None:
    response = admin.delete(f"{USERS}/no-such-user")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_an_admin_cannot_delete_its_own_user_account(
    admin: TestClient, make_client: MakeClient
) -> None:
    second_admin = admin.post(USERS, json={"admin": True}).json()
    with make_client() as client:
        assert _log_in(client, second_admin).status_code == 200

        response = client.delete(f"{USERS}/{second_admin['username']}")

        assert response.status_code == 409
        assert response.json()["code"] == "cannot_delete_self"
        assert client.get(ME).status_code == 200


def test_the_admin_of_the_environment_cannot_be_deleted(
    admin: TestClient, make_client: MakeClient
) -> None:
    second_admin = admin.post(USERS, json={"admin": True}).json()
    with make_client() as client:
        assert _log_in(client, second_admin).status_code == 200

        response = client.delete(f"{USERS}/{ADMIN_USERNAME}")

    assert response.status_code == 409
    assert response.json()["code"] == "environment_admin"
    assert admin.get(ME).status_code == 200
    by_token = admin.delete(f"{USERS}/{ADMIN_USERNAME}", headers=ADMIN_TOKEN)
    assert by_token.json()["code"] == "environment_admin"


def test_a_user_account_with_a_live_engine_run_cannot_be_deleted(
    login_on: None,
    make_engine_client: Callable[..., TestClient],
    fake_engine: FakeEngine,
    project_dir: Path,
) -> None:
    lead = make_engine_client()
    body = {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
    assert lead.post(LOGIN, json=body).status_code == 200
    user = _new_user(lead)
    participant = TestClient(lead.app)
    assert _log_in(participant, user).status_code == 200
    experiment = "test-exp-20260101-000000"
    write_input_dir(
        project_dir
        / "users"
        / user["id"]
        / project_layout.EXPERIMENTS
        / experiment
        / execution_layout.SPECIFICATION_DIR
    )
    fake_engine.mode = "hold"
    started = participant.post(f"/api/v1/engine/simulate/{experiment}/resume")
    assert started.status_code == 202

    response = lead.delete(f"{USERS}/{user['username']}")

    assert response.status_code == 409
    assert response.json()["code"] == "run_in_progress"
    assert participant.get(ME).status_code == 200
    assert (project_dir / "users" / user["id"]).is_dir()


def test_a_user_account_with_a_queued_engine_run_cannot_be_deleted(
    login_on: None,
    make_engine_client: Callable[..., TestClient],
    fake_engine: FakeEngine,
    project_dir: Path,
) -> None:
    # One slot, which a run of another user account holds. The participant's start waits in
    # the queue, and would start later in the folder of the account, so it counts as live.
    lead = make_engine_client(max_runs=1)
    body = {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
    assert lead.post(LOGIN, json=body).status_code == 200
    holder, user = _new_user(lead), _new_user(lead)
    clients = []
    experiment = "test-exp-20260101-000000"
    for account in (holder, user):
        client = TestClient(lead.app)
        assert _log_in(client, account).status_code == 200
        write_input_dir(
            project_dir
            / "users"
            / account["id"]
            / project_layout.EXPERIMENTS
            / experiment
            / execution_layout.SPECIFICATION_DIR
        )
        clients.append(client)
    fake_engine.mode = "hold"
    holding, participant = clients
    assert (
        holding.post(f"/api/v1/engine/simulate/{experiment}/resume").status_code == 202
    )
    assert (
        participant.post(f"/api/v1/engine/simulate/{experiment}/resume").status_code
        == 202
    )
    assert participant.get(f"/api/v1/engine/{experiment}").json()["status"] == "queued"

    response = lead.delete(f"{USERS}/{user['username']}")

    assert response.status_code == 409
    assert response.json()["code"] == "run_in_progress"
    assert (project_dir / "users" / user["id"]).is_dir()


def test_the_local_user_account_cannot_be_deleted(
    make_client: MakeClient, monkeypatch: pytest.MonkeyPatch, project_dir: Path
) -> None:
    with make_client() as laptop:
        _save_interview(laptop, "20261114-101500-interview-k7mwp")
    monkeypatch.setenv("METIS_LOGIN", "1")
    monkeypatch.setenv("METIS_ADMIN_USERNAME", ADMIN_USERNAME)
    monkeypatch.setenv("METIS_ADMIN_PASSWORD", ADMIN_PASSWORD)
    with make_client() as client:
        body = {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
        assert client.post(LOGIN, json=body).status_code == 200

        response = client.delete(f"{USERS}/local")

    assert response.status_code == 409
    assert response.json()["code"] == "local_account"
    assert (project_dir / "evaluations" / "interviews").is_dir()
