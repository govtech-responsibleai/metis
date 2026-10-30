"""DemoAnswerHelpfulnessGrader: each reply helps with what the user just asked."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from metis.core.grading import GradingOutput
from metis.core.trace_processing import Problem
from metis.library.grader import Grader, JudgeArgs
from metis.library.judge import judge
from metis.library.scope import SCOPE_DEFINITIONS, SubsessionArgs
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


class DemoAnswerHelpfulnessArgs(JudgeArgs, SubsessionArgs):
    """The judge model, and the subsession settings: which recorded turns end a window, and how
    long it is. The default ``window`` holds every recorded turn before the judged one."""


class DemoAnswerHelpfulnessGrader(Grader[DemoAnswerHelpfulnessArgs]):
    """Demo: one judged result for each recorded turn, judged with the recorded turns before it.

    Shows a model-based grader that needs context: it declares the subsession scope, so each recorded
    turn is judged with the conversation before it and never sees what came after. A recorded
    turn whose reply METIS could not read is errored, unless the target itself reported an error
    on it: a missing reply is the target failing, so that turn is judged, with the error shown
    to the judge.
    """

    args_model = DemoAnswerHelpfulnessArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.RELEVANCE,
        scopes=(Scope.SUBSESSION,),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        return (
            "You are grading whether the assistant's reply helps with the user's message, "
            "given what came before. A reply that asks a needed question or explains a real "
            "limit can still be helpful."
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
