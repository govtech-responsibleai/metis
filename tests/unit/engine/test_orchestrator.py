"""The orchestrator: building graders, the threshold rule, and every grader run leaving a record."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, ClassVar
from unittest.mock import MagicMock

import pytest

from metis.core.grading import GraderResult, GradingOutput
from metis.core.profile import Criterion
from metis.core.traces import GradingInput, Observation, Trace
from metis.engine.evaluation.orchestrator import (
    GraderSetupError,
    SessionFacts,
    build_grader,
    grade_session,
    record_results,
    resolve_grader_class,
)
from metis.library.grader import (
    DEFAULT_MAX_INPUT_TOKENS,
    Grader,
    GraderArgs,
    JudgeArgs,
    LLMSettings,
)
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

FACTS = SessionFacts(session_id="s1", scenario_id="sc", task_id="TC-1", trial_index=2)
HERE = __name__


def _session(*outputs: object) -> GradingInput:
    return GradingInput(
        traces=tuple(
            Trace(
                id=f"t{i}",
                session_id="s1",
                observations=(Observation(id=f"o{i}", trace_id=f"t{i}", output=out),),
            )
            for i, out in enumerate(outputs)
        )
    )


def _llm() -> LLMSettings:
    client: AsyncOpenAI = MagicMock()
    return LLMSettings(client=client)


class FixedArgs(GraderArgs):
    score: float | None = 1.0
    status: str = "scored"


class FixedGrader(Grader[FixedArgs]):
    """Returns one result with the status and score its args name."""

    args_model = FixedArgs

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        return GradingOutput(
            results=[
                GraderResult(
                    status=self.args.status,  # type: ignore[arg-type]
                    score=self.args.score,
                    reason="fixed",
                )
            ]
        )


class CheckedGrader(Grader[GraderArgs]):
    """One scored result for the session, under a declared pass-if-all rule."""

    args_model = GraderArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=None,
        scopes=(Scope.SESSION,),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.PASS_IF_ALL,),
    )

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        return GradingOutput(
            results=[
                GraderResult(status="scored", score=0.0, reason="r", scope="session")
            ]
        )


class PerTraceGrader(Grader[GraderArgs]):
    """One result per trace, judged on the prefix up to and including that trace."""

    args_model = GraderArgs

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        results = []
        for i, trace in enumerate(input.traces):
            seen = input.traces[: i + 1]
            if trace.root.output is None:
                results.append(
                    GraderResult(status="skipped", reason=f"{trace.id}: no output")
                )
            else:
                results.append(
                    GraderResult(status="scored", score=1.0, reason=f"saw {len(seen)}")
                )
        return GradingOutput(results=results)


class EmptyGrader(Grader[GraderArgs]):
    args_model = GraderArgs

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        return GradingOutput(results=[])


class RaisingGrader(Grader[GraderArgs]):
    args_model = GraderArgs

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        raise RuntimeError("judge exploded")


class WrongReturnGrader(Grader[GraderArgs]):
    args_model = GraderArgs

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        return [GraderResult(status="skipped", reason="x")]  # type: ignore[return-value]


class EchoJudgeArgs(JudgeArgs):
    pass


class EchoJudgeGrader(Grader[EchoJudgeArgs]):
    """A model-based grader that calls the shared client with its resolved model."""

    args_model = EchoJudgeArgs

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        reply = await llm.client.chat.completions.create(
            model=self.args.model, messages=[{"role": "user", "content": "judge"}]
        )
        return GradingOutput(
            results=[GraderResult(status="scored", score=0.9, reason=str(reply))]
        )


class SlowGrader(Grader[GraderArgs]):
    """Records when it starts, to show grader runs on one session overlap."""

    args_model = GraderArgs
    started: list[float] = []

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        SlowGrader.started.append(asyncio.get_running_loop().time())
        await asyncio.sleep(0.05)
        return GradingOutput(results=[GraderResult(status="skipped", reason="slow")])


class NotAGrader:
    pass


def _build(cls: type, args: dict[str, Any] | None = None, **kwargs: Any):
    criterion = Criterion(
        id="AC-1",
        name="Assessment",
        description="Assess the session.",
        grader_fqn=f"{HERE}.{cls.__name__}",
        grader_args=args or {},
    )
    return build_grader(
        criterion,
        default_judge_model=kwargs.get("default"),
        env=kwargs.get("env", {}),
    )


def _run(*instances: Any, grading_input: GradingInput | None = None, llm=None):
    criteria = [
        Criterion(
            id=f"AC-{i}",
            name="Assessment",
            description="Assess the session.",
            grader_fqn=f"{HERE}.{type(grader).__name__}",
        )
        for i, grader in enumerate(instances, 1)
    ]
    graders = {
        criterion.id: grader
        for criterion, grader in zip(criteria, instances, strict=True)
    }
    return asyncio.run(
        grade_session(
            criteria, graders, grading_input or _session("a"), llm or _llm(), FACTS
        )
    )


class TestResolveGraderClass:
    def test_resolves_a_grader(self) -> None:
        assert resolve_grader_class(f"{HERE}.FixedGrader") is FixedGrader

    @pytest.mark.parametrize(
        ("fqn", "message"),
        [
            ("NoDots", "not a fully-qualified name"),
            ("no.such.module.Grader", "could not be imported: ModuleNotFoundError"),
            (f"{HERE}.Missing", "has no attribute 'Missing'"),
            (f"{HERE}.NotAGrader", "not a subclass of metis.library.grader.Grader"),
            (f"{HERE}.FACTS", "not a subclass of metis.library.grader.Grader"),
        ],
    )
    def test_bad_fqns_are_setup_errors(self, fqn: str, message: str) -> None:
        with pytest.raises(GraderSetupError, match=message):
            resolve_grader_class(fqn)


class TestBuildGrader:
    def test_builds_with_validated_args(self) -> None:
        built = _build(FixedGrader, {"score": 0.3, "threshold": 0.2})
        assert isinstance(built, FixedGrader)
        assert built.args == FixedArgs(score=0.3, threshold=0.2)

    def test_criterion_needs_a_grader_before_execution(self) -> None:
        criterion = Criterion(
            id="AC-DRAFT", name="Draft", description="Assess the response."
        )
        with pytest.raises(
            GraderSetupError, match="Criterion 'AC-DRAFT' has no grader_fqn"
        ):
            build_grader(criterion, default_judge_model=None, env={})

    def test_errors_name_the_criterion(self) -> None:
        with pytest.raises(GraderSetupError, match="Criterion 'AC-1'.*no attribute"):
            _build(type("Missing", (), {}))

    def test_misspelt_arg_is_rejected_with_its_name(self) -> None:
        with pytest.raises(
            GraderSetupError, match=r"Criterion 'AC-1'.*scroe: Extra inputs"
        ):
            _build(FixedGrader, {"scroe": 0.3})

    def test_out_of_range_threshold_is_rejected(self) -> None:
        with pytest.raises(GraderSetupError, match="threshold"):
            _build(FixedGrader, {"threshold": 1.5})

    def test_a_taxonomy_pick_the_grader_does_not_declare_names_the_criterion(
        self,
    ) -> None:
        with pytest.raises(
            GraderSetupError,
            match=r"Criterion 'AC-1': CheckedGrader does not support scope 'trace'",
        ):
            _build(CheckedGrader, {"scope": "trace"})

    def test_judge_model_is_resolved_before_validation(self) -> None:
        built = _build(EchoJudgeGrader, default="spec-model")
        assert built.args.model == "spec-model"  # type: ignore[attr-defined]

    def test_model_on_a_code_grader_is_rejected(self) -> None:
        with pytest.raises(GraderSetupError, match="model: Extra inputs"):
            _build(FixedGrader, {"model": "gpt-4o"})


class TestThresholdRule:
    @pytest.mark.parametrize(
        ("score", "threshold", "outcome"),
        [
            (0.5, 0.5, "passed"),  # exactly at the threshold passes
            (0.49, 0.5, "failed"),
            (1.0, 1.0, "passed"),
            (0.0, 0.0, "passed"),
            (0.0, 0.5, "failed"),
            (1.0, 0.5, "passed"),
        ],
    )
    def test_score_against_threshold(
        self, score: float, threshold: float, outcome: str
    ) -> None:
        output = GradingOutput(
            results=[GraderResult(status="scored", score=score, reason="r")]
        )
        (recorded,) = record_results(output, threshold)
        assert (recorded.outcome, recorded.score) == (outcome, score)

    @pytest.mark.parametrize("status", ["skipped", "errored"])
    def test_unscored_results_pass_through(self, status: str) -> None:
        output = GradingOutput(results=[GraderResult(status=status, reason="why")])  # type: ignore[arg-type]
        (recorded,) = record_results(output, 0.5)
        assert (recorded.outcome, recorded.score, recorded.reason) == (
            status,
            None,
            "why",
        )

    def test_empty_output_becomes_one_errored_result(self) -> None:
        (recorded,) = record_results(GradingOutput(results=[]), 0.5)
        assert recorded.outcome == "errored"
        assert "returned no results" in recorded.reason


class TestGradeSession:
    def test_one_record_per_grader_with_run_facts(self) -> None:
        (record,) = _run(_build(FixedGrader, {"score": 0.7}))
        assert (
            record.session_id,
            record.scenario_id,
            record.task_id,
            record.trial_index,
        ) == (
            "s1",
            "sc",
            "TC-1",
            2,
        )
        assert record.criterion_id == "AC-1"
        assert record.grader_fqn == f"{HERE}.FixedGrader"
        assert [(r.outcome, r.score) for r in record.results] == [("passed", 0.7)]

    def test_the_record_carries_the_aggregation_rule_and_scope(self) -> None:
        (record,) = _run(_build(CheckedGrader))
        assert record.aggregation == "pass_if_all"
        [result] = record.results
        assert (result.outcome, result.scope) == ("failed", "session")
        (untyped,) = _run(_build(FixedGrader))
        assert untyped.aggregation is None
        assert "aggregation" not in untyped.model_dump()

    def test_grader_args_record_defaults_and_resolved_model(self) -> None:
        llm = _llm()
        llm.client.chat.completions.create = MagicMock(
            side_effect=lambda **_: _awaitable("ok")
        )
        (record,) = _run(
            _build(EchoJudgeGrader, env={"JUDGE_MODEL": "env-model"}), llm=llm
        )
        assert record.grader_args == {
            "threshold": 0.5,
            "model": "env-model",
            "max_input_tokens": DEFAULT_MAX_INPUT_TOKENS,
        }

    def test_judge_grader_uses_the_shared_client_with_its_resolved_model(self) -> None:
        llm = _llm()
        create = MagicMock(side_effect=lambda **_: _awaitable("verdict"))
        llm.client.chat.completions.create = create
        (record,) = _run(_build(EchoJudgeGrader, {"model": "crit-model"}), llm=llm)
        assert create.call_args.kwargs["model"] == "crit-model"
        assert record.results[0].reason == "verdict"

    def test_per_trace_grader_records_one_result_per_trace(self) -> None:
        (record,) = _run(_build(PerTraceGrader), grading_input=_session("a", None, "c"))
        assert [(r.outcome, r.reason) for r in record.results] == [
            ("passed", "saw 1"),
            ("skipped", "t1: no output"),
            ("passed", "saw 3"),
        ]

    def test_raising_grader_is_one_errored_result_and_others_still_run(self) -> None:
        raising, fixed = _build(RaisingGrader), _build(FixedGrader)
        broken, ok = _run(raising, fixed)
        assert [(r.outcome, r.score) for r in broken.results] == [("errored", None)]
        assert broken.results[0].reason == "Grader raised: RuntimeError: judge exploded"
        assert ok.results[0].outcome == "passed"

    def test_wrong_return_type_is_errored(self) -> None:
        (record,) = _run(_build(WrongReturnGrader))
        assert record.results[0].outcome == "errored"
        assert "not GradingOutput" in record.results[0].reason

    def test_empty_output_is_errored_not_dropped(self) -> None:
        (record,) = _run(_build(EmptyGrader))
        assert [r.outcome for r in record.results] == ["errored"]

    def test_records_keep_grader_order(self) -> None:
        a = _build(FixedGrader, {"score": 0.1})
        b = _build(FixedGrader, {"score": 0.9})
        assert [r.results[0].score for r in _run(a, b)] == [0.1, 0.9]

    def test_grader_runs_on_one_session_overlap(self) -> None:
        SlowGrader.started.clear()
        _run(_build(SlowGrader), _build(SlowGrader), _build(SlowGrader))
        assert max(SlowGrader.started) - min(SlowGrader.started) < 0.04

    def test_one_grader_instance_grades_many_sessions(self) -> None:
        built = _build(PerTraceGrader)
        first = _run(built, grading_input=_session("a"))
        second = _run(built, grading_input=_session("a", "b"))
        assert (len(first[0].results), len(second[0].results)) == (1, 2)

    def test_no_graders_means_no_records(self) -> None:
        assert _run() == []


class PoisoningGrader(Grader[GraderArgs]):
    """Edits a payload in place, as a careless "clean the message first" grader would."""

    args_model = GraderArgs

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        input.traces[0].root.metadata["poisoned"] = True
        return GradingOutput(results=[GraderResult(status="skipped", reason="m")])


class MetadataReader(Grader[GraderArgs]):
    args_model = GraderArgs

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        await asyncio.sleep(0)  # let the poisoning grader run first
        seen = "poisoned" in input.traces[0].root.metadata
        return GradingOutput(results=[GraderResult(status="skipped", reason=str(seen))])


def test_one_grader_mutating_payloads_cannot_change_what_another_sees() -> None:
    """Freezing protects fields, not the dicts inside them; each run gets its own copy."""
    shared = GradingInput(
        traces=(
            Trace(
                id="t",
                session_id="s1",
                observations=(Observation(id="o", trace_id="t", metadata={"k": 1}),),
            ),
        )
    )
    records = _run(
        _build(PoisoningGrader), _build(MetadataReader), grading_input=shared
    )
    assert records[1].results[0].reason == "False"
    assert shared.traces[0].root.metadata == {"k": 1}


def test_the_grader_base_itself_is_not_a_grader() -> None:
    criterion = Criterion(
        id="AC-1",
        name="Assessment",
        description="Assess the session.",
        grader_fqn="metis.library.grader.Grader",
    )
    with pytest.raises(GraderSetupError, match="Criterion 'AC-1'.*abstract base"):
        build_grader(criterion, default_judge_model=None, env={})


async def _awaitable(value: str) -> str:
    return value
