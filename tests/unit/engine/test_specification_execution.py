"""Tests for the executable specification contract."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from metis.engine.simulation.types import Specification


def _base_experiment(**overrides: object) -> dict:
    base: dict = {
        "schema_version": 1,
        "id": "test",
        "runner_factory_ref": "tests.unit.engine.test_runner_ref.StubRunnerFactory",
        "personas": [{"id": "p1", "description": "persona", "name": "p1"}],
        "scenarios": [{"id": "s1", "description": "sc", "name": "s1"}],
        "target": {
            "name": "Test target",
            "users": "Test users",
            "description": "Test target",
        },
        "tasks": [
            {
                "id": "TC-001",
                "scenario_ref": "s1",
                "persona_ref": "p1",
                "fixtures": [],
                "num_trials": 1,
                "behaviour_refs": ["EB-1"],
            }
        ],
        "features": [
            {
                "id": "F-1",
                "name": "Responses",
                "description": "Responses",
                "behaviours": [
                    {
                        "id": "EB-1",
                        "name": "Respond",
                        "description": "Respond correctly",
                        "measured": True,
                        "criteria": [
                            {
                                "id": "AC-1-1",
                                "name": "Check 1",
                                "description": "Given a request, when the agent responds, then the requirement is met.",
                                "grader_fqn": "tests.unit.engine.graders_for_tests.FixedScoreGrader",
                                "grader_args": {},
                            }
                        ],
                    }
                ],
            }
        ],
    }
    base.update(overrides)
    return base


class TestSpecificationExecution:
    def test_loads(self) -> None:
        exp = Specification.model_validate(_base_experiment())
        assert exp.schema_version == 1

    def test_wrong_version_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Unsupported schema_version"):
            Specification.model_validate(_base_experiment(schema_version=99))

    @pytest.mark.parametrize("key", ["schema_version", "id", "runner_factory_ref"])
    def test_header_key_required(self, key: str) -> None:
        data = _base_experiment()
        del data[key]
        with pytest.raises(ValidationError, match=f"needs these keys: {key}"):
            Specification.model_validate(data)

    def test_runner_factory_ref_empty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Specification.model_validate(_base_experiment(runner_factory_ref=""))

    def test_runner_factory_ref_invalid_fqn_rejected(self) -> None:
        with pytest.raises(ValidationError, match="No module named"):
            Specification.model_validate(
                _base_experiment(runner_factory_ref="nonexistent.Factory")
            )

    def test_runner_factory_ref_valid_fqn_accepted(self) -> None:
        exp = Specification.model_validate(_base_experiment())
        assert (
            exp.runner_factory_ref
            == "tests.unit.engine.test_runner_ref.StubRunnerFactory"
        )

    def test_simple_example_loads(self, repo_root: Path) -> None:
        """The toy app example must load for execution."""
        path = (
            repo_root
            / "packages/engine/examples/http-agentic_eval_toyapp-1/specification.yaml"
        )
        specification = Specification.model_validate(yaml.safe_load(path.read_text()))
        assert specification.id == "toyapp-http-simple"
