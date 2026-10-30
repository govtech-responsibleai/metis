"""Schema sync tests — guard the contract between code and committed artifacts.

These tests verify that the generated `specification.schema.json` in
packages/core/schemas/ stays in sync with the Pydantic model, and that the
example specification remains valid against both. They catch drift that would
otherwise go unnoticed until an external consumer (IDE YAML plugin, CI
jsonschema check, downstream tooling) breaks.
"""

import json
from pathlib import Path

import jsonschema
import pytest
import yaml

from metis.core.specification import _SPECIFICATION_VERSION, Specification


@pytest.fixture
def schema_path(repo_root: Path) -> Path:
    return repo_root / "packages" / "core" / "schemas" / "specification.schema.json"


@pytest.fixture
def example_path(repo_root: Path) -> Path:
    return (
        repo_root
        / "packages"
        / "engine"
        / "examples"
        / "http-agentic_eval_toyapp-1"
        / "specification.yaml"
    )


class TestSchemaSync:
    """Verify the JSON Schema artifact stays in sync with the Pydantic model."""

    def test_schema_is_fresh(self, schema_path: Path):
        """Committed schema must match what generate_schema.py produces now."""
        if not schema_path.exists():
            pytest.fail(
                f"Schema file not found: {schema_path}. Run `make generate-schema`."
            )
        committed = json.loads(schema_path.read_text())
        current = Specification.model_json_schema()
        current["title"] = f"Specification v{_SPECIFICATION_VERSION}"
        assert committed == current, (
            "specification.schema.json is stale. Run `make generate-schema` to regenerate."
        )

    def test_schema_requires_document_header(self, schema_path: Path):
        """Hand-authored files must state the header keys that every written file carries."""
        schema = json.loads(schema_path.read_text())
        assert schema["required"] == [
            "schema_version",
            "id",
            "runner_factory_ref",
            "target",
        ]

    def test_example_validates_against_schema(
        self, schema_path: Path, example_path: Path
    ):
        """The example specification must conform to the JSON Schema."""
        schema = json.loads(schema_path.read_text())
        jsonschema.validate(
            instance=yaml.safe_load(example_path.read_text()), schema=schema
        )

    def test_written_draft_validates_against_schema(self, schema_path: Path):
        """A draft with default header values is written with every required key."""
        schema = json.loads(schema_path.read_text())
        draft = Specification.model_validate(
            {"target": {"name": "T", "users": "U", "description": "D"}}
        )
        jsonschema.validate(instance=draft.model_dump(mode="json"), schema=schema)
