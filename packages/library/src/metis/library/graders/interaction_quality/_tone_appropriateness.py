"""ToneAppropriatenessGrader: the assistant's tone suits the user and the situation."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from pydantic import Field

from metis.core.grading import GradingOutput
from metis.core.trace_processing import Problem, render_dialogue
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
from metis.library.text import NonEmptyText  # noqa: TC001 — a Pydantic field type

if TYPE_CHECKING:
    from metis.core.traces import GradingInput
    from metis.library.grader import LLMSettings

_CRITERIA = (
    "You are grading tone: whether the assistant's interpersonal delivery suits this user, "
    "the situation, and the task. Read the user's messages to learn who they are and how "
    "they feel: their role, the formality they use, and any frustration, urgency, or "
    "distress. Check that each reply is respectful, matches the formality the user and the "
    "task call for, shows care when the user is frustrated or the matter is sensitive, and "
    "keeps the same persona across turns. Score 1 when the tone fits. Score 0 when a reply "
    "is dismissive, condescending, too casual or too stiff for the situation, or the persona "
    "shifts without reason. Do not judge fluency, clarity, correctness, or task success."
)


class ToneAppropriatenessArgs(JudgeArgs, SubsessionArgs):
    expected_tone: NonEmptyText | None = Field(
        default=None,
        description=(
            'The tone that the operator requires, such as "formal and professional" or '
            '"casual and friendly". When unset, the judge decides which tone suits the '
            "user and the task."
        ),
    )


class ToneAppropriatenessGrader(Grader[ToneAppropriatenessArgs]):
    """Whether the assistant's tone suits the user, the situation and the task.

    At session scope, by default, one verdict on all replies, so a persona shift is visible.
    At subsession scope, one verdict for each reply. The judge reads the user messages and
    the replies, without tool traffic. It does not see the target's system prompt, so it
    judges the persona that the replies set up. The criteria draw on the persona-consistency
    part of MLflow ConversationalRoleAdherence.
    """

    args_model = ToneAppropriatenessArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.TONE_APPROPRIATENESS,
        scopes=(Scope.SESSION, Scope.SUBSESSION),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        if self.args.expected_tone is None:
            return _CRITERIA
        return (
            f"{_CRITERIA} The operator requires this tone: {self.args.expected_tone} "
            "Judge formality and register against this tone, not against the user's own "
            "style. Respect, care for a user who is upset, and a stable persona still apply."
        )

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        selected = SCOPE_DEFINITIONS[self.scope].select(input, self.args)
        if isinstance(selected, Problem):
            return GradingOutput.errored(selected.detail)
        return GradingOutput(
            results=[
                await judge(self, llm, label, render_dialogue(turns), self.criteria())
                for label, turns in selected.items()
            ]
        )
