"""StateTrackingGrader: whether the agent maintains up-to-date state representation."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from pydantic import Field, field_validator

from metis.core.grading import GradingOutput
from metis.core.trace_processing import Problem
from metis.library.grader import Grader, JudgeArgs
from metis.library.judge import TaskArgs, judge, section
from metis.library.scope import SCOPE_DEFINITIONS
from metis.library.taxonomy import (
    Aggregation,
    GraderTaxonomy,
    GraderType,
    JudgmentForm,
    Measure,
    ReferenceType,
    Scope,
)

if TYPE_CHECKING:
    from metis.core.traces import GradingInput
    from metis.library.grader import LLMSettings


class StateTrackingArgs(JudgeArgs, TaskArgs):
    """Settings for the state-tracking assessment.

    ``task_description`` provides the goal context. ``tracked_state`` optionally
    specifies the state elements expected to be tracked.
    """

    tracked_state: tuple[str, ...] = Field(
        default=(),
        description=(
            "State elements expected to be tracked by the agent. "
            "When empty, the judge assesses general state-tracking quality."
        ),
    )

    @field_validator("tracked_state")
    @classmethod
    def _no_blank_items(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        blanks = [i for i, s in enumerate(v) if not s.strip()]
        if blanks:
            raise ValueError(f"Blank entries at positions {blanks}.")
        return v


class StateTrackingGrader(Grader[StateTrackingArgs]):
    """Assess whether the agent maintains up-to-date state representation.

    Evaluates whether the agent correctly updates its representation of task
    progress and environment state after changes. Does not substitute a general
    memory-use score.
    """

    args_model = StateTrackingArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.STATE_TRACKING,
        scopes=(Scope.SESSION,),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        return (
            "You are assessing whether the agent maintains an up-to-date "
            "representation of task progress and changing environment state."
            + self.args.task_block()
            + section("tracked_state", self.args.tracked_state)
            + "\n\n<assessment_boundaries>\n"
            "Assess whether the agent updates its recorded understanding of task "
            "progress and environment state as new evidence arrives. A tool result "
            "shows whether an action ran; this criterion checks whether the agent's "
            "subsequent behaviour reflects the changed state. An attempted action "
            "alone is not proof that the agent tracked the resulting state change. "
            "Whether the agent checked the result before claiming success is outcome "
            "verification, not state tracking. Do not substitute a general memory-use "
            "score."
            "\n</assessment_boundaries>"
        )

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        scope = SCOPE_DEFINITIONS[self.scope]
        selected = scope.select(input, self.args)
        if isinstance(selected, Problem):
            return GradingOutput.errored(selected.detail)
        return GradingOutput(
            results=[
                await judge(self, llm, label, scope.render(thing), self.criteria())
                for label, thing in selected.items()
            ]
        )
