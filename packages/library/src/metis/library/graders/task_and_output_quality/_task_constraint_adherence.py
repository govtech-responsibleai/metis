"""TaskConstraintAdherenceGrader: whether explicit constraints were respected.

Prompt adapted from MLflow guidelines judge
(mlflow/mlflow@ad84197, mlflow/genai/judges/prompts/guidelines.py).
Copyright 2018 Databricks, Inc. Licensed under the Apache License, Version 2.0.
Changed for METIS: the judge assesses one constraint for each call, and a constraint that the
evidence cannot decide is not applicable, where MLflow passes a guideline that does not apply.
The JSON output format is replaced by the shared judge instructions.
See metis/library/EXTERNAL_SOURCES.md for the license text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Self

from pydantic import Field, field_validator, model_validator

from metis.core.grading import GradingOutput
from metis.core.trace_processing import Problem
from metis.library.aggregation import AGGREGATION_DEFINITIONS
from metis.library.grader import Grader, JudgeArgs
from metis.library.judge import judge
from metis.library.scope import SCOPE_DEFINITIONS, ArtifactArgs
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


class TaskConstraintAdherenceArgs(JudgeArgs, ArtifactArgs):
    """Settings for the task-constraint-adherence assessment.

    ``constraints`` is the authoritative list of restrictions. Each constraint is judged on
    its own, and a result scores 1 only when every constraint is met. The result is errored when
    no constraint failed but one cannot be judged.
    """

    constraints: tuple[NonEmptyText, ...] = Field(
        min_length=1,
        description="Explicit execution or presentation restrictions to check.",
    )

    @field_validator("constraints")
    @classmethod
    def _no_blank_items(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        blanks = [i for i, s in enumerate(v) if not s.strip()]
        if blanks:
            raise ValueError(f"Blank entries at positions {blanks}.")
        return v

    @model_validator(mode="after")
    def _no_duplicate_items(self) -> Self:
        seen: set[str] = set()
        dupes: list[str] = []
        for c in self.constraints:
            normalized = c.strip().lower()
            if normalized in seen:
                dupes.append(c)
            seen.add(normalized)
        if dupes:
            raise ValueError(
                f"Duplicate constraints (case-insensitive): {dupes}. "
                "Duplicates would change weighting."
            )
        return self


class TaskConstraintAdherenceGrader(Grader[TaskConstraintAdherenceArgs]):
    """Assess whether explicit execution or presentation restrictions were respected.

    Constraints are restrictions (limits, prohibitions, format rules), not task
    requirements. Each constraint is judged on its own, and the results are combined
    by ``pass_if_all``: a result scores 0 when any constraint is not met, is errored
    when no constraint failed but one cannot be judged, and scores 1 otherwise. The
    session evidence includes tool results for execution constraints. Under the artifact
    scope, the judge looks only at the file.
    """

    args_model = TaskConstraintAdherenceArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.TASK_CONSTRAINT_ADHERENCE,
        scopes=(Scope.SESSION, Scope.ARTIFACT),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.POLICY_RULE,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.PASS_IF_ALL,),
    )

    def criteria(self, constraint: str) -> str:
        return (
            "Given the following constraint and the assessed evidence, please assess "
            "whether the evidence fully complies with the provided constraint. Only "
            "focus on the provided constraint and not the correctness, relevance, or "
            "effectiveness of the evidence. The constraint is one explicit restriction "
            "on task execution or response presentation."
            f"\n\n<constraint>\n{constraint}\n</constraint>"
            "\n\nScore 0 if the constraint is not satisfied, and state which parts of "
            "the constraint are not satisfied in your reason. Score 1 if the constraint "
            "is satisfied."
            "\n\n<assessment_boundaries>\n"
            "Assess explicit execution or presentation restrictions. Constraints are "
            "restrictions such as limits, prohibitions, required formats, and permitted "
            "resources. Do not treat a request to include something as a constraint "
            "(that is a required component, not a restriction). "
            + self._evidence_rule()
            + "If the evidence is genuinely insufficient to decide the constraint, the "
            "criterion does not apply."
            "\n</assessment_boundaries>"
        )

    def _evidence_rule(self) -> str:
        if self.scope == Scope.ARTIFACT:
            return (
                "Judge only the attached file. A constraint on how the "
                "agent worked, such as spending or timing, cannot be decided from the "
                "file. "
            )
        return (
            "Look for evidence in tool call arguments, tool results, and agent responses. "
            "A constraint on spending, timing, or resource use may be established solely "
            "by tool results even when the agent does not mention it in conversation. "
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
                await judge(self, llm, label, evidence, self.criteria(constraint))
                for constraint in self.args.constraints
            ]
            results.append(combine(per_rule, label))
        return GradingOutput(results=results)
