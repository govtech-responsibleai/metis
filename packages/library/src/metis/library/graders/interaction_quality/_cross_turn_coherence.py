"""CrossTurnCoherenceGrader: the conversation stays connected from one turn to the next."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from metis.core.grading import GradingOutput
from metis.core.trace_processing import Problem, render_dialogue, turns
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

_CRITERIA = (
    "You are grading the coherence of a conversation between a user and an assistant. The "
    "evidence lists only what the user said and what the assistant replied, turn by turn. "
    "Coherence is about the conversation's language and flow, not its facts. Check that each "
    "reference to something earlier, such as 'that option', 'the file', 'it', or 'as I said', "
    "points to the right earlier item; that each reply picks up from the previous exchange "
    "instead of restarting; that names and terms for the same thing stay the same; and that "
    "the assistant does not jump to an unrelated thread or repeat content it already gave. "
    "Score 1 when the conversation reads as one connected progression. Score 0 when a "
    "reference does not resolve, a reply breaks from the previous exchange, or terms shift "
    "without reason. Do not judge whether recalled facts are accurate or whether the task "
    "succeeded."
)


class CrossTurnCoherenceArgs(JudgeArgs):
    pass


class CrossTurnCoherenceGrader(Grader[CrossTurnCoherenceArgs]):
    """Whether the conversation stays connected from one recorded turn to the next.

    Session scope, because coherence is a relation between recorded turns. The judge reads only the
    user messages and the replies, so tool traffic cannot hide a break in the conversation.
    It judges flow and references, not whether recalled facts are accurate, which is Use of
    prior information. Errored for a session with fewer than two recorded turns.
    """

    args_model = CrossTurnCoherenceArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.CROSS_TURN_COHERENCE,
        scopes=(Scope.SESSION,),
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
        if len(turns(input.traces)) < 2:
            return GradingOutput.errored(
                "Coherence across turns needs at least two turns."
            )
        return GradingOutput(
            results=[
                await judge(self, llm, label, render_dialogue(piece), self.criteria())
                for label, piece in selected.items()
            ]
        )
