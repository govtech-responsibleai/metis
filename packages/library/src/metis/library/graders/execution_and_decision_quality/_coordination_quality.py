"""CoordinationQualityGrader: whether agents appropriately delegate and reconcile."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from pydantic import Field, field_validator

from metis.core.grading import GradingOutput
from metis.core.trace_processing import Problem, turns
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


class CoordinationQualityArgs(JudgeArgs, TaskArgs):
    """Settings for the coordination-quality assessment.

    ``task_description`` provides the goal context. ``coordination_requirements``
    optionally specifies expected coordination behaviour such as delegation,
    information sharing, or dependency handling.
    """

    coordination_requirements: tuple[str, ...] = Field(
        default=(),
        description=(
            "Expected coordination behaviour such as delegation, information "
            "sharing, or dependency handling. When empty, the judge assesses "
            "general coordination quality."
        ),
    )

    @field_validator("coordination_requirements")
    @classmethod
    def _no_blank_items(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        blanks = [i for i, s in enumerate(v) if not s.strip()]
        if blanks:
            raise ValueError(f"Blank entries at positions {blanks}.")
        return v


class CoordinationQualityGrader(Grader[CoordinationQualityArgs]):
    """Assess whether agents appropriately delegate, share information, and reconcile.

    Evaluates inter-agent coordination behaviour. Agent configuration describes the
    setting only. A session with no recorded agent delegation is errored. A session
    the judge finds has no coordination is errored, with the judge's reason.
    """

    args_model = CoordinationQualityArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.COORDINATION_QUALITY,
        scopes=(Scope.SESSION,),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        return (
            "You are assessing whether agents appropriately delegate, share "
            "information, handle dependencies, and reconcile their contributions."
            + self.args.task_block()
            + section("coordination_requirements", self.args.coordination_requirements)
            + "\n\n<assessment_boundaries>\n"
            "Assess inter-agent coordination behaviour: delegation, information "
            "sharing, dependency handling, and contribution reconciliation. The "
            "presence of multiple agents in the configuration is not evidence of "
            "coordination; assess observable coordination actions. If the session "
            "involves only a single agent with no delegation or coordination, "
            "the criterion does not apply."
            "\n</assessment_boundaries>"
        )

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        scope = SCOPE_DEFINITIONS[self.scope]
        selected = scope.select(input, self.args)
        if isinstance(selected, Problem):
            return GradingOutput.errored(selected.detail)
        if not any(
            call.agent for turn in turns(input.traces) for call in turn.tool_calls
        ):
            return GradingOutput.errored(
                "The session records no agent delegation, so coordination quality "
                "cannot be assessed."
            )
        return GradingOutput(
            results=[
                await judge(self, llm, label, scope.render(thing), self.criteria())
                for label, thing in selected.items()
            ]
        )
