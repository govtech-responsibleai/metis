"""The process setup of the engine library functions, which the API runs once at startup."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from metis.api import engine_runs
from metis.api.main import create_app

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

SETUP = engine_runs.setup_engine_process
"""The real setup. The ``no_engine_setup`` fixture replaces it in the module for each test."""


def test_the_setup_loads_env_registers_tracing_and_sets_up_logging_in_that_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        "metis.core.model_settings.load_env",
        lambda: calls.append(("load_env", {})),
    )
    monkeypatch.setattr(
        "metis.engine.tracing.tracing_key",
        lambda: calls.append(("tracing_key", {})) or "key",
    )
    monkeypatch.setattr(
        "metis.core.logging.configure_logging",
        lambda **options: calls.append(("configure_logging", options)),
    )
    real_setup = SETUP.__wrapped__

    real_setup()

    assert calls == [("load_env", {}), ("tracing_key", {}), ("configure_logging", {})]


def test_the_process_setup_runs_one_time() -> None:
    assert hasattr(SETUP, "cache_info")


def test_an_api_test_app_does_not_load_the_env_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / "leak.env"
    env_file.write_text("METIS_TEST_LEAK=1\n")
    monkeypatch.setenv("METIS_ENV_FILE", str(env_file))
    monkeypatch.delenv("METIS_TEST_LEAK", raising=False)

    with TestClient(create_app()):
        pass

    assert "METIS_TEST_LEAK" not in os.environ
