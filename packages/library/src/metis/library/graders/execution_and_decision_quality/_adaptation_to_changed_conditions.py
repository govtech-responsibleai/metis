"""AdaptationToChangedConditionsGrader: whether the agent revises its approach when conditions change."""

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


class AdaptationToChangedConditionsArgs(JudgeArgs, TaskArgs):
    """Settings for the adaptation-to-changed-conditions assessment.

    ``task_description`` provides the goal context. ``changed_conditions`` optionally
    specifies what conditions changed during execution.
    """

    changed_conditions: tuple[str, ...] = Field(
        default=(),
        description=(
            "Specific changes in goals, information, or operating conditions "
            "to assess adaptation against. When empty, the judge identifies "
            "changes from the session evidence."
        ),
    )

    @field_validator("changed_conditions")
    @classmethod
    def _no_blank_items(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        blanks = [i for i, s in enumerate(v) if not s.strip()]
        if blanks:
            raise ValueError(f"Blank entries at positions {blanks}.")
        return v


class AdaptationToChangedConditionsGrader(Grader[AdaptationToChangedConditionsArgs]):
    """Assess whether the agent appropriately revises its approach when conditions change.

    Evaluates adaptation to changed goals, information, or operating conditions.
    Error recovery for repair after an identified failure is a separate concern. A
    session with no observable change in conditions is errored, with the judge's reason.
    """

    args_model = AdaptationToChangedConditionsArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.ADAPTATION_TO_CHANGED_CONDITIONS,
        scopes=(Scope.SESSION,),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        return (
            "You are assessing whether the agent appropriately revises its approach "
            "when goals, information, or operating conditions change."
            + self.args.task_block()
            + section("changed_conditions", self.args.changed_conditions)
            + "\n\n<assessment_boundaries>\n"
            "Do not assess repair after an identified failure — that is error "
            "recovery, not adaptation. This criterion assesses whether the agent "
            "revises its approach when goals, information, or operating conditions "
            "change. If the session contains no observable changes in goals, "
            "information, or operating conditions, the criterion does not apply."
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
