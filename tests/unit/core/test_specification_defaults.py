"""The models that a Specification records: experiment defaults and the Test Case override."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from metis.core.specification import Specification


def _document(**extra: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "id": "exp",
        "target": {"name": "T", "users": "U", "description": "D"},
        **extra,
    }


def test_defaults_are_empty_when_absent() -> None:
    spec = Specification.model_validate(_document())
    assert spec.experiment.defaults.judge_model is None


def test_judge_model_is_read_from_the_flat_document() -> None:
    spec = Specification.model_validate(
        _document(defaults={"judge_model": "gpt-4o-mini"})
    )
    assert spec.experiment.defaults.judge_model == "gpt-4o-mini"


def test_judge_model_round_trips() -> None:
    spec = Specification.model_validate(
        _document(defaults={"judge_model": "gpt-4o-mini"})
    )
    dumped = spec.model_dump(mode="json")
    assert dumped["defaults"] == {"judge_model": "gpt-4o-mini"}
    assert Specification.model_validate(dumped) == spec


def test_empty_defaults_are_not_written() -> None:
    """Specs without defaults serialise exactly as before, so compiled YAML does not churn."""
    dumped = Specification.model_validate(_document()).model_dump(mode="json")
    assert "defaults" not in dumped


def test_defaults_come_after_runner_factory_ref() -> None:
    dumped = Specification.model_validate(
        _document(defaults={"judge_model": "m"})
    ).model_dump(mode="json")
    keys = list(dumped)
    assert (
        keys.index("runner_factory_ref") < keys.index("defaults") < keys.index("target")
    )


def test_experiment_dump_omits_empty_defaults() -> None:
    """Callers dump an Experiment directly and splice it into documents; keep it unchanged."""
    from metis.core.experiment import Experiment, ExperimentDefaults

    assert "defaults" not in Experiment(id="e").model_dump()
    assert Experiment(
        id="e", defaults=ExperimentDefaults(judge_model="m")
    ).model_dump()["defaults"] == {"judge_model": "m"}


def test_blank_default_judge_model_is_rejected() -> None:
    with pytest.raises(ValidationError, match="judge_model"):
        Specification.model_validate(_document(defaults={"judge_model": ""}))


def test_misspelt_default_is_rejected() -> None:
    with pytest.raises(ValidationError, match="judge_modle"):
        Specification.model_validate(_document(defaults={"judge_modle": "m"}))


_TASKS = {
    "personas": [{"id": "p", "name": "P", "description": "d"}],
    "scenarios": [{"id": "s", "name": "S", "description": "d"}],
}


def _task(**extra: Any) -> dict[str, Any]:
    return {"id": "t", "scenario_ref": "s", "persona_ref": "p", **extra}


def test_each_model_field_round_trips_and_a_blank_value_is_rejected() -> None:
    defaults = {"user_agent_model": "ua", "runner_agent_model": "ra"}
    spec = Specification.model_validate(
        _document(defaults=defaults, tasks=[_task(user_agent_model="t")], **_TASKS)
    )
    dumped = spec.model_dump(mode="json")
    assert dumped["defaults"] == defaults
    assert dumped["tasks"][0]["user_agent_model"] == "t"
    assert Specification.model_validate(dumped) == spec

    for key in defaults:
        with pytest.raises(ValidationError, match=key):
            Specification.model_validate(_document(defaults={key: ""}))
    with pytest.raises(ValidationError, match="user_agent_model"):
        Specification.model_validate(
            _document(tasks=[_task(user_agent_model="")], **_TASKS)
        )


def test_unset_models_are_not_written() -> None:
    dumped = Specification.model_validate(
        _document(defaults={"judge_model": "j"}, tasks=[_task()], **_TASKS)
    ).model_dump(mode="json")
    assert dumped["defaults"] == {"judge_model": "j"}
    assert "user_agent_model" not in dumped["tasks"][0]
