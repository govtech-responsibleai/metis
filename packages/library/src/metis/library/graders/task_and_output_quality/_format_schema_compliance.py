"""FormatSchemaComplianceGrader: whether an output satisfies structural and syntactic requirements."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, ClassVar, Literal, Self

from pydantic import Field, field_validator, model_validator

from metis.core.grading import GraderResult, GradingOutput
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

if TYPE_CHECKING:
    from pathlib import Path

    from metis.core.specification import Specification
    from metis.core.trace_processing import Turn
    from metis.core.traces import GradingInput
    from metis.library.grader import LLMSettings


class FormatSchemaComplianceArgs(JudgeArgs, TraceArgs, ArtifactArgs):
    """Settings for the format-and-schema-compliance assessment.

    At least one of ``format_requirements`` or ``json_schema_spec`` must be provided.
    When only ``json_schema_spec`` is set, the assessment is purely deterministic and
    makes no LLM call.
    """

    turn: Literal["each", "last"] = "last"
    """``last`` judges only the final reply. ``each`` judges every reply."""
    format_requirements: tuple[str, ...] = Field(
        default=(),
        description="Prose structural or syntactic requirements the output must satisfy.",
    )
    json_schema_spec: str | None = Field(
        default=None,
        description=(
            "JSON Schema as a JSON string. When provided, the reply or file is validated "
            "deterministically against the schema. Invalid JSON or a schema violation "
            "scores 0 without an LLM call."
        ),
    )

    @field_validator("format_requirements")
    @classmethod
    def _no_blank_requirements(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        blanks = [i for i, s in enumerate(v) if not s.strip()]
        if blanks:
            raise ValueError(f"Blank format requirements at positions {blanks}.")
        return v

    @model_validator(mode="after")
    def _at_least_one_requirement(self) -> Self:
        if not self.format_requirements and self.json_schema_spec is None:
            raise ValueError(
                "At least one of format_requirements or json_schema_spec must be provided."
            )
        return self


def _output_text(thing: tuple[Turn, ...] | Path | Problem) -> str | Problem:
    """The text to validate: the selected turn's reply, or the selected file's contents."""
    if isinstance(thing, Problem):
        return thing
    if isinstance(thing, tuple):
        return thing[-1].reply
    try:
        return thing.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return Problem(
            kind="unsupported",
            detail=f"The file {thing.name} cannot be read as UTF-8 text: {exc}",
        )


def _schema_failure(text: str, schema_spec: str, label: str) -> GraderResult | None:
    """A scored-0 or errored result when ``text`` fails the schema, or ``None`` when it passes."""
    import jsonschema

    try:
        instance = json.loads(text)
    except json.JSONDecodeError as exc:
        return GraderResult(
            status="scored",
            score=0.0,
            reason=f"The output is not valid JSON: {exc}",
            scope=label,
        )
    try:
        jsonschema.validate(instance=instance, schema=json.loads(schema_spec))
    except jsonschema.ValidationError as exc:
        return GraderResult(
            status="scored",
            score=0.0,
            reason=f"JSON Schema violation: {exc.message}",
            scope=label,
        )
    except jsonschema.SchemaError as exc:
        return GraderResult(
            status="errored", reason=f"Invalid JSON Schema: {exc.message}", scope=label
        )
    return None


class FormatSchemaComplianceGrader(Grader[FormatSchemaComplianceArgs]):
    """Assess whether an output satisfies specified structural and syntactic requirements.

    When ``json_schema_spec`` is provided, each judged reply or file is validated
    deterministically against the JSON Schema first. Invalid JSON or a schema violation
    scores 0.0 without an LLM call. An LLM verdict cannot override a deterministic schema
    failure. A reply or file that cannot be read is errored, with the reason.

    When only ``json_schema_spec`` is set (no prose ``format_requirements``), a successful
    deterministic validation scores 1.0 with no LLM call.

    When ``format_requirements`` are also set, the LLM assesses those after schema
    validation passes.
    """

    args_model = FormatSchemaComplianceArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.FORMAT_AND_SCHEMA_COMPLIANCE,
        scopes=(Scope.TRACE, Scope.ARTIFACT),
        grader_types=(GraderType.LLM, GraderType.DETERMINISTIC),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    @classmethod
    def check_setup(
        cls, args: FormatSchemaComplianceArgs, spec: Specification
    ) -> list[str]:
        errors: list[str] = []
        if args.json_schema_spec is not None:
            try:
                schema = json.loads(args.json_schema_spec)
            except (json.JSONDecodeError, TypeError):
                errors.append(
                    "json_schema_spec is not valid JSON. "
                    "Provide a valid JSON Schema string or omit it."
                )
                return errors
            import jsonschema

            try:
                jsonschema.Draft202012Validator.check_schema(schema)
            except jsonschema.SchemaError as exc:
                errors.append(
                    f"json_schema_spec is not a valid JSON Schema: {exc.message}"
                )
        return errors

    def criteria(self) -> str:
        schema_note = (
            "\n\nThe output has already passed deterministic JSON Schema validation. "
            "Do not re-check JSON validity or schema structure."
            if self.args.json_schema_spec is not None
            else ""
        )
        return (
            "You are assessing whether the target response satisfies specified "
            "structural and syntactic requirements."
            + section("format_requirements", self.args.format_requirements)
            + schema_note
            + "\n\n<assessment_boundaries>\n"
            "Assess syntax and structure. This criterion covers format compliance even "
            "when the requirement comes from a policy or task instruction. "
            "Do not assess substantive correctness or content quality."
            "\n</assessment_boundaries>"
        )

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        scope = SCOPE_DEFINITIONS[self.scope]
        selected = scope.select(input, self.args)
        if isinstance(selected, Problem):
            return GradingOutput.errored(selected.detail)
        schema_spec = self.args.json_schema_spec
        results: list[GraderResult] = []
        for label, thing in selected.items():
            if schema_spec is not None:
                text = _output_text(thing)
                if isinstance(text, Problem):
                    results.append(
                        GraderResult(status="errored", reason=text.detail, scope=label)
                    )
                    continue
                if failure := _schema_failure(text, schema_spec, label):
                    results.append(failure)
                    continue
                if not self.args.format_requirements:
                    results.append(
                        GraderResult(
                            status="scored",
                            score=1.0,
                            reason="The output passes JSON Schema validation.",
                            scope=label,
                        )
                    )
                    continue
            results.append(
                await judge(self, llm, label, scope.render(thing), self.criteria())
            )
        return GradingOutput(results=results)
