"""TaskSuccessGrader: whether the requested end goal was achieved.

Prompt adapted from DeepEval task completion
(confident-ai/deepeval@d6cd78a, deepeval/metrics/task_completion/templates/
extract_task_and_outcome_from_trace.txt and
deepeval/metrics/task_completion/templates/generate_verdict.txt).
Copyright 2024 Confident AI Inc. Licensed under the Apache License, Version 2.0.
Changed for METIS: the two DeepEval calls (extract the task and outcome, then score 0 to 1) are
one call with the extraction as first steps, and the score is binary. The trace JSON example and
the JSON output format are removed.
See metis/library/EXTERNAL_SOURCES.md for the license text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Self

from pydantic import Field, field_validator, model_validator

from metis.core.grading import GradingOutput
from metis.core.trace_processing import Problem
from metis.library.grader import Grader, JudgeArgs
from metis.library.judge import TaskArgs, judge, section
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

if TYPE_CHECKING:
    from metis.core.traces import GradingInput
    from metis.library.grader import LLMSettings


class TaskSuccessArgs(JudgeArgs, ArtifactArgs, TaskArgs):
    """Settings for the task-success assessment.

    ``task_description`` and ``success_conditions`` are the assessment criteria, set in the
    specification. When ``task_description`` is unset, the judge infers the goal from the
    user's messages. A file has no user messages, so the artifact scope needs at least one
    of the two, and without ``task_description`` the judge uses the success conditions only.
    """

    success_conditions: tuple[str, ...] = Field(
        default=(),
        description=(
            "Observable conditions that define success. When empty, "
            "the judge infers conditions from the task description."
        ),
    )

    @field_validator("success_conditions")
    @classmethod
    def _no_blank_conditions(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        blanks = [i for i, s in enumerate(v) if not s.strip()]
        if blanks:
            raise ValueError(f"Blank success conditions at positions {blanks}.")
        return v

    @model_validator(mode="after")
    def _artifact_needs_a_goal(self) -> Self:
        if (
            self.scope == Scope.ARTIFACT
            and self.task_description is None
            and not self.success_conditions
        ):
            raise ValueError(
                "The artifact scope needs task_description or success_conditions, "
                "because a file has no user messages to infer the goal from."
            )
        return self


class TaskSuccessGrader(Grader[TaskSuccessArgs]):
    """Assess whether the requested end goal was achieved under declared success conditions.

    For action tasks, requires recorded outcome evidence (tool results, state changes);
    an agent's claim of completion alone is insufficient. The evidence includes tool
    results so the judge can verify that actions actually happened. Under the artifact
    scope, the judge sees only the file and judges whether the file meets the goal.
    """

    args_model = TaskSuccessArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.TASK_SUCCESS,
        scopes=(Scope.SESSION, Scope.ARTIFACT),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        return (
            "You are assessing whether the requested end goal was achieved."
            + self._task_block()
            + section("success_conditions", self.args.success_conditions)
            + self._steps()
            + "\n\n<assessment_boundaries>\n"
            "Assess whether the declared end goals and mandatory conditions were achieved. "
            + self._evidence_rule()
            + "\n</assessment_boundaries>"
        )

    def _steps(self) -> str:
        if self.scope == Scope.ARTIFACT:
            task = "1. Identify the task: the goal and success conditions given above."
            outcome = (
                "2. Describe the outcome: a strictly factual description of what the "
                "file contains, based only on the file."
            )
            enumerate_ = "Enumerate each relevant part of the file, in plain language."
        else:
            task = (
                "1. Identify the task: the task or objective expressed by the user, "
                "together with any task description and success conditions given above."
            )
            outcome = (
                "2. Describe the outcome: a strictly factual description of what the "
                "system did, based only on the evidence."
            )
            enumerate_ = (
                "Enumerate each relevant action or output the evidence shows, in plain "
                "language."
            )
        return (
            "\n\n<steps>\n"
            "Follow these steps before you score.\n"
            f"{task}\n"
            f"{outcome} The outcome should be solely factual, derived strictly from the "
            'evidence. Do not include subjective language such as "successfully", '
            f'"efficiently", or "well". {enumerate_}\n'
            "3. Compare how well the actual outcome aligns with the desired task. "
            "Score 1 only when the actual outcome achieves the task and every success "
            "condition. Otherwise, score 0."
            "\n</steps>"
        )

    def _task_block(self) -> str:
        if self.scope == Scope.ARTIFACT and self.args.task_description is None:
            return (
                "\n\nNo task description is given. Judge the file against the "
                "success conditions only."
            )
        return self.args.task_block()

    def _evidence_rule(self) -> str:
        if self.scope == Scope.ARTIFACT:
            return (
                "Judge only the attached file. It is the only evidence, so decide "
                "whether the file itself achieves the goal."
            )
        return (
            "For action tasks, require recorded outcome evidence such as tool results that "
            "show state changes or confirmations from external systems. An agent's claim of "
            'completion alone (e.g. "I have completed the task") is insufficient without '
            "supporting evidence in tool results or system responses. "
            "For answer-only tasks, a correct and complete answer may establish success."
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
