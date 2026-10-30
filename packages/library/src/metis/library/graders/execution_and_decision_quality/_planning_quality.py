"""PlanningQualityGrader: whether the proposed sequence of actions is feasible and sufficient.

Prompt adapted from DeepEval plan quality
(confident-ai/deepeval@d6cd78a, deepeval/metrics/plan_quality/templates/evaluate_plan_quality.txt).
Copyright 2024 Confident AI Inc. Licensed under the Apache License, Version 2.0.
Changed for METIS: kept the completeness and logical coherence criteria and one alignment
sentence, removed the efficiency and level-of-detail criteria, and mapped the five-level scale to
a binary score. The JSON output format is removed.
See metis/library/EXTERNAL_SOURCES.md for the license text.
"""

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


class PlanningQualityArgs(JudgeArgs, TaskArgs):
    """Settings for the planning-quality assessment.

    ``task_description`` provides the goal context. ``plan_requirements`` optionally
    specifies aspects to assess such as feasibility, ordering, or dependency handling.
    """

    plan_requirements: tuple[str, ...] = Field(
        default=(),
        description=(
            "Specific aspects to assess such as feasibility, sufficiency, ordering, "
            "or dependency handling. When empty, the judge assesses general plan quality."
        ),
    )

    @field_validator("plan_requirements")
    @classmethod
    def _no_blank_items(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        blanks = [i for i, s in enumerate(v) if not s.strip()]
        if blanks:
            raise ValueError(f"Blank entries at positions {blanks}.")
        return v


class PlanningQualityGrader(Grader[PlanningQualityArgs]):
    """Assess whether the proposed sequence of actions is feasible and sufficient.

    Evaluates the observable plan for feasibility, sufficiency, ordering, and
    dependency handling. A plan need not expose an argument for this assessment. A
    session with no observable plan is errored, with the judge's reason.
    """

    args_model = PlanningQualityArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.PLANNING_QUALITY,
        scopes=(Scope.SESSION,),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        return (
            "You are assessing whether the proposed sequence of actions is feasible "
            "and sufficient to reach the goal."
            + self.args.task_block()
            + section("plan_requirements", self.args.plan_requirements)
            + "\n\n<criteria>\n"
            "The plan is the plan the agent shows in the evidence.\n\n"
            "1. Completeness (Most Important)\n"
            "- The plan must fully address all major requirements of the user task.\n"
            "- Missing even one critical subtask or dependency should reduce the score "
            "sharply.\n"
            "- The plan must include all prerequisite actions necessary for the final "
            "outcome.\n\n"
            "2. Logical Coherence\n"
            "- Steps must follow a clear, rational sequence that leads directly to "
            "completing the task.\n"
            "- Disordered, redundant, or circular reasoning should be penalized heavily.\n"
            "- Every step must have a clear purpose; no filler or irrelevant actions.\n\n"
            "The plan must explicitly and directly target the user's stated goal."
            "\n</criteria>"
            "\n\n<scoring>\n"
            "Score 1 for a plan that is complete and logically ordered: it covers all, "
            "or nearly all, aspects of the task with clear logic, and any gaps are minor "
            "and do not block task completion. Score 0 for a plan with missing critical "
            "steps or disordered logic."
            "\n</scoring>" + "\n\n<assessment_boundaries>\n"
            "Assess feasibility, sufficiency, ordering, or dependencies from the "
            "observable plan. A plan need not expose an argument. Do not assess "
            "whether the plan's reasoning is logically valid; only assess whether "
            "the proposed actions are feasible and sufficient. If the session "
            "contains no observable plan or sequence of proposed actions, the "
            "criterion does not apply."
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
