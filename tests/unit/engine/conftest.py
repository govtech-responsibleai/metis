"""Shared fixtures for engine unit tests."""

from __future__ import annotations

import pytest
import structlog


@pytest.fixture(autouse=True)
def reset_structlog() -> None:
    """Reset structlog to its built-in defaults before each test.

    Tests that invoke CLI commands via Typer's CliRunner call
    configure_logging(), which reconfigures the global structlog state
    (including the logger factory's file handle).  When the CliRunner context
    exits, that file handle may be closed.  Subsequent tests that log at a
    level that is *not* filtered out (e.g. ERROR / exception) then fail with
    "I/O operation on closed file".

    This autouse fixture resets structlog to its built-in defaults before
    every test so that each test starts from a clean logging state.
    """
    structlog.reset_defaults()


_MODEL_VARS = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "USER_AGENT_API_KEY",
    "USER_AGENT_BASE_URL",
    "USER_AGENT_MODEL",
    "RUNNER_AGENT_API_KEY",
    "RUNNER_AGENT_BASE_URL",
    "RUNNER_AGENT_MODEL",
    "JUDGE_API_KEY",
    "JUDGE_BASE_URL",
    "JUDGE_MODEL",
    "METIS_INTERNAL_LANGFUSE_PUBLIC_KEY",
    "METIS_INTERNAL_LANGFUSE_SECRET_KEY",
    "METIS_INTERNAL_LANGFUSE_BASE_URL",
)


@pytest.fixture(autouse=True)
def model_settings(monkeypatch: pytest.MonkeyPatch, tmp_path_factory) -> None:
    """Give each test a fake shared key and an empty `.env`.

    No test reads a developer's real `.env` or keys. A test that checks a missing key
    deletes ``OPENAI_API_KEY`` itself. No test makes a real model call.
    """
    for name in _MODEL_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    env_file = tmp_path_factory.mktemp("env") / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("METIS_ENV_FILE", str(env_file))
