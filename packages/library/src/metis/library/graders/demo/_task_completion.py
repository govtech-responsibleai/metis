"""DemoTaskCompletionGrader: by the end of the session, the user got what they asked for."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from metis.core.grading import GradingOutput
from metis.core.trace_processing import Problem
from metis.library.grader import Grader, JudgeArgs
from metis.library.judge import judge
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


class DemoTaskCompletionGrader(Grader[JudgeArgs]):
    """Demo: one judged result for the whole session.

    Shows the simplest model-based grader: the session scope, its own ``criteria()``, and one
    ``judge()`` call for each selected piece. The judge reads every recorded turn with its
    tool calls, because the evidence for an earlier request often sits in an earlier one.
    """

    args_model = JudgeArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.TASK_SUCCESS,
        scopes=(Scope.SESSION,),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        return (
            "You are grading an assistant over a whole conversation. Collect everything the "
            "user asked for across all turns, then judge whether the assistant delivered it by "
            "the end. Count a limit the assistant explained and an alternative the user "
            "accepted as delivered."
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
