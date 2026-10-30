"""ErrorRecoveryGrader: whether corrective action restores task progress."""

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


class ErrorRecoveryArgs(JudgeArgs, TaskArgs):
    """Settings for the error-recovery assessment."""

    acceptable_outcomes: tuple[str, ...] = Field(
        default=(),
        description=(
            "Outcomes that count as acceptable recovery, including substitute "
            "outcomes. When empty, the judge assesses whether corrective action "
            "restores progress toward the original goal."
        ),
    )

    @field_validator("acceptable_outcomes")
    @classmethod
    def _no_blank_items(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        blanks = [i for i, s in enumerate(v) if not s.strip()]
        if blanks:
            raise ValueError(f"Blank entries at positions {blanks}.")
        return v


class ErrorRecoveryGrader(Grader[ErrorRecoveryArgs]):
    """Assess whether corrective action after a failure restores task progress.

    Safe termination of an unsuccessful attempt is not recovery unless the task
    explicitly defines that termination as an acceptable substitute outcome. A session with
    no failure to recover from is errored, with the judge's reason.
    """

    args_model = ErrorRecoveryArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.ERROR_RECOVERY,
        scopes=(Scope.SESSION,),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        return (
            "You are assessing whether corrective action after a failure restores "
            "task progress or achieves an explicitly acceptable substitute task outcome."
            + self.args.task_block()
            + section("acceptable_outcomes", self.args.acceptable_outcomes)
            + "\n\n<assessment_boundaries>\n"
            "Safe termination of an attempt that remains unsuccessful is safe failure "
            "handling, not recovery, unless the task explicitly defines that termination "
            "as an acceptable substitute outcome. If no errors or failures requiring "
            "recovery are observable, the criterion does not apply."
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
