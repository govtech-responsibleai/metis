"""Experiment plan: Personas, Scenarios, Tasks, and execution settings."""

from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
)

from metis.core.profile import NamedNode


def _require_relative(path: str) -> str:
    if (
        not path
        or PurePosixPath(path).is_absolute()
        or PureWindowsPath(path).is_absolute()
    ):
        raise ValueError("must be a non-empty path relative to specification.yaml")
    return path


RelativePath = Annotated[str, AfterValidator(_require_relative)]
"""A path relative to ``specification.yaml``; ``..`` is allowed."""

_OPTIONAL_MODELS = ("judge_model", "user_agent_model", "runner_agent_model")


def omit_unset_models(data: dict[str, Any]) -> None:
    """Remove unset model fields from a dumped Experiment or Specification, in place.

    Existing specs then serialise unchanged. ``defaults`` goes when nothing in it is set.
    """
    defaults = data.get("defaults")
    if isinstance(defaults, dict):
        for key in _OPTIONAL_MODELS:
            if defaults.get(key) is None:
                defaults.pop(key, None)
        if not defaults:
            data.pop("defaults")
    for task in data.get("tasks") or []:
        if isinstance(task, dict) and task.get("user_agent_model") is None:
            task.pop("user_agent_model", None)


class Persona(NamedNode[str]):
    """A user type whose id can differ from its display name."""

    metadata: dict[str, str] = Field(default_factory=dict)


class Scenario(NamedNode[str], extra="forbid"):
    """The situation in which Tasks evaluate the target."""

    metadata: dict[str, str] = Field(default_factory=dict)


class Task(BaseModel, extra="forbid"):
    """One test case. Identity survives edits to its references and inputs."""

    id: str
    scenario_ref: str
    persona_ref: str
    fixtures: list[str] = Field(default_factory=list)
    num_trials: int = Field(default=3, strict=True)
    behaviour_refs: list[str] = Field(default_factory=list)
    max_turns: int = Field(default=20, gt=0, strict=True)
    timeout_minutes: int = Field(default=15, gt=0, strict=True)
    response_wait_ms: int = Field(default=300000, gt=0, strict=True)
    max_run_retries: int | None = Field(default=None, ge=0, strict=True)
    user_agent_model: str | None = Field(default=None, min_length=1)
    """The user agent model of this Test Case."""


class ExperimentDefaults(BaseModel, extra="forbid"):
    """Experiment-wide defaults that individual criteria can override."""

    judge_model: str | None = Field(default=None, min_length=1)
    """The judge model of every model-based grader."""
    user_agent_model: str | None = Field(default=None, min_length=1)
    """The user agent model of every Test Case."""
    runner_agent_model: str | None = Field(default=None, min_length=1)
    """The runner agent model of the generic runners."""


class Experiment(BaseModel):
    """The Test Cases and settings used to execute an evaluation."""

    id: str = ""
    runner_factory_ref: str = "metis.engine.simulation.runners.http.HttpRunnerFactory"
    target_binding: RelativePath | None = None
    """The ``TargetBinding`` file the generic runner reads, relative to ``specification.yaml``."""
    defaults: ExperimentDefaults = Field(default_factory=ExperimentDefaults)
    personas: list[Persona] = Field(default_factory=list)
    scenarios: list[Scenario] = Field(default_factory=list)
    tasks: list[Task] = Field(default_factory=list)
    fixture_content_descriptions: dict[str, str] = Field(default_factory=dict)

    @model_serializer(mode="wrap")
    def _omit_empty_defaults(self, handler: SerializerFunctionWrapHandler) -> Any:
        """Leave unset models, ``defaults`` and ``target_binding`` out, so existing specs
        serialise unchanged."""
        data = handler(self)
        if isinstance(data, dict):
            omit_unset_models(data)
            if self.target_binding is None:
                data.pop("target_binding", None)
        return data

    def persona(self, persona_id: str) -> Persona | None:
        return next((p for p in self.personas if p.id == persona_id), None)

    def scenario(self, scenario_id: str) -> Scenario | None:
        return next((s for s in self.scenarios if s.id == scenario_id), None)

    def task(self, task_id: str) -> Task | None:
        return next((task for task in self.tasks if task.id == task_id), None)

    def trial_count(self) -> int:
        return sum(task.num_trials for task in self.tasks)
