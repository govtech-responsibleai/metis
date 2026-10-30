"""EvidenceSourceSuitabilityGrader: whether evidence sources meet suitability requirements."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Literal

from pydantic import Field, field_validator

from metis.core.grading import GradingOutput
from metis.core.trace_processing import Problem
from metis.library.aggregation import AGGREGATION_DEFINITIONS
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


class EvidenceSourceSuitabilityArgs(JudgeArgs, TraceArgs, ArtifactArgs):
    """Settings for the evidence-source-suitability assessment.

    ``sources`` lists the evidence sources to assess. Each source is judged on its own,
    and a result scores 1 only when every source is suitable. The result is errored when
    no source is unsuitable but one cannot be judged.
    """

    turn: Literal["each", "last"] = "last"
    """``last`` judges only the final reply. ``each`` judges every reply."""
    suitability_requirements: tuple[NonEmptyText, ...] = Field(
        min_length=1,
        description="Requirements for authority, relevance, and currency of sources.",
    )
    sources: tuple[NonEmptyText, ...] = Field(
        min_length=1,
        description="Descriptions of the evidence sources to assess.",
    )

    @field_validator("sources", "suitability_requirements")
    @classmethod
    def _no_blank_items(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        blanks = [i for i, s in enumerate(v) if not s.strip()]
        if blanks:
            raise ValueError(f"Blank entries at positions {blanks}.")
        return v


class EvidenceSourceSuitabilityGrader(Grader[EvidenceSourceSuitabilityArgs]):
    """Assess whether evidence sources meet authority, relevance, and currency requirements.

    Suitability is independent of whether the source supports a particular claim. Each
    source is judged on its own, and a result scores 1 only when every source is
    suitable.
    """

    args_model = EvidenceSourceSuitabilityArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.EVIDENCE_SOURCE_SUITABILITY,
        scopes=(Scope.TRACE, Scope.ARTIFACT),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.PASS_IF_ALL,),
    )

    def criteria(self, source: str) -> str:
        return (
            "You are assessing whether one evidence source meets the task-specific "
            "requirements for authority, relevance, and currency. Score 1 when the source "
            "is suitable."
            f"\n\n<source>\n{source}\n</source>"
            + section("suitability_requirements", self.args.suitability_requirements)
            + "\n\n<assessment_boundaries>\n"
            "Assess whether each source is appropriate to rely on for the task. "
            "Suitability is independent of whether the source supports a particular "
            "claim. An outdated manual may support a claim about an old product version "
            "while being unsuitable for a question about the current version. "
            "Use Claim Support by Evidence to assess claim-evidence connections, and "
            "Attribution Accuracy to assess correct source identification."
            "\n</assessment_boundaries>"
        )

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        scope = SCOPE_DEFINITIONS[self.scope]
        selected = scope.select(input, self.args)
        if isinstance(selected, Problem):
            return GradingOutput.errored(selected.detail)
        combine = AGGREGATION_DEFINITIONS[self.aggregation]
        results = []
        for label, thing in selected.items():
            evidence = scope.render(thing)
            per_rule = [
                await judge(self, llm, label, evidence, self.criteria(source))
                for source in self.args.sources
            ]
            results.append(combine(per_rule, label))
        return GradingOutput(results=results)
