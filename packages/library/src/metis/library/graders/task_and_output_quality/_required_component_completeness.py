"""RequiredComponentCompletenessGrader: whether every required component is present.

Prompt adapted from Arize Phoenix evals completeness classification evaluator
(Arize-ai/phoenix@d5f5e05, js/packages/phoenix-evals/src/__generated__/default_templates/
COMPLETENESS_CLASSIFICATION_EVALUATOR_CONFIG.ts).
Copyright 2025 Arize AI, Inc. Licensed under the Apache License, Version 2.0.
Changed for METIS: kept only the artifact rules and the refusal rules, removed the request
enumeration, the action and withdrawal rules and the output format, and judged one required
component from the settings per call.
See metis/library/EXTERNAL_SOURCES.md for the license text.

Prompt adapted from MLflow completeness
(mlflow/mlflow@ad84197, mlflow/genai/judges/prompts/completeness.py).
Copyright 2018 Databricks, Inc. Licensed under the Apache License, Version 2.0.
Changed for METIS: kept the scope rules, and removed the rules that a refusal with a reason or
a request for missing details is complete, the request listing and the output format.
See metis/library/EXTERNAL_SOURCES.md for the license text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Literal, Self

from pydantic import Field, model_validator

from metis.core.grading import GradingOutput
from metis.core.trace_processing import Problem
from metis.library.aggregation import AGGREGATION_DEFINITIONS
from metis.library.grader import Grader, JudgeArgs
from metis.library.judge import judge
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


class RequiredComponentCompletenessArgs(JudgeArgs, TraceArgs, ArtifactArgs):
    """Settings for the required-component-completeness assessment.

    ``required_components`` is the authoritative list of components. Each component is
    judged on its own, and a result scores 1 only when every component is present. The result
    is errored when no component is missing but one cannot be judged.
    """

    turn: Literal["each", "last"] = "last"
    """``last`` judges only the final reply. ``each`` judges every reply."""
    required_components: tuple[NonEmptyText, ...] = Field(
        min_length=1,
        description="Components that must be present in the assessed evidence.",
    )

    @model_validator(mode="after")
    def _no_duplicate_items(self) -> Self:
        seen: set[str] = set()
        dupes: list[str] = []
        for c in self.required_components:
            normalized = c.strip().lower()
            if normalized in seen:
                dupes.append(c)
            seen.add(normalized)
        if dupes:
            raise ValueError(
                f"Duplicate required components (case-insensitive): {dupes}."
            )
        return self


class RequiredComponentCompletenessGrader(Grader[RequiredComponentCompletenessArgs]):
    """Assess whether every explicitly requested component is present.

    Checks presence only, not correctness or quality. Each component is judged on its own,
    and a result scores 1 only when every component is present. The result scores 0 when any
    component is missing, and is errored when none is missing but one cannot be judged.
    """

    args_model = RequiredComponentCompletenessArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.REQUIRED_COMPONENT_COMPLETENESS,
        scopes=(Scope.TRACE, Scope.ARTIFACT),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.EXPECTED_OUTPUT,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.PASS_IF_ALL,),
    )

    def criteria(self, component: str) -> str:
        return (
            "You are an expert evaluator labeling whether the assessed evidence contains "
            "one explicitly required component."
            f"\n\n<required_component>\n{component}\n</required_component>"
            "\n\nArtifacts\n"
            "- The assistant must deliver the requested artifact.\n"
            "- The artifact must contain every component the user explicitly required.\n"
            "- Do not judge general quality beyond those explicit requirements.\n\n"
            "Answers\n"
            "- Saying the requested fact is absent, unknown, or not in the "
            "source/context is not an answer.\n"
            '- A refusal or "I don\'t know" is likewise not fulfilment.\n\n'
            "Score 1 when the required component is present. Score 0 when it is "
            "absent, or when the assistant refused, said it does not know, or said the "
            "requested fact is absent or unknown in place of the component."
            "\n\n<assessment_boundaries>\n"
            "Do not evaluate factual correctness, style, or usefulness beyond whether "
            "the required component was directly handled. "
            "Do not make assumptions or bring in external knowledge. "
            "Assess the PRESENCE of each required component, independently of its "
            "correctness or quality. A component that is present but contains errors "
            "still counts as present. A component that is absent or cannot be identified "
            "is not present, and scores 0."
            "\n</assessment_boundaries>"
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
                await judge(self, llm, label, evidence, self.criteria(component))
                for component in self.args.required_components
            ]
            results.append(combine(per_rule, label))
        return GradingOutput(results=results)
