"""OutputCorrectnessGrader: whether an answer or deliverable is substantively correct.

Prompt adapted from MLflow correctness
(mlflow/mlflow@ad84197, mlflow/genai/judges/prompts/correctness.py).
Copyright 2018 Databricks, Inc. Licensed under the Apache License, Version 2.0.
Changed for METIS: checked the response against the correctness conditions in the settings
in place of expected facts, removed the rule not to focus on correctness, the step-by-step
rationale rule and the output format.
See metis/library/EXTERNAL_SOURCES.md for the license text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Literal

from pydantic import Field, field_validator

from metis.core.grading import GradingOutput
from metis.core.trace_processing import Problem
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


class OutputCorrectnessArgs(JudgeArgs, TraceArgs, ArtifactArgs):
    """Settings for the output-correctness assessment.

    ``correctness_conditions`` is the authoritative list of correctness criteria.
    """

    turn: Literal["each", "last"] = "last"
    """``last`` judges only the final reply. ``each`` judges every reply."""
    correctness_conditions: tuple[NonEmptyText, ...] = Field(
        min_length=1,
        description="Conditions that define substantive correctness of the output.",
    )

    @field_validator("correctness_conditions")
    @classmethod
    def _no_blank_conditions(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        blanks = [i for i, s in enumerate(v) if not s.strip()]
        if blanks:
            raise ValueError(f"Blank correctness conditions at positions {blanks}.")
        return v


class OutputCorrectnessGrader(Grader[OutputCorrectnessArgs]):
    """Assess whether an answer or deliverable is substantively correct.

    Evaluates against explicit correctness conditions. A correct output does not
    establish that an external action occurred.
    """

    args_model = OutputCorrectnessArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.OUTPUT_CORRECTNESS,
        scopes=(Scope.TRACE, Scope.ARTIFACT),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        return (
            "You are assessing whether the target response is substantively correct."
            + section("correctness_conditions", self.args.correctness_conditions)
            + "\n\nYou must determine whether the response satisfies every correctness "
            "condition above. Do not make assumptions, approximations, or bring in "
            "external knowledge."
            "\n\nScore 1 only if the response satisfies every correctness condition, "
            "and score 0 otherwise. If any condition is not met, state in the reason "
            "which condition fails." + "\n\n<assessment_boundaries>\n"
            "Assess substantive correctness of the assessed evidence under the explicit "
            "correctness conditions above. A correct answer does not establish that an "
            "external action was completed. Focus on whether the content of the response "
            "is correct, not on whether the broader task was completed. "
            "Earlier messages or user-supplied content are not part of the assessed output."
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
