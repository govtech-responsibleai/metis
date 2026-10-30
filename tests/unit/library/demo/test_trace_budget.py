"""DemoTraceBudgetGrader: the simplest demo grader (#431)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
import yaml
from pydantic import ValidationError

from metis.core.traces import GradingInput, Observation, Trace
from metis.library.grader import Grader, LLMSettings
from metis.library.graders.demo import DemoTraceBudgetArgs, DemoTraceBudgetGrader
from metis.library.taxonomy import (
    Aggregation,
    GraderType,
    JudgmentForm,
    Measure,
    ReferenceType,
    Scope,
)


def _trace(index: int, *, output: object = "an answer") -> Trace:
    return Trace(
        id=f"t{index}",
        session_id="s1",
        observations=(
            Observation(id=f"o{index}", trace_id=f"t{index}", output=output),
        ),
    )


def _session(count: int) -> GradingInput:
    return GradingInput(traces=tuple(_trace(i) for i in range(count)))


def _grade(grader: DemoTraceBudgetGrader, grading_input: GradingInput):
    client = MagicMock()
    out = asyncio.run(grader.grade(grading_input, LLMSettings(client=client)))
    client.assert_not_called()  # code-based: never touches the LLM client
    assert client.mock_calls == []
    return out


def _grader(**args: object) -> DemoTraceBudgetGrader:
    return DemoTraceBudgetGrader(DemoTraceBudgetArgs.model_validate(args))


class TestArgs:
    def test_defaults(self) -> None:
        assert DemoTraceBudgetArgs.model_validate({}).model_dump() == {
            "threshold": 0.5,
            "max_traces": 10,
        }

    @pytest.mark.parametrize("bad", [0, -1, "many"])
    def test_rejects_a_non_positive_or_non_integer_budget(self, bad: object) -> None:
        with pytest.raises(ValidationError, match="max_traces"):
            DemoTraceBudgetArgs.model_validate({"max_traces": bad})

    @pytest.mark.parametrize(
        "raw", ["max_traces: yes", "max_traces: '4'", "max_traces: 4.5"]
    )
    def test_budget_must_be_a_yaml_integer(self, raw: str) -> None:
        with pytest.raises(ValidationError, match="max_traces"):
            DemoTraceBudgetArgs.model_validate(yaml.safe_load(raw))

    def test_rejects_the_old_turn_budget_arg_name(self) -> None:
        """Specs written for TurnBudgetGrader fail validation loudly, not silently."""
        with pytest.raises(ValidationError, match="max_turns"):
            DemoTraceBudgetArgs.model_validate({"max_turns": 4})

    def test_is_a_grader_with_matching_args_model(self) -> None:
        assert issubclass(DemoTraceBudgetGrader, Grader)
        assert DemoTraceBudgetGrader.args_model is DemoTraceBudgetArgs

    def test_declares_one_supported_value_for_each_taxonomy_field(self) -> None:
        assert DemoTraceBudgetGrader.taxonomy.model_dump() == {
            "measure": Measure.TASK_CONSTRAINT_ADHERENCE,
            "scopes": (Scope.SESSION,),
            "grader_types": (GraderType.DETERMINISTIC,),
            "reference_types": (ReferenceType.POLICY_RULE,),
            "judgment_forms": (JudgmentForm.BINARY,),
            "aggregations": (Aggregation.NONE_SINGLE_SCORE,),
        }


class TestGrade:
    def test_under_budget_scores_one(self) -> None:
        out = _grade(_grader(max_traces=4), _session(2))
        assert [(r.status, r.score) for r in out.results] == [("scored", 1.0)]
        assert out.results[0].reason == (
            "The session used 2 trace(s) against a budget of 4."
        )

    def test_exactly_at_budget_scores_one(self) -> None:
        out = _grade(_grader(max_traces=4), _session(4))
        assert out.results[0].score == 1.0

    def test_over_budget_scores_zero(self) -> None:
        out = _grade(_grader(max_traces=4), _session(5))
        assert [(r.status, r.score) for r in out.results] == [("scored", 0.0)]
        assert "5 trace(s)" in out.results[0].reason

    def test_one_trace_session_is_still_a_session(self) -> None:
        out = _grade(_grader(max_traces=1), _session(1))
        assert len(out.results) == 1
        assert out.results[0].score == 1.0

    def test_traces_without_output_still_count(self) -> None:
        """A crashed exchange is still an exchange the session spent."""
        grading_input = GradingInput(
            traces=(_trace(0), _trace(1, output=None), _trace(2, output=None))
        )
        out = _grade(_grader(max_traces=2), grading_input)
        assert out.results[0].score == 0.0

    def test_returns_one_result_for_a_multi_trace_session(self) -> None:
        """Session-scoped: never one result per trace."""
        out = _grade(_grader(max_traces=10), _session(7))
        assert len(out.results) == 1

    def test_artifacts_do_not_affect_the_count(self) -> None:
        from metis.core import Artifact

        grading_input = GradingInput(
            traces=(_trace(0),),
            artifacts=(Artifact(name="a.csv", state="received", path="/tmp/a.csv"),),
        )
        out = _grade(_grader(max_traces=1), grading_input)
        assert out.results[0].score == 1.0

    def test_grader_is_reusable_across_sessions(self) -> None:
        """Holds no per-evaluation state: the same instance grades two sessions."""
        grader = _grader(max_traces=3)
        first = _grade(grader, _session(5))
        second = _grade(grader, _session(1))
        assert (first.results[0].score, second.results[0].score) == (0.0, 1.0)
