"""CommunicationClarityGrader: the assistant's replies are clear and well organized.

The conciseness check is adapted from Arize Phoenix evals conciseness classification evaluator
(Arize-ai/phoenix@d5f5e05, js/packages/phoenix-evals/src/__generated__/default_templates/
CONCISENESS_CLASSIFICATION_EVALUATOR_CONFIG.ts).
Copyright 2025 Arize AI, Inc. Licensed under the Apache License, Version 2.0.
Changed for METIS: the verbose rubric is one check inside a wider clarity measure, and a reply
fails it only when the extra content makes the meaning hard to get. The rule against
explanations that were not requested is removed, because a needed explanation is not padding.
The template variables and output format are replaced by the session evidence and the shared
judge instructions.
See metis/library/EXTERNAL_SOURCES.md for the license text.
"""

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
    "You are grading communication clarity: whether the user can get the meaning of the "
    "assistant's replies without avoidable effort. Check that the main point or answer comes "
    "first or is easy to find; that the order and structure, such as steps, lists, or "
    "headings, fit the content; that the meaning has one reasonable reading; that terms the "
    "user may not know are explained or avoided; and that the point is not hidden under "
    "repetition, filler, or detail the user did not need. Filler includes unnecessary "
    "pleasantries, hedging language or excessive qualifiers, meta-commentary about the "
    "response itself, and unnecessary formatting for simple answers. Score 1 when the "
    "replies are clear. Score 0 when a reply is ambiguous, disorganized, or padded enough to "
    "make the meaning hard to get."
)

_BOUNDARIES = (
    "\n\n<assessment_boundaries>\n"
    "Grammar and natural phrasing belong to output naturalness, and politeness and warmth to "
    "tone, so do not judge them here. Do not judge correctness or task success."
    "\n</assessment_boundaries>"
)


class CommunicationClarityArgs(JudgeArgs, SubsessionArgs):
    audience: NonEmptyText | None = Field(
        default=None,
        description=(
            'Who receives the output and what they already know, such as "members of the '
            'public with no technical background". When unset, the judge reads the '
            "audience from the conversation."
        ),
    )


class CommunicationClarityGrader(Grader[CommunicationClarityArgs]):
    """Whether the assistant's replies are clear, well organized and free of avoidable ambiguity.

    At session scope, by default, one verdict on all replies. At subsession scope, one verdict
    for each reply. The judge reads the user messages and the replies, without tool traffic,
    because clarity is a property of what the user reads. It covers organization, ambiguity
    and padding, not fluent phrasing or tone, which have their own graders.
    """

    args_model = CommunicationClarityArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.COMMUNICATION_CLARITY,
        scopes=(Scope.SESSION, Scope.SUBSESSION),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        if self.args.audience is None:
            return _CRITERIA + _BOUNDARIES
        return (
            _CRITERIA
            + " Judge clarity for this audience, not for the user that the conversation "
            f"suggests: {self.args.audience} Count a term as unexplained only if this "
            "audience would not know it." + _BOUNDARIES
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
