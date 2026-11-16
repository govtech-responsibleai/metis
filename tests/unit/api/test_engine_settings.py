"""The settings of the engine routes: request defaults, request maximums, and the stop limit."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from metis.api.main import create_app
from metis.api.settings import EngineSettings, InvalidSettingError


def test_the_defaults_match_the_engine_cli() -> None:
    settings = EngineSettings.from_env({})

    assert settings == EngineSettings(
        concurrency=1,
        max_concurrency=8,
        langfuse_timeout=90,
        max_langfuse_timeout=600,
        stop_timeout=30,
    )


def test_each_setting_comes_from_its_variable() -> None:
    settings = EngineSettings.from_env(
        {
            "METIS_API_ENGINE_CONCURRENCY": "2",
            "METIS_API_ENGINE_MAX_CONCURRENCY": "4",
            "METIS_API_LANGFUSE_TIMEOUT": "120",
            "METIS_API_MAX_LANGFUSE_TIMEOUT": "300",
            "METIS_API_STOP_TIMEOUT": " 5 ",
        }
    )

    assert settings == EngineSettings(
        concurrency=2,
        max_concurrency=4,
        langfuse_timeout=120,
        max_langfuse_timeout=300,
        stop_timeout=5,
    )


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "abc", ""])
def test_a_value_that_is_not_a_whole_number_of_one_or_more_is_refused(
    value: str,
) -> None:
    with pytest.raises(InvalidSettingError, match="METIS_API_STOP_TIMEOUT"):
        EngineSettings.from_env({"METIS_API_STOP_TIMEOUT": value})


@pytest.mark.parametrize(
    ("variables", "name"),
    [
        (
            {
                "METIS_API_ENGINE_CONCURRENCY": "9",
                "METIS_API_ENGINE_MAX_CONCURRENCY": "8",
            },
            "METIS_API_ENGINE_CONCURRENCY",
        ),
        (
            {"METIS_API_LANGFUSE_TIMEOUT": "700"},
            "METIS_API_LANGFUSE_TIMEOUT",
        ),
    ],
)
def test_a_default_above_its_maximum_is_refused(
    variables: dict[str, str], name: str
) -> None:
    with pytest.raises(InvalidSettingError, match=name):
        EngineSettings.from_env(variables)


def test_a_setting_that_is_not_valid_stops_the_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("METIS_API_ENGINE_CONCURRENCY", "many")

    with pytest.raises(InvalidSettingError), TestClient(create_app()):
        pass
