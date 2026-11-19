"""The workshop variables: `METIS_WORKSHOP_ENV` and `GET /api/v1/workshop/env`."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from metis.api.main import create_app
from metis.api.settings import SettingsError, login_from_env
from metis.api.store import Store

pytestmark = pytest.mark.usefixtures("no_demo_target")

JOIN = {"Authorization": "Bearer workshop-join-token"}
WORKSHOP_ENV = "/api/v1/workshop/env"

MakeClient = Callable[..., TestClient]


@pytest.fixture
def login_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("METIS_LOGIN", "1")
    monkeypatch.setenv("METIS_JOIN_TOKEN", "workshop-join-token")
    monkeypatch.delenv("HOST", raising=False)


def _logged_in(client: TestClient) -> TestClient:
    user = client.post("/api/v1/users", headers=JOIN).json()
    response = client.post(
        "/api/v1/auth/login",
        json={"username": user["username"], "password": user["password"]},
    )
    assert response.status_code == 200
    return client


def test_the_setting_keeps_the_names_in_their_order(
    login_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "METIS_WORKSHOP_ENV", " LANGFUSE_BASE_URL , ,LANGFUSE_PUBLIC_KEY,"
    )

    assert login_from_env().workshop_env == ("LANGFUSE_BASE_URL", "LANGFUSE_PUBLIC_KEY")


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"METIS_WORKSHOP_ENV": "LANGFUSE_PUBLIC_KEY"}, "login is off"),
        (
            {"METIS_LOGIN": "1", "METIS_WORKSHOP_ENV": "LANGFUSE_PUBLIC_KEY,BASE-URL"},
            "'BASE-URL', which is not a variable name",
        ),
        (
            {
                "METIS_LOGIN": "1",
                "METIS_WORKSHOP_ENV": "LANGFUSE_PUBLIC_KEY,METIS_JOIN_TOKEN",
            },
            "'METIS_JOIN_TOKEN'. A METIS_ variable",
        ),
        (
            {
                "METIS_LOGIN": "1",
                "METIS_WORKSHOP_ENV": "LANGFUSE_PUBLIC_KEY,LANGFUSE_PUBLIC_KEY",
            },
            "more than one time",
        ),
    ],
)
def test_the_server_does_not_start_with_a_wrong_workshop_setting(
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


def test_a_user_reads_the_variables_that_have_a_value_in_the_order_of_the_setting(
    login_on: None, make_client: MakeClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "METIS_WORKSHOP_ENV",
        "LANGFUSE_SECRET_KEY,LANGFUSE_UNSET,LANGFUSE_EMPTY,LANGFUSE_PUBLIC_KEY",
    )
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-1")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-1")
    monkeypatch.setenv("LANGFUSE_EMPTY", "")
    monkeypatch.delenv("LANGFUSE_UNSET", raising=False)

    with make_client() as client:
        assert client.get(WORKSHOP_ENV).json()["code"] == "login_required"
        response = _logged_in(client).get(WORKSHOP_ENV)

    assert response.status_code == 200
    assert response.json() == {
        "variables": [
            {"name": "LANGFUSE_SECRET_KEY", "value": "sk-lf-1"},
            {"name": "LANGFUSE_PUBLIC_KEY", "value": "pk-lf-1"},
        ]
    }


def test_a_server_without_the_setting_gives_no_variables(
    login_on: None, make_client: MakeClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("METIS_WORKSHOP_ENV", raising=False)

    with make_client() as client:
        response = _logged_in(client).get(WORKSHOP_ENV)

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
