"""ErrorDetectionGrader: whether the agent observably identifies errors."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from metis.core.grading import GradingOutput
from metis.core.trace_processing import Problem
from metis.library.grader import Grader, JudgeArgs
from metis.library.judge import TaskArgs, judge
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


class ErrorDetectionArgs(JudgeArgs, TaskArgs):
    """Settings for the error-detection assessment.

    ``task_description`` provides the goal context.
    """


class ErrorDetectionGrader(Grader[ErrorDetectionArgs]):
    """Assess whether the agent observably identifies failed or erroneous actions.

    Requires a visible flag, statement, or corrective behaviour. Does not infer
    unobserved internal recognition. A session with no observable error is errored,
    with the judge's reason.
    """

    args_model = ErrorDetectionArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.ERROR_DETECTION,
        scopes=(Scope.SESSION,),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        return (
            "You are assessing whether the agent observably identifies failed or "
            "erroneous actions, assumptions, or results."
            + self.args.task_block()
            + "\n\n<assessment_boundaries>\n"
            "Require a visible flag, statement, or corrective behaviour. Do not infer "
            "unobserved internal recognition. If no errors or failures are observable "
            "in the session, the criterion does not apply."
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
