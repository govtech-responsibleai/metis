"""Structured-output targets for the model boundary.

The draft models in this module are deliberately not the persisted specification models.  They are
the small set of semantic fields the model is allowed to propose; application code supplies
ids, authorship, defaults and matcher-owned fields afterwards.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from metis.core.profile import CriterionDescription
from metis.wizard.domain.patch import Patch, PatchOp


class _StrictDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BehaviourDraft(_StrictDraft):
    name: str
    description: str


class FeatureDraft(_StrictDraft):
    name: str
    description: str
    behaviours: list[BehaviourDraft] = Field(min_length=1)


class CriterionDraft(_StrictDraft):
    name: str
    description: CriterionDescription


class CriterionConfiguration(_StrictDraft):
    description: CriterionDescription
    grader_args: dict[str, Any]


class PersonaDraft(_StrictDraft):
    name: str
    description: str
    metadata: dict[str, str] = Field(default_factory=dict)


class TaskDraft(_StrictDraft):
    scenario_ref: str
    persona_ref: str
    behaviour_refs: list[str]
    fixtures: list[str] = Field(default_factory=list)


class ScenarioDraft(_StrictDraft):
    name: str
    description: str
    metadata: dict[str, str] = Field(default_factory=dict)


_DRAFT_TYPES = (
    FeatureDraft,
    BehaviourDraft,
    CriterionDraft,
    PersonaDraft,
    ScenarioDraft,
    TaskDraft,
)


def _container(path: str) -> str:
    """Return the final collection field in a patch path."""
    return (
        re.split(r"[.\[]", path)[-1] if path.endswith("]") else path.rsplit(".", 1)[-1]
    )


def _legacy_value(path: str, value: Any) -> Any:
    """Adapt package-authored scripted patches without weakening provider JSON validation."""
    if not isinstance(value, dict):
        return value
    field = _container(path)
    if field == "features":
        behaviours = [
            BehaviourDraft(name=item["name"], description=item["description"])
            for item in value.get("behaviours", [])
        ]
        return FeatureDraft(
            name=value["name"],
            description=value["description"],
            behaviours=behaviours,
        )
    if field == "behaviours":
        return BehaviourDraft(name=value["name"], description=value["description"])
    if field == "criteria":
        return CriterionDraft(
            name=value["name"],
            description=value["description"],
        )
    if field == "personas":
        return PersonaDraft(
            name=value["name"],
            description=value["description"],
            metadata=value.get("metadata", {}),
        )
    if field == "scenarios":
        return ScenarioDraft(
            name=value["name"],
            description=value["description"],
            metadata=value.get("metadata", {}),
        )
    if field == "tasks":
        return TaskDraft.model_validate(value)
    return value


class StepResultPatch(BaseModel):
    """An operation-aware, model-only patch contract.

    Unlike runtime :class:`Patch`, this type has no trust marker and no generic ``Any`` value.  The
    provider must return one of the strict drafts for creation or a scalar/reference value for
    targeted edits.
    """

    model_config = ConfigDict(extra="forbid")

    op: PatchOp
    path: str
    value: (
        FeatureDraft
        | BehaviourDraft
        | CriterionDraft
        | PersonaDraft
        | ScenarioDraft
        | TaskDraft
        | str
        | int
        | bool
        | list[str]
        | None
    ) = None

    @model_validator(mode="before")
    @classmethod
    def from_runtime_patch(cls, value: object) -> object:
        # ScriptedInterviewer and wizard-owned tests construct runtime patches directly.  This
        # compatibility path is never used for provider JSON, where extra fields are rejected.
        if isinstance(value, Patch):
            data = value.model_dump(mode="python")
            data.pop("origin", None)
            data["value"] = _legacy_value(data["path"], data.get("value"))
            return data
        if isinstance(value, dict) and isinstance(value.get("value"), dict):
            # JSON decoding does not preserve the draft subtype.  Rebuild it from the
            # addressed container, while leaving incomplete or legacy shapes for strict
            # Pydantic validation to reject.
            field = _container(str(value.get("path", "")))
            if field in {"personas", "scenarios"}:
                draft_type = PersonaDraft if field == "personas" else ScenarioDraft
                return {**value, "value": draft_type.model_validate(value["value"])}
            required = {
                "features": {"name", "description", "behaviours"},
                "behaviours": {"name", "description"},
                "criteria": {"name", "description"},
                "personas": {"name", "description"},
                "scenarios": {
                    "name",
                    "description",
                    "tasks",
                },
            }.get(field, set())
            semantic = value["value"]
            nested_valid = field != "features" or all(
                isinstance(item, dict) and set(item) == {"name", "description"}
                for item in semantic.get("behaviours", [])
            )
            if set(semantic) == required and nested_valid:
                data = dict(value)
                data["value"] = _legacy_value(str(value["path"]), value["value"])
                return data
        return value

    @model_validator(mode="after")
    def enforce_operation_shape(self) -> StepResultPatch:
        if self.op is PatchOp.ADD:
            field = self.path.rsplit(".", 1)[-1]
            expected = {
                "features": FeatureDraft,
                "behaviours": BehaviourDraft,
                "criteria": CriterionDraft,
                "personas": PersonaDraft,
                "scenarios": ScenarioDraft,
                "tasks": TaskDraft,
            }.get(field)
            if expected is None or not isinstance(self.value, expected):
                raise ValueError(f"add to {field!r} requires its strict draft")
        elif isinstance(self.value, _DRAFT_TYPES):
            raise ValueError("strict drafts are only valid for add operations")
        return self


class StepResult(BaseModel):
    """The text shown with a step and the model's proposed edits."""

    model_config = ConfigDict(extra="forbid")

    message: str
    patches: list[StepResultPatch] = Field(default_factory=list)


class ClarifyResult(StepResult):
    """A clarify question plus target edits and the option to finish early."""

    done: bool = False


class GraderChoice(_StrictDraft):
    """The model's grader suggestion for one Criterion."""

    criterion_id: str
    # An FQN from the offered list, or None when no library grader fits. Models often leave the
    # key out for no match, so a missing key also means None.
    grader: str | None = None


class GraderChoices(_StrictDraft):
    choices: list[GraderChoice]
