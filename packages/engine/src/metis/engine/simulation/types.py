"""Pydantic models for simulation types.

Covers simulation inputs and the interface types between the user agent and a runner: what the
user agent decides each turn and what a runner hands back. Trial records live in
``metis.core.trials``. The specification schema is published by metis-core. See
``packages/core/schemas/README.md``.
"""

from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, model_validator

from metis.core import Artifact
from metis.core.experiment import Persona, Task
from metis.core.specification import Specification as CoreSpecification
from metis.core.trials import GraderRef

__all__ = [
    "Artifact",
    "Observation",
    "Persona",
    "Promise",
    "Reading",
    "Scenario",
    "Specification",
    "UserAgentOutput",
]

# ---------------------------------------------------------------------------
# Interface types
# ---------------------------------------------------------------------------


class UserAgentOutput(BaseModel):
    """One turn's decision, as the user agent's LLM returns it."""

    reasoning: str = Field(
        description=(
            "What you observed and why you chose this action. It is not shown to the "
            "assistant."
        )
    )
    """Why the user chose this. Kept in the log, never shown to the target or the runner."""
    action: str = Field(
        description=(
            "One plain-language action. Anything you send to the assistant, the whole "
            "message, goes between ⟦ and ⟧, written the way your persona would type it, "
            "for example: ⟦How many leave days do I get?⟧. An action with no ⟦ ⟧ "
            "quoted message means nothing is sent."
        )
    )
    """One plain-language action. Text for the target sits between ``⟦`` and ``⟧``."""
    decision: Literal["continue", "goal_achieved", "giving_up"] = Field(
        description=(
            '"goal_achieved" when you have what you asked for; "giving_up" when the '
            "assistant keeps failing to make progress or your persona would give up; "
            '"continue" otherwise.'
        )
    )
    """Whether the user carries on, has what they wanted, or gives up."""

    @model_validator(mode="after")
    def _continue_needs_an_action(self) -> Self:
        if self.decision == "continue" and not self.action.strip():
            raise ValueError("a 'continue' decision needs an action")
        return self


class Reading(BaseModel):
    """The runner's own account of what its action did.

    An interpretation, not a fact: the user agent is told so. Whatever code can copy
    or measure belongs on :class:`Observation` instead.
    """

    outcome: str
    why: str
    next_options: str = ""
    """What the runner thinks the user could do next, if it has a view."""


class Observation(BaseModel):
    """What one ``Runner.act`` hands back, with facts kept apart from the reading."""

    reply: str | None
    """The target's reply, copied by code. ``None`` when no reply was shown."""
    reading: Reading
    promised: list[str] = Field(default_factory=list)
    """Names of files the reply promised, copied by code from it."""
    observed: bool = True
    """``False`` when nobody could check the target's state after the action."""
    notice: str | None = None
    """A problem METIS itself found with the turn, such as a timeout. Not the runner's."""
    submission_unresolved: bool = False
    """``True`` when a submission never settled, so the target cannot take another."""
    sent_nothing: bool = False
    """``True`` when the action tried to send a message but quoted none, so the runner
    refused the submission and none reached the target. The turn is not counted."""


class Promise(BaseModel, frozen=True):
    """A file the target said it would deliver."""

    name: str
    turn: int
    """The simulated turn whose reply promised it."""


# ---------------------------------------------------------------------------
# Experiment
# ---------------------------------------------------------------------------


class Scenario(BaseModel):
    task_id: str = ""
    id: str
    description: str
    metadata: dict[str, str] = Field(default_factory=dict)
    num_trials: int = 1
    fixtures: list[str] = Field(default_factory=list)
    persona_refs: list[str] = Field(min_length=1)
    grader_refs: list[GraderRef] = Field(default_factory=list)
    max_turns: int = 20
    timeout_minutes: int = 15
    response_wait_ms: int = 300000
    max_trial_retries: int | None = None
    user_agent_model: str | None = None
    """The Task's ``user_agent_model``. ``None`` takes the experiment default."""

    @model_validator(mode="after")
    def _check_unique_fixtures(self) -> Self:
        seen: set[str] = set()
        dupes: list[str] = []
        for name in self.fixtures:
            if name in seen:
                dupes.append(name)
            seen.add(name)
        if dupes:
            raise ValueError(
                f"Scenario '{self.id}' lists duplicate fixture(s): "
                f"{sorted(set(dupes))}. Each fixture name must appear at most once."
            )
        return self

    @model_validator(mode="after")
    def _check_unique_persona_refs(self) -> Self:
        seen: set[str] = set()
        dupes: list[str] = []
        for ref in self.persona_refs:
            if ref in seen:
                dupes.append(ref)
            seen.add(ref)
        if dupes:
            raise ValueError(
                f"Scenario '{self.id}' lists duplicate persona_ref(s): "
                f"{sorted(set(dupes))}. Each persona_ref must appear at most once."
            )
        return self


class Specification(CoreSpecification):
    """A complete Specification validated for engine execution."""

    @model_validator(mode="before")
    @classmethod
    def _require_header(cls, data: Any) -> Any:
        # drafts take defaults for these keys; a file the engine runs must state them.
        if isinstance(data, dict) and not {"profile", "experiment"} & data.keys():
            missing = [
                key
                for key in ("schema_version", "id", "runner_factory_ref")
                if key not in data
            ]
            if missing:
                raise ValueError(
                    f"The specification needs these keys: {', '.join(missing)}."
                )
        return data

    @model_validator(mode="after")
    def _check_execution(self) -> Self:
        errors = self.execution_errors()
        if errors:
            raise ValueError(" ".join(errors))
        from .runner_resolver import resolve_runner_factory

        try:
            resolve_runner_factory(self.runner_factory_ref)
        except (ImportError, TypeError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        return self

    def resolved_tasks(self) -> list[Scenario]:
        return [self.resolve_task(task) for task in self.tasks]

    def resolve_task(self, task: Task) -> Scenario:
        scenario = self.scenario(task.scenario_ref)
        assert scenario is not None
        refs = []
        for behaviour_id in task.behaviour_refs:
            behaviour = self.behaviour(behaviour_id)
            assert behaviour is not None
            for criterion in behaviour.criteria:
                assert criterion.grader_fqn
                refs.append(
                    GraderRef(
                        criterion_id=criterion.id,
                        fqn=criterion.grader_fqn,
                        args=criterion.grader_args,
                        description=criterion.description,
                    )
                )
        return Scenario(
            id=scenario.id,
            task_id=task.id,
            description=scenario.description,
            metadata=scenario.metadata,
            persona_refs=[task.persona_ref],
            num_trials=task.num_trials,
            max_turns=task.max_turns,
            timeout_minutes=task.timeout_minutes,
            response_wait_ms=task.response_wait_ms,
            max_trial_retries=task.max_run_retries,
            user_agent_model=task.user_agent_model,
            fixtures=task.fixtures,
            grader_refs=refs,
        )

    @classmethod
    def load_file(cls, path: Path) -> Self:
        import yaml

        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
