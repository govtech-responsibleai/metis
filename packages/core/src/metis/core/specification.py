"""The specification document: a profile and the configuration needed to conduct an experiment.

YAML and API JSON use the same flat document.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from metis.core.experiment import (
    ExperimentDefaults,
    Persona,
    RelativePath,
    Scenario,
    Task,
)
from metis.core.profile import Behaviour, Criterion, Feature, Target

_SPECIFICATION_VERSION = 1


def _require_document_header(schema: dict[str, Any]) -> None:
    # drafts load without these keys, but every written document carries them, so the
    # published schema requires them for hand-authored files.
    header = ["schema_version", "id", "runner_factory_ref"]
    schema["required"] = [*header, *schema.get("required", [])]


# the source of packages/core/schemas/specification.schema.json; run
# `make -C packages/core generate-schema` after a change.
class Specification(BaseModel):
    """The flat YAML and API representation of a Specification."""

    model_config = ConfigDict(json_schema_extra=_require_document_header)

    schema_version: Literal[1] = _SPECIFICATION_VERSION
    id: str = ""
    runner_factory_ref: str = "metis.engine.simulation.runners.http.HttpRunnerFactory"
    # unset values stay out of a dump, so existing specs serialise unchanged.
    target_binding: RelativePath | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    defaults: ExperimentDefaults = Field(
        default_factory=ExperimentDefaults,
        exclude_if=lambda value: value == ExperimentDefaults(),
    )
    target: Target
    features: list[Feature] = Field(default_factory=list)
    personas: list[Persona] = Field(default_factory=list)
    scenarios: list[Scenario] = Field(default_factory=list)
    tasks: list[Task] = Field(default_factory=list)
    fixture_content_descriptions: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _check_version(cls, data: object) -> object:
        """Reject only an explicit version we cannot read; a missing key takes the default."""
        if not isinstance(data, dict):
            return data
        version = data.get("schema_version")
        if version is not None and version != _SPECIFICATION_VERSION:
            raise ValueError(
                f"Unsupported schema_version {version!r} (expected {_SPECIFICATION_VERSION}). "
                "This specification.yaml was written by a different version of METIS."
            )
        return data

    def behaviours(self) -> list[Behaviour]:
        """Every behaviour, in document order."""
        return [b for feature in self.features for b in feature.behaviours]

    def measured_behaviours(self) -> list[Behaviour]:
        """The behaviours the user chose to measure."""
        return [
            b for feature in self.features for b in feature.behaviours if b.measured
        ]

    def behaviour(self, behaviour_id: str) -> Behaviour | None:
        return next((b for b in self.behaviours() if b.id == behaviour_id), None)

    def feature(self, feature_id: str) -> Feature | None:
        """Find a Feature by ID."""
        return next((f for f in self.features if f.id == feature_id), None)

    def feature_of(self, behaviour_id: str) -> Feature | None:
        """Which feature owns a behaviour — symmetric with `feature` and `behaviour`."""
        return next(
            (
                f
                for f in self.features
                if any(b.id == behaviour_id for b in f.behaviours)
            ),
            None,
        )

    def criterion(self, criterion_id: str) -> Criterion | None:
        return next(
            (c for b in self.behaviours() for c in b.criteria if c.id == criterion_id),
            None,
        )

    def persona(self, persona_id: str) -> Persona | None:
        return next((p for p in self.personas if p.id == persona_id), None)

    def scenario(self, scenario_id: str) -> Scenario | None:
        return next((s for s in self.scenarios if s.id == scenario_id), None)

    def task(self, task_id: str) -> Task | None:
        return next((task for task in self.tasks if task.id == task_id), None)

    def trial_count(self) -> int:
        return sum(task.num_trials for task in self.tasks)

    def scenarios_covering(self, behaviour_id: str) -> list[Scenario]:
        covered = {
            t.scenario_ref for t in self.tasks if behaviour_id in t.behaviour_refs
        }
        return [s for s in self.scenarios if s.id in covered]

    def uncovered(self) -> list[Behaviour]:
        """Measured behaviours that no scenario exercises."""
        return [
            b for b in self.measured_behaviours() if not self.scenarios_covering(b.id)
        ]

    def execution_errors(self) -> list[str]:
        """Validate a complete document without preventing incomplete Interview drafts."""
        errors: list[str] = []
        if not self.id or not self.runner_factory_ref:
            errors.append("The specification needs an ID and a runner reference.")
        nodes = [
            *self.features,
            *self.behaviours(),
            *[c for b in self.behaviours() for c in b.criteria],
            *self.personas,
            *self.scenarios,
            *self.tasks,
        ]
        seen: set[str] = set()
        for node in nodes:
            if not node.id or node.id in seen:
                errors.append(f"Duplicate or empty ID: {node.id!r}.")
            seen.add(node.id)
        for criterion in [c for b in self.behaviours() for c in b.criteria]:
            if not criterion.grader_fqn:
                errors.append(f"Criterion {criterion.id} needs a Grader.")
        measured = {b.id for b in self.measured_behaviours()}
        for behaviour in self.measured_behaviours():
            if not behaviour.criteria:
                errors.append(f"Measured Behaviour {behaviour.id} needs a Criterion.")
        for task in self.tasks:
            if any(char in task.id for char in ("/", "\\", "\x00")) or task.id in {
                ".",
                "..",
            }:
                errors.append(f"Task {task.id!r} has an invalid ID.")
            if not self.scenario(task.scenario_ref) or not self.persona(
                task.persona_ref
            ):
                errors.append(f"Task {task.id} needs an existing Scenario and Persona.")
            if task.num_trials < 1:
                errors.append(f"Task {task.id} needs at least one Trial.")
            if not task.behaviour_refs or any(
                ref not in measured for ref in task.behaviour_refs
            ):
                errors.append(f"Task {task.id} must select measured Behaviours.")
            if len(set(task.behaviour_refs)) != len(task.behaviour_refs):
                errors.append(f"Task {task.id} repeats a Behaviour.")
            if len(set(task.fixtures)) != len(task.fixtures):
                errors.append(f"Task {task.id} repeats a fixture.")
            if any(
                not name or "/" in name or "\\" in name or name in {".", ".."}
                for name in task.fixtures
            ):
                errors.append(f"Task {task.id} has an invalid fixture filename.")
        for scenario in self.scenarios:
            if not any(t.scenario_ref == scenario.id for t in self.tasks):
                errors.append(f"Scenario {scenario.id} needs a Task.")
        for behaviour in self.uncovered():
            errors.append(f"Measured Behaviour {behaviour.id} needs Task coverage.")
        if not self.tasks:
            errors.append("The specification needs at least one Task.")
        return errors


def collect_specification_ids(specification: Specification) -> set[str]:
    """Return every node and reference id present in a specification."""
    ids = {
        *(feature.id for feature in specification.features),
        *(behaviour.id for behaviour in specification.behaviours()),
        *(
            criterion.id
            for behaviour in specification.behaviours()
            for criterion in behaviour.criteria
        ),
        *(persona.id for persona in specification.personas),
        *(scenario.id for scenario in specification.scenarios),
        *(task.id for task in specification.tasks),
        *(ref for task in specification.tasks for ref in task.behaviour_refs),
    }
    return ids
