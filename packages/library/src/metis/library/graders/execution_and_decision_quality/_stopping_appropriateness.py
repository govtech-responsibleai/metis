"""StoppingAppropriatenessGrader: whether the agent stops at the appropriate point."""

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


class StoppingAppropriatenessArgs(JudgeArgs, TaskArgs):
    """Settings for the stopping-appropriateness assessment.

    ``task_description`` provides the goal context. ``stopping_criteria`` optionally
    specifies conditions that define when the agent should stop.
    """

    stopping_criteria: tuple[str, ...] = Field(
        default=(),
        description=(
            "Conditions that define when the agent should stop, continue, or "
            "hand over. When empty, the judge assesses the termination decision "
            "against the task description."
        ),
    )

    @field_validator("stopping_criteria")
    @classmethod
    def _no_blank_items(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        blanks = [i for i, s in enumerate(v) if not s.strip()]
        if blanks:
            raise ValueError(f"Blank entries at positions {blanks}.")
        return v


class StoppingAppropriatenessGrader(Grader[StoppingAppropriatenessArgs]):
    """Assess whether the agent stops, continues, or hands over at the appropriate point.

    Evaluates the termination decision. Repeated non-progress before stopping
    belongs to avoiding unproductive repetition.
    """

    args_model = StoppingAppropriatenessArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.STOPPING_APPROPRIATENESS,
        scopes=(Scope.SESSION,),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        return (
            "You are assessing whether the agent stops, continues, or hands over "
            "at the appropriate point."
            + self.args.task_block()
            + section("stopping_criteria", self.args.stopping_criteria)
            + "\n\n<assessment_boundaries>\n"
            "Assess the termination decision: whether the agent stopped, continued, "
            "or handed over at the right point. Do not assess repeated non-progress "
            "before stopping; that belongs to avoiding unproductive repetition."
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
