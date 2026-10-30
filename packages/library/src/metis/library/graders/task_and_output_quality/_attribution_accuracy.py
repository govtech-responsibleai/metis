"""AttributionAccuracyGrader: whether citations correctly identify supporting evidence.

Prompt adapted from DeepEval citation faithfulness
(confident-ai/deepeval@d6cd78a, deepeval/metrics/community/citation_faithfulness/template.py).
Copyright 2024 Confident AI Inc. Licensed under the Apache License, Version 2.0.
Changed for METIS: removed the condition that every factual claim is supported, because Claim
Support by Evidence is a separate grader. DeepEval reads a per-test-case retrieval context;
METIS reads the sources from the session. Citations may take any form and point at those
sources, and the JSON output format is replaced by the shared judge instructions.
See metis/library/EXTERNAL_SOURCES.md for the license text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Literal

from pydantic import Field

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


class AttributionAccuracyArgs(JudgeArgs, TraceArgs, ArtifactArgs):
    """Settings for the attribution-accuracy assessment.

    ``citation_required`` controls behaviour when no citations are found:
    - True (default): missing citations is a scored failure (score 0).
    - False: with no citations the criterion does not apply, and the result is errored.
    """

    turn: Literal["each", "last"] = "last"
    """``last`` judges only the final reply. ``each`` judges every reply."""
    citation_required: bool = Field(
        default=True,
        description=(
            "Whether attribution is required. True: missing citations is a scored "
            "failure. False: with no citations the criterion does not apply."
        ),
    )


class AttributionAccuracyGrader(Grader[AttributionAccuracyArgs]):
    """Assess whether citations correctly identify evidence that supports claims.

    The sources are the content the user gave the agent or the agent retrieved, and the
    files the user gave the target. Claims can be supported but incorrectly cited. When
    ``citation_required=True`` (default), missing citations is a scored failure. When False,
    evidence with no citations is errored, with the judge's reason. Correct source naming is
    distinct from claim support. A session with no sources (only the reply, and no source
    file) is left to the judge, which returns not applicable, so the result is errored with
    its reason.
    """

    args_model = AttributionAccuracyArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.ATTRIBUTION_ACCURACY,
        scopes=(Scope.TRACE, Scope.ARTIFACT),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.EXPECTED_OUTPUT,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        citation_policy = (
            "Attribution is REQUIRED. If the assessed output contains no citations "
            "or source attributions, score 0 — missing required citations is a failure."
            if self.args.citation_required
            else "Attribution is OPTIONAL. If the assessed output contains no citations "
            "or source attributions, the criterion does not apply."
        )
        return (
            "You are assessing whether stated citations or source attributions in the "
            "assessed output correctly identify evidence that supports the associated "
            "claims."
            + sources_block(
                self.scope,
                "If the session has no source content, the criterion does not apply.",
            )
            + f"\n\n<citation_policy>\n{citation_policy}\n</citation_policy>"
            "\n\nA citation may take any form, such as a [N] marker, a source name, a "
            "link, or a footnote. Match each citation to the source it points to in the "
            "sources above.\n"
            "Check each citation: read the source it points to and confirm it supports "
            "the claim the citation is attached to. Score 0 if any claim carries a "
            "citation where the cited source does NOT support that claim — even if some "
            "other source would support it (this is citation misattribution). Judge "
            "relative to the sources only, not world knowledge."
            "\n\n<assessment_boundaries>\n"
            "Assess whether each citation correctly identifies the source material that "
            "supports the associated claim. Correct source naming (pointing to the right "
            "document) is distinct from whether the evidence actually supports the claim "
            "(Claim Support by Evidence). Claims can be supported but incorrectly cited."
            "\n</assessment_boundaries>"
        )

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        return await judge_against_sources(self, llm, input, self.criteria())
