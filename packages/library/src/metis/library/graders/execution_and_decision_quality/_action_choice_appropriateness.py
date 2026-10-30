"""ActionChoiceAppropriatenessGrader: whether recorded intermediate choices are suitable."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from pydantic import Field, field_validator

from metis.core.grading import GradingOutput
from metis.core.trace_processing import Problem
from metis.library.grader import Grader, JudgeArgs
from metis.library.judge import (
    TaskArgs,
    ToolListArgs,
    available_tools_block,
    judge,
    section,
)
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


class ActionChoiceAppropriatenessArgs(JudgeArgs, TaskArgs, ToolListArgs):
    """Settings for the action-choice appropriateness assessment.

    ``task_description`` provides the goal context. ``assessment_criteria`` optionally
    specifies what makes a choice appropriate for the task.
    """

    assessment_criteria: tuple[str, ...] = Field(
        default=(),
        description=(
            "Criteria for what makes an intermediate choice appropriate. "
            "When empty, the judge assesses general choice suitability."
        ),
    )

    @field_validator("assessment_criteria")
    @classmethod
    def _no_blank_items(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        blanks = [i for i, s in enumerate(v) if not s.strip()]
        if blanks:
            raise ValueError(f"Blank entries at positions {blanks}.")
        return v


class ActionChoiceAppropriatenessGrader(Grader[ActionChoiceAppropriatenessArgs]):
    """Assess whether recorded intermediate choices are suitable.

    Evaluates whether each recorded choice is appropriate for the immediate
    objective, available evidence, constraints, and alternatives. The judge uses the tool
    list (the ``available_tools`` setting, or the tools the session offered) to know the
    alternatives.
    """

    args_model = ActionChoiceAppropriatenessArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.ACTION_CHOICE_APPROPRIATENESS,
        scopes=(Scope.SESSION,),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self, tools: tuple[str, ...]) -> str:
        return (
            "You are assessing whether recorded intermediate choices are suitable "
            "for the immediate objective, available evidence, constraints, and "
            "alternatives."
            + self.args.task_block()
            + section("assessment_criteria", self.args.assessment_criteria)
            + available_tools_block(
                tools,
                "Use available_tools to know the alternatives the agent could have "
                "chosen at each step.",
            )
            + "\n\n<assessment_boundaries>\n"
            "Broad criterion. Assess whether each recorded intermediate choice is "
            "suitable for the immediate objective, available evidence, constraints, "
            "and alternatives."
            "\n</assessment_boundaries>"
        )

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        scope = SCOPE_DEFINITIONS[self.scope]
        selected = scope.select(input, self.args)
        if isinstance(selected, Problem):
            return GradingOutput.errored(selected.detail)
        return GradingOutput(
            results=[
                await judge(
                    self,
                    llm,
                    label,
                    scope.render(thing),
                    self.criteria(self.args.tool_list(input.traces)),
                )
                for label, thing in selected.items()
            ]
        )
