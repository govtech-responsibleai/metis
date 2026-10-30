"""The API model settings: it starts without keys and reports each role through `/models`."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from metis.api.main import create_app
from metis.api.routes.models import model_statuses
from metis.api.settings import Settings, SettingsError, build_dependencies
from metis.core.model_settings import ModelRole

_ROLE_KEYS = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "INTERVIEW_API_KEY",
    "EMBEDDING_API_KEY",
    "USER_AGENT_API_KEY",
    "RUNNER_AGENT_API_KEY",
    "JUDGE_API_KEY",
)


@pytest.fixture
def no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ROLE_KEYS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("METIS_ENV_FILE", "")


def test_the_app_starts_without_keys_and_the_interview_needs_only_its_own_key(
    no_keys: None,
) -> None:
    start = {
        "description": "A research assistant",
        "known_capability_ids": [],
        "capability_confidence": "low",
    }
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200
        response = client.post("/api/v1/wizard/interview/start", json=start)

    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "model_unavailable"
    assert "INTERVIEW_API_KEY or OPENAI_API_KEY" in body["message"]
    assert Settings(env={"INTERVIEW_API_KEY": "k"}).missing_message() is None
    with pytest.raises(SettingsError, match="INTERVIEW_API_KEY or OPENAI_API_KEY"):
        build_dependencies(Settings(env={"JUDGE_API_KEY": "k"}))


def test_the_connection_check_works_without_model_keys(no_keys: None) -> None:
    binding = {
        "schema_version": 1,
        "identity": {"name": "Billing bot"},
        "transport": "http",
        "spec_url": "",
    }
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/wizard/connection/check", json={"binding": binding}
        )

    assert response.status_code == 200
    assert response.json()["errors"][0]["loc"] == ["spec_url"]


def test_models_reports_each_role_and_its_missing_variables_without_secrets(
    monkeypatch: pytest.MonkeyPatch, no_keys: None
) -> None:
    monkeypatch.setenv("INTERVIEW_API_KEY", "sk-secret")
    monkeypatch.setenv("INTERVIEW_BASE_URL", "https://secret.example/v1")
    monkeypatch.setenv("JUDGE_MODEL", "judge-model")

    with TestClient(create_app(interview_handler=lambda _: None)) as client:  # type: ignore[arg-type]
        response = client.get("/api/v1/models")

    assert "secret" not in response.text
    rows = {row["role"]: row for row in response.json()}
    assert list(rows) == [
        "interview",
        "embeddings",
        "user_agent",
        "runner_agent",
        "judge",
    ]
    assert rows["interview"]["configured"] is True
    assert rows["judge"] == {
        "role": "judge",
        "label": "Judge",
        "model": "judge-model",
        "source": "JUDGE_MODEL",
        "configured": False,
        "affects_scores": True,
        "missing_vars": ["JUDGE_API_KEY", "OPENAI_API_KEY"],
    }


def test_the_settings_repr_shows_no_environment_value() -> None:
    settings = Settings(env={"OPENAI_API_KEY": "sk-secret"})

    assert "sk-secret" not in repr(settings)


def test_the_runner_agent_follows_the_user_agent_model_as_in_the_engine() -> None:
    settings = Settings(env={"USER_AGENT_MODEL": "ua-model", "DEFAULT_MODEL": "other"})

    assert settings.role(ModelRole.RUNNER_AGENT).model == "ua-model"
    rows = {row.role: row for row in model_statuses(settings)}
    assert rows[ModelRole.RUNNER_AGENT].model == "ua-model"
    assert rows[ModelRole.RUNNER_AGENT].source == "user agent model"
    explicit = Settings(env={"USER_AGENT_MODEL": "ua", "RUNNER_AGENT_MODEL": "ra"})
    assert explicit.role(ModelRole.RUNNER_AGENT).model == "ra"
