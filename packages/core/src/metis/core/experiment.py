"""Experiment plan: Personas, Scenarios, Tasks, and execution settings."""

from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field

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
    user_agent_model: str | None = Field(
        default=None, min_length=1, exclude_if=lambda value: value is None
    )
    """The user agent model of this Test Case."""


class ExperimentDefaults(BaseModel, extra="forbid"):
    """Experiment-wide defaults that individual criteria can override."""

    judge_model: str | None = Field(
        default=None, min_length=1, exclude_if=lambda value: value is None
    )
    """The judge model of every model-based grader."""
    user_agent_model: str | None = Field(
        default=None, min_length=1, exclude_if=lambda value: value is None
    )
    """The user agent model of every Test Case."""
    runner_agent_model: str | None = Field(
        default=None, min_length=1, exclude_if=lambda value: value is None
    )
    """The runner agent model of the generic runners."""
