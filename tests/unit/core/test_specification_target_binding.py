"""The specification's optional path to a target binding file."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from metis.core.specification import Specification

BASE = {
    "schema_version": 1,
    "id": "x",
    "runner_factory_ref": "pkg.Factory",
    "target": {"name": "T", "users": "U", "description": "D"},
}


def test_target_binding_defaults_to_none_and_is_not_written():
    spec = Specification.model_validate(BASE)
    assert spec.target_binding is None
    assert "target_binding" not in spec.model_dump(mode="json")


def test_target_binding_round_trips():
    spec = Specification.model_validate({**BASE, "target_binding": "targets/app.yaml"})
    assert spec.target_binding == "targets/app.yaml"
    assert spec.experiment.target_binding == "targets/app.yaml"
    assert spec.model_dump(mode="json")["target_binding"] == "targets/app.yaml"


@pytest.mark.parametrize("path", ["", "/srv/targets/app.yaml", "C:\\targets\\app.yaml"])
def test_target_binding_must_be_relative(path):
    with pytest.raises(ValidationError):
        Specification.model_validate({**BASE, "target_binding": path})


def test_example_specification_dumps_without_target_binding(repo_root: Path):
    path = (
        repo_root
        / "packages/testbed/wizard/cases/enterprise-ai-assistant/outputs/specification.yaml"
    )
    spec = Specification.model_validate(
        yaml.safe_load(path.read_text(encoding="utf-8"))
    )
    assert "target_binding" not in spec.model_dump(mode="json")
