"""ClaimSupportByEvidenceGrader: whether claims are supported by the evidence in the session.

Prompt adapted from DeepEval faithfulness claim extraction
(confident-ai/deepeval@d6cd78a, deepeval/metrics/faithfulness/templates/generate_claims.txt).
Copyright 2024 Confident AI Inc. Licensed under the Apache License, Version 2.0.
Changed for METIS: only the claim extraction rules are kept, as the first step of one judge
call. The example, the JSON output format and the template variables are removed.
See metis/library/EXTERNAL_SOURCES.md for the license text.

Prompt adapted from Braintrust Autoevals faithfulness
(braintrustdata/autoevals@586cc16, py/autoevals/ragas.py).
Copyright (c) 2023 BrainTrust Data. Licensed under the MIT License.
Changed for METIS: only the verdict rule of ``NLI_STATEMENTS_PROMPT`` is kept, with the
sources as the context. The verdicts become one binary score. The JSON schema, the examples
and the template variables are removed.
See metis/library/EXTERNAL_SOURCES.md for the license text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Literal

from metis.library.grader import Grader, JudgeArgs
from metis.library.judge import judge_against_sources, sources_block
from metis.library.scope import ArtifactArgs, TraceArgs
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
    from metis.core.grading import GradingOutput
    from metis.core.traces import GradingInput
    from metis.library.grader import LLMSettings


class ClaimSupportByEvidenceArgs(JudgeArgs, TraceArgs, ArtifactArgs):
    """Settings for the claim-support-by-evidence assessment."""

    turn: Literal["each", "last"] = "last"
    """``last`` judges only the final reply. ``each`` judges every reply."""


class ClaimSupportByEvidenceGrader(Grader[ClaimSupportByEvidenceArgs]):
    """Assess whether claims in the output are supported by the evidence in the session.

    The evidence is the content the user gave the agent or the agent retrieved, and the files
    the user gave the target. Support by evidence is independent of whether the claims are
    true in the world and of whether the evidence source is suitable. Output with no factual
    claims to check, or a session with no evidence (only the reply, and no source file), is
    left to the judge, which returns not applicable, so the result is errored with its reason.
    """

    args_model = ClaimSupportByEvidenceArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.CLAIM_SUPPORT_BY_EVIDENCE,
        scopes=(Scope.TRACE, Scope.ARTIFACT),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.EXPECTED_OUTPUT,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        return (
            "You are assessing whether claims in the assessed output are supported by "
            "the sources."
            + sources_block(
                self.scope,
                "Match each claim in the assessed output to the source content that "
                "supports it.",
            )
            + "\n\nFirst, extract the factual claims in the assessed output. Only include "
            "claims that are factual, BUT IT DOESN'T MATTER IF THEY ARE FACTUALLY CORRECT. "
            "The claims you extract should include the full context it was presented in, "
            "NOT cherry picked facts. You should NOT include any prior knowledge, and take "
            "the text at face value when extracting claims.\n\n"
            "Then judge the faithfulness of the series of claims based on the sources. For "
            "each claim you must decide the verdict as 1 if the claim can be verified based "
            "on the sources or 0 if the claim can not be verified based on the sources.\n\n"
            "Score 1 only when every claim can be verified based on the sources. Score 0 "
            "when any claim can not be verified based on the sources, and name that claim "
            "in the reason.\n\n<assessment_boundaries>\n"
            "Assess whether each claim in the assessed output is actually supported by "
            "the sources — not merely non-contradicted. A supported "
            "claim need not be true in the world; support and truth are independent. "
            "Whether the evidence source is authoritative, relevant, or current is a "
            "separate concern (Evidence Source Suitability). An omission of essential "
            "source meaning is Content Fidelity, not lack of support. Assess attribution "
            "separately when required.\n\n"
            "If the assessed output contains no factual claims that can be checked "
            "against the sources, or the session has no source content, the criterion "
            "does not apply."
            "\n</assessment_boundaries>"
        )

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        return await judge_against_sources(self, llm, input, self.criteria())
