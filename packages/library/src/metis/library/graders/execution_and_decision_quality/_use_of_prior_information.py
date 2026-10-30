"""UseOfPriorInformationGrader: whether relevant earlier facts are retrieved and applied.

Prompt adapted from MLflow knowledge retention
(mlflow/mlflow@ad84197, mlflow/genai/judges/prompts/knowledge_retention.py).
Copyright 2018 Databricks, Inc. Licensed under the Apache License, Version 2.0.
Changed for METIS: the judge assesses each agent response in the session against information
given earlier in the session from any source, not only the last response against facts the
user gave. Guidelines 1 and 6, the yes and no labels and the template variable are removed.
See metis/library/EXTERNAL_SOURCES.md for the license text.

Prompt adapted from DeepEval knowledge retention
(confident-ai/deepeval@d6cd78a,
deepeval/metrics/knowledge_retention/templates/generate_verdict.txt).
Copyright 2024 Confident AI Inc. Licensed under the Apache License, Version 2.0.
Changed for METIS: only rules 2 and 3 are kept, on repeated questions and on requests for
clarification. The JSON output format, the examples and the template variables are removed.
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


class UseOfPriorInformationArgs(JudgeArgs, TaskArgs):
    """Settings for the use-of-prior-information assessment.

    ``task_description`` provides the goal context. ``prior_information`` optionally
    specifies earlier facts or instructions that should be retrieved and applied.
    """

    prior_information: tuple[str, ...] = Field(
        default=(),
        description=(
            "Earlier facts, instructions, or experiences that should be retrieved "
            "and applied. When empty, the judge assesses general retrieval and "
            "application of prior information."
        ),
    )

    @field_validator("prior_information")
    @classmethod
    def _no_blank_items(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        blanks = [i for i, s in enumerate(v) if not s.strip()]
        if blanks:
            raise ValueError(f"Blank entries at positions {blanks}.")
        return v


class UseOfPriorInformationGrader(Grader[UseOfPriorInformationArgs]):
    """Assess whether relevant earlier facts, instructions, or experiences are
    retrieved and applied appropriately.

    Judges retrieval and application of prior information, separate from observing
    or updating current state.
    """

    args_model = UseOfPriorInformationArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.USE_OF_PRIOR_INFORMATION,
        scopes=(Scope.SESSION,),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        return (
            "You are assessing whether relevant earlier facts, instructions, or "
            "experiences are retrieved and applied appropriately."
            + self.args.task_block()
            + section("prior_information", self.args.prior_information)
            + "\n\nEvaluate each agent response in the session and determine if it:\n"
            "- Correctly uses or references information given earlier in the session\n"
            "- Avoids contradicting information given earlier in the session\n"
            "- Accurately recalls details without distortion\n\n"
            "Score 0 if an agent response:\n"
            "- Contradicts information given earlier in the session\n"
            "- Misrepresents or inaccurately recalls information given earlier in the "
            "session\n"
            "- Forgets or ignores information that is directly relevant to answering the "
            "current request\n"
            '- Asks for information that is already known (for example, "Where do you '
            'live?" when the address is already provided)\n\n'
            "IMPORTANT GUIDELINES:\n"
            "- Focus on factual information (names, dates, preferences, context) rather "
            "than opinions\n"
            "- Not all prior information needs to be referenced in every response - only "
            "evaluate information that is directly relevant to the current request\n"
            "- If the agent doesn't reference prior information because it's not relevant "
            "to the current turn, that's acceptable\n"
            "- If the agent is asking for clarification, confirmation, or correction of "
            "known facts, that is not a failure\n"
            "- Only score 0 if there's a clear contradiction, distortion, or problematic "
            "forgetting of information that should have been used, or a repeated question "
            "for information that is already known\n\n"
            "Base your judgment strictly on the session content provided. Do not use "
            "outside knowledge.\n\n<assessment_boundaries>\n"
            "Judge retrieval and application of earlier facts and instructions. "
            "Separate from observing or updating current state. Score 1 when no "
            "earlier information is relevant, or when the agent uses it correctly."
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
