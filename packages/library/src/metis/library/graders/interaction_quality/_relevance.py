"""RelevanceGrader: the assistant's replies address what the user needs.

Prompt adapted from DeepEval turn relevancy
(confident-ai/deepeval@d6cd78a, deepeval/metrics/turn_relevancy/templates/generate_verdicts.txt).
Copyright 2024 Confident AI Inc. Licensed under the Apache License, Version 2.0.
Changed for METIS: at session scope the judge gives one verdict for the whole conversation,
where a few replies that drift do not fail it. A needed question or a stated limit is also
relevant, and yes and no map to scores 1 and 0. The example and the JSON output format are
replaced by the shared judge instructions.
See metis/library/EXTERNAL_SOURCES.md for the license text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from pydantic import Field

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
from metis.library.text import NonEmptyText  # noqa: TC001 — a Pydantic field type

if TYPE_CHECKING:
    from metis.core.traces import GradingInput
    from metis.library.grader import LLMSettings

_CRITERIA = (
    "You are grading relevance: whether the assistant's replies are relevant to the context "
    "in the messages. You MUST USE the previous messages (if any) to make an informed "
    "judgement on relevancy. A reply is relevant when it responds to the user's current "
    "message, given what came before. Vague replies to vague inputs, such as greetings, do "
    "not count as irrelevancies. A needed question or a stated limit can also be relevant. "
    "A reply is not relevant when it ignores, misreads, or wanders from what the user asked. "
    "When judging a whole conversation, a few replies that drift do not fail it if the "
    "conversation as a whole stays on the user's needs. Score 1 for relevant and 0 for not "
    "relevant."
)

_BOUNDARIES = (
    "\n\n<assessment_boundaries>\n"
    "Do not judge whether a reply is true, complete, or achieves the task."
    "\n</assessment_boundaries>"
)


class RelevanceArgs(JudgeArgs, SubsessionArgs):
    purpose: NonEmptyText | None = Field(
        default=None,
        description=(
            'What the assistant is for, such as "answers billing questions for a telecom '
            'provider". The judge uses it to tell which requests the assistant should '
            "handle and which it should redirect."
        ),
    )


class RelevanceGrader(Grader[RelevanceArgs]):
    """Whether the assistant's replies address what the user needs.

    At session scope, by default, one holistic verdict: a few off-target recorded turns can still
    pass when the conversation as a whole stays on the user's needs. At subsession scope, one
    verdict for each recorded turn, judged with the recorded turns before it. Relevance only, not truth,
    completeness or task success.
    """

    args_model = RelevanceArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.RELEVANCE,
        scopes=(Scope.SESSION, Scope.SUBSESSION),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        if self.args.purpose is None:
            return _CRITERIA + _BOUNDARIES
        return (
            _CRITERIA + f" The operator states that the assistant is for: "
            f"{self.args.purpose} A reply that redirects or declines a request outside "
            "that purpose is relevant." + _BOUNDARIES
        )

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
