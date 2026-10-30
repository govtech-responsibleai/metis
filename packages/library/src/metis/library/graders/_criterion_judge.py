"""Judge a session against the instructions in its criterion."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from metis.core.grading import GradingOutput
from metis.core.trace_processing import Problem
from metis.library.grader import CriterionJudgeArgs, Grader
from metis.library.judge import judge
from metis.library.scope import SCOPE_DEFINITIONS
from metis.library.taxonomy import (
    Aggregation,
    GraderTaxonomy,
    GraderType,
    JudgmentForm,
    ReferenceType,
    Scope,
)

if TYPE_CHECKING:
    from metis.core.traces import GradingInput
    from metis.library.grader import LLMSettings


class CriterionJudgeGrader(Grader[CriterionJudgeArgs]):
    """Assess the recorded session against a criterion description with a binary score.

    The judge reads the whole session, with each tool call's arguments and result in full. A
    session with no recorded turns is errored without a judge call.
    """

    args_model = CriterionJudgeArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=None,
        scopes=(Scope.SESSION,),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        return (
            "Assess the entire recorded session against the criterion below."
            f"\n\n<criterion>\n{self.args.criterion}\n</criterion>"
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
