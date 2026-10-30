"""Check that Wizard evaluation cases can be used and reviewed offline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from metis.core.specification import Specification
from metis.testbed.use_cases import load_case

EVALS_ROOT = Path(__file__).resolve().parents[3] / "packages/testbed/wizard/cases"
CONFIG = yaml.safe_load((EVALS_ROOT / "config.yaml").read_text())


def _read(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def _file(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    assert path.is_relative_to(root.resolve()), relative
    assert path.is_file(), relative
    return path


@pytest.mark.parametrize("case_path", CONFIG["cases"])
def test_use_case_has_inputs_documentation_and_valid_reference(case_path: str) -> None:
    case, root = load_case(EVALS_ROOT, case_path)
    assert (root / "README.md").read_text().strip()
    assert (root / "inputs").is_dir()
    assert case.inputs
    assert "inputs/prompt.md" in case.inputs
    for relative in case.inputs:
        assert _file(root, relative).stat().st_size > 0
    spec = Specification.model_validate(_read(_file(root, case.expected_output)))
    behaviours = {b.id: b for b in spec.behaviours()}
    assert len(behaviours) == len(spec.behaviours())
    criteria = [c for b in spec.behaviours() for c in b.criteria]
    criterion_ids = {c.id for c in criteria}
    assert criteria
    assert len(criterion_ids) == len(criteria)
    scenarios = {s.id for s in spec.scenarios}
    personas = {p.id for p in spec.personas}
    assert len(scenarios) == len(spec.scenarios)
    assert len(personas) == len(spec.personas)
    for entry in [*spec.personas, *spec.scenarios]:
        assert all(
            not isinstance(value, (dict, list)) for value in entry.metadata.values()
        )
    assert [t.id for t in spec.tasks] == [
        f"TC-{number:03d}" for number in range(1, len(spec.tasks) + 1)
    ]
    for task in spec.tasks:
        assert task.scenario_ref in scenarios
        assert task.persona_ref in personas
        assert task.num_trials > 0
        assert task.behaviour_refs
        for fixture in task.fixtures:
            assert _file(root, f"outputs/fixtures/{fixture}").stat().st_size > 0
        for ref in task.behaviour_refs:
            assert ref in behaviours
            assert behaviours[ref].measured
            assert behaviours[ref].criteria


def test_enterprise_prelaunch_tasks_cover_the_selected_behaviours() -> None:
    root = EVALS_ROOT / "enterprise-ai-assistant"
    spec = Specification.model_validate(_read(root / "outputs/specification.yaml"))
    selected_by_task = {
        "TC-001": {"EB-CONV-1", "EB-ENTERPRISE-1"},
        "TC-002": {"EB-CONV-1", "EB-ENTERPRISE-1"},
        "TC-003": {
            "EB-CONV-1",
            "EB-ENTERPRISE-1",
            "EB-COMMS-2",
        },
        "TC-004": {"EB-CONV-1", "EB-ARTEFACT-1"},
        "TC-005": {
            "EB-CONV-1",
            "EB-COMMS-2",
            "EB-ARTEFACT-1",
        },
    }
    assert {
        task.id: set(task.behaviour_refs) for task in spec.tasks
    } == selected_by_task
    assert {
        behaviour.id for behaviour in spec.behaviours() if behaviour.measured
    } == set().union(*selected_by_task.values())


def test_use_case_discovers_prompt_and_supporting_documents(tmp_path: Path) -> None:
    root = tmp_path / "example"
    (root / "inputs/nested").mkdir(parents=True)
    (root / "outputs").mkdir()
    (root / "inputs/.gitkeep").touch()
    (root / "inputs/prompt.md").write_text("Product brief")
    (root / "inputs/nested/settings.yaml").write_text("language: en")
    (root / "outputs/specification.yaml").write_text("Reference only")
    (root / "README.md").write_text("Review notes")

    case, folder = load_case(tmp_path, "example")

    assert folder == root
    assert case.inputs == ["inputs/nested/settings.yaml", "inputs/prompt.md"]
    assert case.expected_output == "outputs/specification.yaml"
