"""AvoidingUnproductiveRepetitionGrader: whether the agent avoids repeating equivalent actions."""

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


class AvoidingUnproductiveRepetitionArgs(JudgeArgs, TaskArgs):
    """Settings for the avoiding-unproductive-repetition assessment.

    ``task_description`` provides the goal context so the judge can distinguish
    justified retries from unproductive loops.
    """


class AvoidingUnproductiveRepetitionGrader(Grader[AvoidingUnproductiveRepetitionArgs]):
    """Assess whether the agent avoids repeating equivalent actions without progress.

    Allows retries justified by transient conditions or new information.
    Step count alone does not establish a loop.
    """

    args_model = AvoidingUnproductiveRepetitionArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.AVOIDING_UNPRODUCTIVE_REPETITION,
        scopes=(Scope.SESSION,),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        return (
            "You are assessing whether the agent avoids repeating substantially "
            "equivalent actions without new evidence or progress."
            + self.args.task_block()
            + "\n\n<assessment_boundaries>\n"
            "Allow retries justified by transient conditions or new information. "
            "Step count alone does not establish a loop. A session with no repeated "
            "actions avoids unproductive repetition, so score it 1."
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
