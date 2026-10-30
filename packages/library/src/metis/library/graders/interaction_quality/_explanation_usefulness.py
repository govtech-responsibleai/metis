"""ExplanationUsefulnessGrader: the assistant's explanations help the user understand."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from metis.core.grading import GradingOutput
from metis.core.trace_processing import Problem, render_session
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

_CRITERIA = (
    "You are grading explanation usefulness. An explanation is any part of a reply that "
    "tells the user why or how: why a result came out as it did, why the assistant chose an "
    "approach, how a figure was computed, or why a request was declined. One explanation can "
    "be spread over several turns. A useful explanation gives the actual reason or basis, "
    "ties it to the result it explains, and has enough detail for this user to understand it "
    "and act on it, without burying it in method the user did not ask for. Score 1 when the "
    "explanations help the user understand and act. Score 0 when an explanation the user "
    "needed is missing, only restates the result, is too vague to check, or leaves out the "
    "reason. If there is no explanation and none was needed, return status not_applicable."
)


class ExplanationUsefulnessArgs(JudgeArgs, SubsessionArgs):
    pass


class ExplanationUsefulnessGrader(Grader[ExplanationUsefulnessArgs]):
    """Whether the assistant's explanations help the user understand a result or decision.

    At session scope, by default, one verdict, because one explanation can span several
    recorded turns. At subsession scope, one verdict for each reply, judged with the recorded
    turns before it.
    Either way the result is errored when there is no explanation and none was needed.
    """

    args_model = ExplanationUsefulnessArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.EXPLANATION_USEFULNESS,
        scopes=(Scope.SESSION, Scope.SUBSESSION),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        return _CRITERIA

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        selected = SCOPE_DEFINITIONS[self.scope].select(input, self.args)
        if isinstance(selected, Problem):
            return GradingOutput.errored(selected.detail)
        return GradingOutput(
            results=[
                await judge(self, llm, label, render_session(turns), self.criteria())
                for label, turns in selected.items()
            ]
        )
