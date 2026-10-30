"""OutcomeVerificationGrader: whether the agent checks results before claiming success."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from pydantic import Field, field_validator

from metis.core.grading import GradingOutput
from metis.core.trace_processing import Problem
from metis.library.grader import Grader, JudgeArgs
from metis.library.judge import TaskArgs, judge, section
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


class OutcomeVerificationArgs(JudgeArgs, TaskArgs):
    """Settings for the outcome-verification assessment.

    ``task_description`` provides the goal context. ``verification_requirements``
    optionally specifies what the agent should verify before claiming success.
    """

    verification_requirements: tuple[str, ...] = Field(
        default=(),
        description=(
            "Specific results or states the agent should check before claiming "
            "success. When empty, the judge assesses general verification behaviour."
        ),
    )

    @field_validator("verification_requirements")
    @classmethod
    def _no_blank_items(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        blanks = [i for i, s in enumerate(v) if not s.strip()]
        if blanks:
            raise ValueError(f"Blank entries at positions {blanks}.")
        return v


class OutcomeVerificationGrader(Grader[OutcomeVerificationArgs]):
    """Assess whether the agent checks relevant results before claiming success.

    Verification is the checking action; error detection is recognition of an
    error. A successful claim is not evidence that verification occurred.
    """

    args_model = OutcomeVerificationArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.OUTCOME_VERIFICATION,
        scopes=(Scope.SESSION,),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        return (
            "You are assessing whether the agent checks relevant results before "
            "claiming success or taking a dependent action."
            + self.args.task_block()
            + section("verification_requirements", self.args.verification_requirements)
            + "\n\n<assessment_boundaries>\n"
            "Verification is the checking action; error detection is recognition "
            "of an error. A successful claim is not evidence that verification "
            "occurred."
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
