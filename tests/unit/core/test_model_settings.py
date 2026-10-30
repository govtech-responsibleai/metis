"""Model settings for each LLM role and the one `.env` search."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from metis.core.model_settings import (
    ENV_FILE_VAR,
    MODEL_GUIDE,
    ModelRole,
    ModelSettingsError,
    check_roles,
    find_env_file,
    load_env,
    resolve_role,
)


def test_a_role_uses_the_shared_gateway_unless_it_sets_its_own_key_or_url() -> None:
    env = {"OPENAI_API_KEY": "shared", "OPENAI_BASE_URL": "https://shared/v1"}
    for role in ModelRole:
        settings = resolve_role(role, env)
        assert (settings.api_key, settings.base_url) == ("shared", "https://shared/v1")

    env["JUDGE_BASE_URL"] = "https://judge/v1"
    judge = resolve_role(ModelRole.JUDGE, env)
    assert (judge.api_key, judge.base_url) == ("shared", "https://judge/v1")


def test_the_runner_agent_follows_the_user_agent_for_its_key_and_model() -> None:
    env = {
        "OPENAI_API_KEY": "shared",
        "USER_AGENT_API_KEY": "ua",
        "USER_AGENT_MODEL": "m",
    }
    runner = resolve_role(ModelRole.RUNNER_AGENT, env)
    assert (runner.api_key, runner.model) == ("ua", "m")

    env |= {"RUNNER_AGENT_API_KEY": "ra", "RUNNER_AGENT_MODEL": "r"}
    runner = resolve_role(ModelRole.RUNNER_AGENT, env)
    assert (runner.api_key, runner.model) == ("ra", "r")


def test_the_model_comes_from_the_first_place_that_has_a_value() -> None:
    env = {"DEFAULT_MODEL": "team", "JUDGE_MODEL": "judge"}
    cases = [
        (resolve_role(ModelRole.JUDGE, env, "spec"), "spec", "specification.yaml"),
        (resolve_role(ModelRole.JUDGE, env), "judge", "JUDGE_MODEL"),
        (resolve_role(ModelRole.USER_AGENT, env), "team", "DEFAULT_MODEL"),
        (resolve_role(ModelRole.USER_AGENT, {}), "gpt-6-luna", "built-in default"),
    ]
    for settings, model, source in cases:
        assert (settings.model, settings.source) == (model, source)


def test_embeddings_use_their_own_default_and_not_the_default_model() -> None:
    env = {"DEFAULT_MODEL": "team"}
    assert resolve_role(ModelRole.EMBEDDINGS, env).model == "text-embedding-3-large"
    env["EMBEDDING_MODEL"] = "custom-embedding"
    assert resolve_role(ModelRole.EMBEDDINGS, env).model == "custom-embedding"


def test_an_empty_value_counts_as_unset() -> None:
    env = {
        "OPENAI_API_KEY": "shared",
        "INTERVIEW_API_KEY": "",
        "INTERVIEW_MODEL": "",
        "OPENAI_BASE_URL": "",
    }
    settings = resolve_role(ModelRole.INTERVIEW, env)
    assert (settings.api_key, settings.base_url, settings.model) == (
        "shared",
        None,
        "gpt-6-luna",
    )


def test_the_missing_settings_error_names_what_to_set_and_no_secret() -> None:
    env = {"JUDGE_BASE_URL": "https://secret/v1"}
    with pytest.raises(ModelSettingsError) as exc:
        check_roles("metis engine evaluate", [ModelRole.JUDGE], env, Path("/p/.env"))
    message = str(exc.value)
    for expected in (
        "metis engine evaluate",
        "JUDGE_API_KEY or OPENAI_API_KEY",
        "/p/.env",
    ):
        assert expected in message
    assert MODEL_GUIDE in message
    assert "secret" not in message

    secret = {"OPENAI_API_KEY": "sk-secret", "OPENAI_BASE_URL": "https://secret/v1"}
    assert "secret" not in repr(resolve_role(ModelRole.JUDGE, secret))

    with pytest.raises(ModelSettingsError, match="No .env file was found"):
        check_roles("metis wizard init", [ModelRole.INTERVIEW], {}, None)


def test_the_env_search_goes_up_to_the_project_root_and_never_above(
    tmp_path: Path,
) -> None:
    (tmp_path / ".env").write_text("X=outside\n")
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    sub = root / "a" / "b"
    sub.mkdir(parents=True)

    assert find_env_file(sub, {}) is None
    (root / ".env").write_text("X=root\n")
    assert find_env_file(sub, {}) == root.resolve() / ".env"
    (sub / ".env").write_text("X=sub\n")
    assert find_env_file(sub, {}) == sub.resolve() / ".env"

    plain = tmp_path / "plain"
    plain.mkdir()
    assert find_env_file(plain, {}) is None


def test_metis_env_file_and_exported_values_win(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / ".env").write_text("METIS_TEST_A=file\nMETIS_TEST_B=file\n")
    named = tmp_path / "custom.env"
    assert find_env_file(root, {ENV_FILE_VAR: str(named)}) == named

    monkeypatch.delenv(ENV_FILE_VAR, raising=False)
    monkeypatch.setenv("METIS_TEST_A", "exported")
    monkeypatch.delenv("METIS_TEST_B", raising=False)
    assert load_env(root) == root.resolve() / ".env"
    assert os.environ["METIS_TEST_A"] == "exported"
    assert os.environ["METIS_TEST_B"] == "file"
    monkeypatch.delenv("METIS_TEST_B")

    monkeypatch.setenv(ENV_FILE_VAR, str(tmp_path / "absent.env"))
    with pytest.raises(ModelSettingsError, match=ENV_FILE_VAR):
        load_env(tmp_path)
