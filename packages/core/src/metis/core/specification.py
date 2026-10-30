"""A Specification combines a Profile and an Experiment.

YAML and API JSON use one flat document. The domain objects retain their own fields.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    GetJsonSchemaHandler,
    SerializationInfo,
    model_serializer,
    model_validator,
)

if TYPE_CHECKING:
    from pydantic.json_schema import JsonSchemaValue
    from pydantic_core import CoreSchema

from metis.core.experiment import (
    Experiment,
    ExperimentDefaults,
    Persona,
    RelativePath,
    Scenario,
    Task,
    omit_unset_models,
)
from metis.core.profile import Behaviour, Criterion, Feature, Target, TargetProfile

_SPECIFICATION_VERSION = 1


def _require_document_header(schema: dict[str, Any]) -> None:
    # drafts load without these keys, but every written document carries them, so the
    # published schema requires them for hand-authored files.
    header = ["schema_version", "id", "runner_factory_ref"]
    schema["required"] = [*header, *schema.get("required", [])]


# the source of packages/core/schemas/specification.schema.json; run
# `make -C packages/core generate-schema` after a change.
class SpecificationDocument(BaseModel):
    """The flat YAML and API representation of a Specification."""

    model_config = ConfigDict(json_schema_extra=_require_document_header)

    schema_version: Literal[1] = _SPECIFICATION_VERSION
    id: str = ""
    runner_factory_ref: str = "metis.engine.simulation.runners.http.HttpRunnerFactory"
    target_binding: RelativePath | None = None
    defaults: ExperimentDefaults = Field(default_factory=ExperimentDefaults)
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


class Specification(BaseModel):
    """A Profile and an Experiment, authored by hand or through the Interview."""

    schema_version: Literal[1] = _SPECIFICATION_VERSION
    profile: TargetProfile
    experiment: Experiment

    @model_validator(mode="before")
    @classmethod
    def _read_document(cls, data: Any) -> Any:
        if not isinstance(data, dict) or "profile" in data or "experiment" in data:
            return data
        document = SpecificationDocument.model_validate(data)
        return {
            "schema_version": document.schema_version,
            "profile": TargetProfile(
                target=document.target, features=document.features
            ),
            "experiment": Experiment(
                id=document.id,
                runner_factory_ref=document.runner_factory_ref,
                target_binding=document.target_binding,
                defaults=document.defaults,
                personas=document.personas,
                scenarios=document.scenarios,
                tasks=document.tasks,
                fixture_content_descriptions=document.fixture_content_descriptions,
            ),
        }

    @model_serializer
    def _write_document(self, info: SerializationInfo) -> dict[str, Any]:
        document = SpecificationDocument(
            schema_version=self.schema_version,
            **self.profile.model_dump(),
            **self.experiment.model_dump(),
        )
        dumped = document.model_dump(
            mode=info.mode,
            by_alias=info.by_alias,
            include=info.include,
            exclude=info.exclude,
            exclude_none=info.exclude_none,
            exclude_defaults=info.exclude_defaults,
        )
        omit_unset_models(dumped)
        if self.experiment.target_binding is None:
            dumped.pop("target_binding", None)
        return dumped

    @classmethod
    def __get_pydantic_json_schema__(
        cls, core_schema: CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        """Describe the flat document at every API and file boundary."""
        schema = handler(SpecificationDocument.__pydantic_core_schema__)
        schema = handler.resolve_ref_schema(schema).copy()
        schema["title"] = cls.__name__
        return schema

    @property
    def target(self) -> Target:
        return self.profile.target

    @target.setter
    def target(self, value: Target) -> None:
        self.profile.target = value

    @property
    def features(self) -> list[Feature]:
        return self.profile.features

    @features.setter
    def features(self, value: list[Feature]) -> None:
        self.profile.features = value

    @property
    def id(self) -> str:
        return self.experiment.id

    @id.setter
    def id(self, value: str) -> None:
        self.experiment.id = value

    @property
    def runner_factory_ref(self) -> str:
        return self.experiment.runner_factory_ref

    @runner_factory_ref.setter
    def runner_factory_ref(self, value: str) -> None:
        self.experiment.runner_factory_ref = value

    @property
    def target_binding(self) -> str | None:
        return self.experiment.target_binding

    @target_binding.setter
    def target_binding(self, value: str | None) -> None:
        self.experiment.target_binding = value

    @property
    def personas(self) -> list[Persona]:
        return self.experiment.personas

    @personas.setter
    def personas(self, value: list[Persona]) -> None:
        self.experiment.personas = value

    @property
    def scenarios(self) -> list[Scenario]:
        return self.experiment.scenarios

    @scenarios.setter
    def scenarios(self, value: list[Scenario]) -> None:
        self.experiment.scenarios = value

    @property
    def tasks(self) -> list[Task]:
        return self.experiment.tasks

    @tasks.setter
    def tasks(self, value: list[Task]) -> None:
        self.experiment.tasks = value

    @property
    def fixture_content_descriptions(self) -> dict[str, str]:
        return self.experiment.fixture_content_descriptions

    @fixture_content_descriptions.setter
    def fixture_content_descriptions(self, value: dict[str, str]) -> None:
        self.experiment.fixture_content_descriptions = value

    def behaviours(self) -> list[Behaviour]:
        return self.profile.behaviours()

    def measured_behaviours(self) -> list[Behaviour]:
        return self.profile.measured_behaviours()

    def behaviour(self, behaviour_id: str) -> Behaviour | None:
        return self.profile.behaviour(behaviour_id)

    def feature(self, feature_id: str) -> Feature | None:
        return self.profile.feature(feature_id)

    def feature_of(self, behaviour_id: str) -> Feature | None:
        return self.profile.feature_of(behaviour_id)

    def criterion(self, criterion_id: str) -> Criterion | None:
        return self.profile.criterion(criterion_id)

    def persona(self, persona_id: str) -> Persona | None:
        return self.experiment.persona(persona_id)

    def scenario(self, scenario_id: str) -> Scenario | None:
        return self.experiment.scenario(scenario_id)

    def task(self, task_id: str) -> Task | None:
        return self.experiment.task(task_id)

    def trial_count(self) -> int:
        return self.experiment.trial_count()

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
