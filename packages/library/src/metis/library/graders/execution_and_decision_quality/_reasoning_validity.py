"""ReasoningValidityGrader: whether recorded conclusions follow from stated premises."""

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


class ReasoningValidityArgs(JudgeArgs, TaskArgs):
    """Settings for the reasoning-validity assessment.

    ``task_description`` provides the goal context so the judge can locate and
    evaluate recorded reasoning within the session.
    """


class ReasoningValidityGrader(Grader[ReasoningValidityArgs]):
    """Assess whether recorded conclusions follow from stated premises and evidence.

    Evaluates the recorded argument only; does not claim access to hidden reasoning.
    Does not infer a reasoning defect merely from an unsuccessful plan. A session with
    no recorded reasoning is errored, with the judge's reason.
    """

    args_model = ReasoningValidityArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.REASONING_VALIDITY,
        scopes=(Scope.SESSION,),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        return (
            "You are assessing whether recorded conclusions follow from stated "
            "premises and evidence under the relevant reasoning rules."
            + self.args.task_block()
            + "\n\n<assessment_boundaries>\n"
            "Evaluate the recorded argument only; do not claim access to hidden "
            "reasoning. Planning feasibility and decision appropriateness are "
            "separate. Do not infer a reasoning defect merely from an unsuccessful "
            "plan; require the argument being assessed. If the session contains no "
            "recorded reasoning or explicit arguments, the criterion does not apply."
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
