"""FactualAccuracyGrader: whether factual claims agree with designated ground truth.

Prompt adapted from Braintrust Autoevals factuality
(braintrustdata/autoevals@586cc16, templates/factuality.yaml), which comes from the OpenAI
Evals fact prompt (openai/evals@8eac7a7, evals/registry/modelgraded/fact.yaml).
Copyright (c) 2023 BrainTrust Data. Licensed under the MIT License.
Copyright (c) 2023 OpenAI. Licensed under the MIT License.
Changed for METIS: the submitted answer is the assessed evidence and the expert answer is the
ground truth. Options A, B, C and E score 1 and option D scores 0, because a binary judgment
has no partial scores. The data block and template variables are removed.
See metis/library/EXTERNAL_SOURCES.md for the license text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Literal

from pydantic import Field

from metis.core.grading import GradingOutput
from metis.core.trace_processing import Problem
from metis.library.grader import Grader, JudgeArgs
from metis.library.judge import judge, section
from metis.library.scope import SCOPE_DEFINITIONS, ArtifactArgs, TraceArgs
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


class FactualAccuracyArgs(JudgeArgs, TraceArgs, ArtifactArgs):
    """Settings for the factual-accuracy assessment.

    ``ground_truth`` is the authoritative reference. Claims not addressed by the
    ground truth are outside the scope of this assessment. The grader does not use
    the judge's own knowledge.
    """

    turn: Literal["each", "last"] = "last"
    """``last`` judges only the final reply. ``each`` judges every reply."""
    ground_truth: tuple[NonEmptyText, ...] = Field(
        min_length=1,
        description="Authoritative facts to check claims against.",
    )


class FactualAccuracyGrader(Grader[FactualAccuracyArgs]):
    """Assess whether factual claims agree with the designated authoritative ground truth.

    Compares claims against the supplied ground truth only. Does not substitute the
    judge's own knowledge. Partial reference coverage is noted in the reason. Evidence with
    no claim that the ground truth addresses is errored, with the judge's reason.
    """

    args_model = FactualAccuracyArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.FACTUAL_ACCURACY,
        scopes=(Scope.TRACE, Scope.ARTIFACT),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.EXPECTED_OUTPUT,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        return (
            "You are comparing a submitted answer to an expert answer. The submitted "
            "answer is the assessed evidence. The expert answer is the ground truth below."
            + section("ground_truth", self.args.ground_truth)
            + "\n\nCompare the factual content of the submitted answer with the expert "
            "answer. Ignore any differences in style, grammar, or punctuation.\n"
            "The submitted answer may either be a subset or superset of the expert "
            "answer, or it may conflict with it. Determine which case applies. Answer "
            "by selecting one of the following options:\n"
            "(A) The submitted answer is a subset of the expert answer and is fully "
            "consistent with it.\n"
            "(B) The submitted answer is a superset of the expert answer and is fully "
            "consistent with it.\n"
            "(C) The submitted answer contains all the same details as the expert "
            "answer.\n"
            "(D) There is a disagreement between the submitted answer and the expert "
            "answer.\n"
            "(E) The answers differ, but these differences don't matter from the "
            "perspective of factuality.\n\n"
            "Name the option that applies in your reason. Score 1 for option A, B, C or "
            "E. Score 0 for option D."
            "\n\n<assessment_boundaries>\n"
            "Compare factual claims with the designated ground truth above ONLY. Do not "
            "substitute your own knowledge or unsupported recollection. A claim that the "
            "ground truth does not address is outside the scope of this assessment; note "
            "partial coverage in your reason when some claims could not be checked. A claim "
            "contradicted by the ground truth is inaccurate. A response can be complete and "
            "well-structured but still contain an incorrect fact. If the assessed evidence "
            "contains no factual claims assessable against the ground truth, the criterion "
            "does not apply."
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
