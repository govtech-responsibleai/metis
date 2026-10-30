"""ContentFidelityGrader: whether a transformation preserves the meaning of its source."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Literal

from pydantic import Field, field_validator

from metis.library.grader import Grader, JudgeArgs
from metis.library.judge import judge_against_sources, section, sources_block
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


class ContentFidelityArgs(JudgeArgs, TraceArgs, ArtifactArgs):
    """Settings for the content-fidelity assessment.

    ``fidelity_requirements`` optionally specifies coverage, addition, or omission rules.
    """

    turn: Literal["each", "last"] = "last"
    """``last`` judges only the final reply. ``each`` judges every reply."""
    fidelity_requirements: tuple[str, ...] = Field(
        default=(),
        description=(
            "Specific requirements about coverage, additions, or omissions. "
            "When empty, the judge assesses general meaning preservation."
        ),
    )

    @field_validator("fidelity_requirements")
    @classmethod
    def _no_blank_items(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        blanks = [i for i, s in enumerate(v) if not s.strip()]
        if blanks:
            raise ValueError(f"Blank entries at positions {blanks}.")
        return v


class ContentFidelityGrader(Grader[ContentFidelityArgs]):
    """Assess whether a transformation preserves the meaning of its source.

    The source is in the session: the content the user gave the agent or the agent
    retrieved, and the files the user gave the target. Compares preservation against the
    source, not truth against the world. A transformation can have supported claims yet lose
    essential meaning through omission. Legitimate omission failures are not suppressed. A
    session with no source content (only the reply, and no source file) is left to the judge,
    which returns not applicable, so the result is errored with its reason.
    """

    args_model = ContentFidelityArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.CONTENT_FIDELITY,
        scopes=(Scope.TRACE, Scope.ARTIFACT),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.EXPECTED_OUTPUT,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        return (
            "You are assessing whether a transformation preserves the meaning or content "
            "of its source."
            + sources_block(
                self.scope,
                "Find the source content that the assessed output transforms, and compare "
                "the output with it. If the session has no source content for the output, "
                "the criterion does not apply.",
            )
            + section("fidelity_requirements", self.args.fidelity_requirements)
            + "\n\n<assessment_boundaries>\n"
            "Compare preservation against the source, not truth against the world. "
            "A summary can have fully supported claims yet lose essential meaning through "
            "omission. Assess whether the assessed output preserves the source's main "
            "meaning and qualifications, including required coverage and restrictions on "
            "additions or omissions. A legitimate omission failure should not be "
            "suppressed merely because completeness is a related criterion — this "
            "criterion checks preservation relative to the source."
            "\n</assessment_boundaries>"
        )

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        return await judge_against_sources(self, llm, input, self.criteria())
