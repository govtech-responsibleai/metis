"""ClarificationAppropriatenessGrader: the assistant asks the questions it needs, and no others."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from pydantic import Field

from metis.core.grading import GradingOutput
from metis.core.trace_processing import Problem, render_session
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
from metis.library.text import NonEmptyText  # noqa: TC001 — a Pydantic field type

if TYPE_CHECKING:
    from metis.core.traces import GradingInput
    from metis.library.grader import LLMSettings

_CRITERIA = (
    "You are grading how an assistant asks clarifying questions over a whole conversation. "
    "First, list every question the assistant asked the user, including forms or option "
    "lists it set up for the user to fill in, and every point where it proceeded on an "
    "assumption. A question is necessary only when information that changes how the task "
    "should be done is missing or ambiguous. For each question, check that the user had not "
    "already given the answer, that the assistant could not work it out from the "
    "conversation, and that it was not one of a run of questions asked turn after turn when "
    "the assistant could have proceeded. For each assumption, check that a question was not "
    "needed. Score 1 when every question was necessary and no necessary question was "
    "missed, including when none was needed and none was asked. Score 0 when the assistant "
    "asked a redundant or unnecessary question, asked again for something already given, or "
    "proceeded on a guess where a question was needed. Do not judge a question that is a "
    "response to being unable to proceed, such as a missing permission."
)


class ClarificationAppropriatenessArgs(JudgeArgs):
    confirm_before: NonEmptyText | None = Field(
        default=None,
        description=(
            "Actions that the assistant must confirm with the user before it does them, "
            'such as "payments, deletions, and messages sent for the user".'
        ),
    )
    question_limit: NonEmptyText | None = Field(
        default=None,
        description=(
            "The most questions that the product accepts before the assistant must act, "
            'such as "at most one question before the first answer".'
        ),
    )


class ClarificationAppropriatenessGrader(Grader[ClarificationAppropriatenessArgs]):
    """Whether the assistant asks the clarifying questions it needs, and no others.

    Session scope, so that a pattern such as a question in every recorded turn is visible. The judge
    sees the tool calls too, because a form or option list that a tool sets up is also a
    question to the user. A question caused by an inability to proceed is Appropriate
    handling of capability limits, not this measure.
    """

    args_model = ClarificationAppropriatenessArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.CLARIFICATION_APPROPRIATENESS,
        scopes=(Scope.SESSION,),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        rules = []
        if self.args.confirm_before is not None:
            rules.append(
                "The assistant must confirm these actions with the user before it does "
                f"them: {self.args.confirm_before} A confirmation question for such an "
                "action is necessary. Doing such an action without one is a missed question."
            )
        if self.args.question_limit is not None:
            rules.append(
                f"The product sets this question limit: {self.args.question_limit} "
                "Asking more questions than the limit allows scores 0, even when each "
                "question was necessary."
            )
        return " ".join([_CRITERIA, *rules])

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
