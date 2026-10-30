"""The Grader contract: args models, the args_model/type-argument check, the taxonomy settings
and declaration checks, and grade()."""

from __future__ import annotations

import asyncio
import math
from typing import TYPE_CHECKING, ClassVar, Generic, TypeVar
from unittest.mock import MagicMock

import pytest
import yaml
from pydantic import Field, ValidationError

from metis.core.grading import GraderResult, GradingOutput
from metis.core.specification import Specification
from metis.core.traces import GradingInput
from metis.library.grader import Grader, GraderArgs, JudgeArgs, LLMSettings
from metis.library.scope import ArtifactArgs, TraceArgs
from metis.library.taxonomy import (
    Aggregation,
    GraderTaxonomy,
    GraderType,
    JudgmentForm,
    ReferenceType,
    Scope,
)

if TYPE_CHECKING:
    from openai import AsyncOpenAI


class FontSizeArgs(GraderArgs):
    min_pt: int = Field(default=18, ge=1)


class FontSizeGrader(Grader[FontSizeArgs]):
    """A worked example of a grader."""

    args_model = FontSizeArgs

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        return GradingOutput(
            results=[
                GraderResult(
                    status="scored", score=1.0, reason=f"min {self.args.min_pt}pt"
                )
            ]
        )


def _llm() -> LLMSettings:
    client: AsyncOpenAI = MagicMock()
    return LLMSettings(client=client)


class TestGraderArgs:
    """The validation table from issue #428, 'Example: a grader and its criteria'."""

    def test_override(self) -> None:
        assert FontSizeArgs.model_validate({"min_pt": 24}) == FontSizeArgs(
            min_pt=24, threshold=0.5
        )

    def test_defaults(self) -> None:
        args = FontSizeArgs.model_validate({})
        assert (args.min_pt, args.threshold) == (18, 0.5)

    def test_misspelt_arg_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="min_pts"):
            FontSizeArgs.model_validate({"min_pts": 24})

    def test_mistyped_arg_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="valid integer"):
            FontSizeArgs.model_validate({"min_pt": "large"})

    @pytest.mark.parametrize("threshold", [-0.1, 1.5, math.nan])
    def test_out_of_range_threshold_is_rejected(self, threshold: float) -> None:
        with pytest.raises(ValidationError, match="threshold"):
            FontSizeArgs.model_validate({"threshold": threshold})

    @pytest.mark.parametrize(
        "raw", ["threshold: yes", "threshold: true", "threshold: '0.8'"]
    )
    def test_yaml_booleans_and_strings_are_not_thresholds(self, raw: str) -> None:
        """YAML reads ``yes``/``true`` as booleans; a lax float would take them as 1.0."""
        with pytest.raises(ValidationError, match="threshold"):
            GraderArgs.model_validate(yaml.safe_load(raw))

    @pytest.mark.parametrize(
        ("raw", "expected"), [("threshold: 1", 1.0), ("threshold: 0", 0.0)]
    )
    def test_yaml_integers_are_still_thresholds(
        self, raw: str, expected: float
    ) -> None:
        assert GraderArgs.model_validate(yaml.safe_load(raw)).threshold == expected

    @pytest.mark.parametrize("threshold", [0.0, 1.0])
    def test_threshold_bounds_are_inclusive(self, threshold: float) -> None:
        assert GraderArgs(threshold=threshold).threshold == threshold

    def test_args_are_frozen(self) -> None:
        args = FontSizeArgs()
        with pytest.raises(ValidationError):
            args.min_pt = 30

    def test_dump_includes_defaults(self) -> None:
        """GraderRecord.grader_args records defaults, so the dump must include them."""
        assert FontSizeArgs.model_validate({}).model_dump() == {
            "threshold": 0.5,
            "min_pt": 18,
        }


class TestJudgeArgs:
    def test_model_is_required(self) -> None:
        with pytest.raises(ValidationError, match="model"):
            JudgeArgs.model_validate({})

    def test_model_and_threshold(self) -> None:
        args = JudgeArgs.model_validate({"model": "gpt-4o", "threshold": 0.8})
        assert (args.model, args.threshold) == ("gpt-4o", 0.8)

    @pytest.mark.parametrize("model", ["", "   "])
    def test_blank_model_is_rejected(self, model: str) -> None:
        with pytest.raises(ValidationError, match="model"):
            JudgeArgs.model_validate({"model": model})

    def test_model_is_stripped(self) -> None:
        assert JudgeArgs.model_validate({"model": " gpt-4o "}).model == "gpt-4o"


class TestSubclassCheck:
    def test_matching_args_model_is_accepted(self) -> None:
        assert FontSizeGrader.args_model is FontSizeArgs

    def test_mismatched_args_model_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="args_model = FontSizeArgs"):

            class _Wrong(Grader[FontSizeArgs]):
                args_model = GraderArgs

                async def grade(
                    self, input: GradingInput, llm: LLMSettings
                ) -> GradingOutput:
                    raise NotImplementedError

    def test_missing_args_model_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="args_model = FontSizeArgs"):

            class _Missing(Grader[FontSizeArgs]):
                async def grade(
                    self, input: GradingInput, llm: LLMSettings
                ) -> GradingOutput:
                    raise NotImplementedError

    def test_bare_grader_subclass_is_rejected(self) -> None:
        with pytest.raises(TypeError, match=r"Grader\[ItsArgsModel\]"):

            class _Bare(Grader):
                args_model = GraderArgs

                async def grade(
                    self, input: GradingInput, llm: LLMSettings
                ) -> GradingOutput:
                    raise NotImplementedError

    def test_generic_intermediate_base_is_checked_at_its_subclass(self) -> None:
        A = TypeVar("A", bound=GraderArgs)

        class _Family(Grader[A], Generic[A]):
            async def grade(
                self, input: GradingInput, llm: LLMSettings
            ) -> GradingOutput:
                raise NotImplementedError

        class _Member(_Family[FontSizeArgs]):
            args_model = FontSizeArgs

        assert _Member.args_model is FontSizeArgs

    def test_subclass_of_a_concrete_grader_inherits_its_args_model(self) -> None:
        class _Stricter(FontSizeGrader):
            pass

        assert _Stricter.args_model is FontSizeArgs

    def test_grader_without_grade_cannot_be_built(self) -> None:
        class _NoGrade(Grader[FontSizeArgs]):
            args_model = FontSizeArgs

        with pytest.raises(TypeError, match="abstract"):
            _NoGrade(FontSizeArgs())


class TestGrade:
    def test_grade_is_async_and_reads_its_args(self) -> None:
        grader = FontSizeGrader(FontSizeArgs(min_pt=24))
        out = asyncio.run(grader.grade(GradingInput(traces=()), _llm()))
        assert out.results[0].reason == "min 24pt"

    def test_check_setup_defaults_to_no_errors(self) -> None:
        spec = Specification.model_validate(
            {"target": {"name": "T", "users": "U", "description": "D"}}
        )
        assert FontSizeGrader.check_setup(FontSizeArgs(), spec) == []

    def test_llm_settings_is_frozen(self) -> None:
        llm = _llm()
        with pytest.raises(AttributeError):
            llm.client = MagicMock()


def _taxonomy(**overrides: object) -> GraderTaxonomy:
    fields: dict[str, object] = {
        "measure": None,
        "scopes": (Scope.TRACE, Scope.ARTIFACT),
        "grader_types": (GraderType.LLM,),
        "reference_types": (ReferenceType.RUBRIC_BASED,),
        "judgment_forms": (JudgmentForm.BINARY,),
        "aggregations": (Aggregation.NONE_SINGLE_SCORE,),
    }
    fields.update(overrides)
    return GraderTaxonomy.model_validate(fields)


class TwoScopeArgs(GraderArgs, TraceArgs, ArtifactArgs):
    pass


class TwoScopeGrader(Grader[TwoScopeArgs]):
    args_model = TwoScopeArgs
    taxonomy: ClassVar[GraderTaxonomy] = _taxonomy()

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        raise NotImplementedError


class TestTaxonomyPicks:
    def test_an_unset_pick_is_the_first_declared_value(self) -> None:
        grader = TwoScopeGrader(TwoScopeArgs())
        assert (grader.scope, grader.judgment_form, grader.aggregation) == (
            Scope.TRACE,
            JudgmentForm.BINARY,
            Aggregation.NONE_SINGLE_SCORE,
        )

    def test_a_declared_pick_is_used(self) -> None:
        grader = TwoScopeGrader(TwoScopeArgs(scope=Scope.ARTIFACT))
        assert grader.scope == Scope.ARTIFACT

    def test_a_pick_the_grader_does_not_declare_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="does not support scope 'session'"):
            TwoScopeGrader(TwoScopeArgs(scope=Scope.SESSION))

    def test_a_grader_without_a_taxonomy_accepts_no_picks(self) -> None:
        with pytest.raises(ValueError, match="does not support scope"):
            FontSizeGrader(FontSizeArgs(scope=Scope.SESSION))

    def test_unset_picks_are_left_out_of_the_dump(self) -> None:
        assert "scope" not in TwoScopeArgs().model_dump()
        assert TwoScopeArgs(scope=Scope.ARTIFACT).model_dump(mode="json")["scope"] == (
            "artifact"
        )


class TestTaxonomyDeclarationCheck:
    def test_a_declared_scope_needs_its_settings(self) -> None:
        with pytest.raises(TypeError, match="scope 'artifact' and use ArtifactArgs"):

            class _Missing(Grader[TraceOnlyArgs]):
                args_model = TraceOnlyArgs
                taxonomy: ClassVar[GraderTaxonomy] = _taxonomy()

    def test_settings_need_their_scope(self) -> None:
        with pytest.raises(TypeError, match="scope 'artifact' and use ArtifactArgs"):

            class _Extra(Grader[TwoScopeArgs]):
                args_model = TwoScopeArgs
                taxonomy: ClassVar[GraderTaxonomy] = _taxonomy(scopes=(Scope.TRACE,))

    def test_a_declared_value_needs_a_definition(self) -> None:
        with pytest.raises(TypeError, match="have no definition"):

            class _Undefined(Grader[TwoScopeArgs]):
                args_model = TwoScopeArgs
                taxonomy: ClassVar[GraderTaxonomy] = _taxonomy(
                    judgment_forms=(JudgmentForm.SCALAR,)
                )


class TraceOnlyArgs(GraderArgs, TraceArgs):
    pass
