"""The Resource Use graders: deterministic, no LLM judge.

These graders compute a measured value from the session traces and compare it to a budget.
They never call the LLM, so the client mock asserts no calls were made.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from metis.core.traces import GradingInput, Observation, Trace
from metis.library.grader import LLMSettings
from metis.library.graders import (
    ElapsedTimeGrader,
    ExecutionStepCountGrader,
    ModelCallCountGrader,
    MonetaryCostGrader,
    TokenUsageGrader,
    ToolCallCountGrader,
)
from metis.library.graders.resource_use._elapsed_time import ElapsedTimeArgs
from metis.library.graders.resource_use._execution_step_count import (
    ExecutionStepCountArgs,
)
from metis.library.graders.resource_use._model_call_count import ModelCallCountArgs
from metis.library.graders.resource_use._monetary_cost import MonetaryCostArgs
from metis.library.graders.resource_use._token_usage import TokenUsageArgs
from metis.library.graders.resource_use._tool_call_count import ToolCallCountArgs
from metis.library.taxonomy import (
    Aggregation,
    GraderType,
    JudgmentForm,
    Measure,
    ReferenceType,
    Scope,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _t(second: int) -> datetime:
    return datetime(2026, 1, 1, 0, 0, second, tzinfo=UTC)


def _obs(
    obs_id: str,
    trace_id: str = "t1",
    *,
    type: str | None = None,
    parent: str | None = None,
    start: int | None = None,
    end: int | None = None,
    **kwargs: Any,
) -> Observation:
    return Observation(
        id=obs_id,
        trace_id=trace_id,
        type=type,
        parent_observation_id=parent,
        start_time=_t(start) if start is not None else None,
        end_time=_t(end) if end is not None else None,
        **kwargs,
    )


def _trace(trace_id: str, *observations: Observation) -> Trace:
    return Trace(id=trace_id, session_id="s1", observations=observations)


def _grade(grader: Any, gi: GradingInput) -> list[Any]:
    client = MagicMock()
    out = asyncio.run(grader.grade(gi, LLMSettings(client=client)))
    client.chat.completions.create.assert_not_called()
    return out.results


EMPTY = GradingInput(traces=())


# ---------------------------------------------------------------------------
# Taxonomy declarations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("grader_cls", "measure"),
    [
        (ElapsedTimeGrader, Measure.ELAPSED_TIME),
        (ExecutionStepCountGrader, Measure.EXECUTION_STEP_COUNT),
        (ModelCallCountGrader, Measure.MODEL_CALL_COUNT),
        (MonetaryCostGrader, Measure.MONETARY_COST),
        (TokenUsageGrader, Measure.TOKEN_USAGE),
        (ToolCallCountGrader, Measure.TOOL_CALL_COUNT),
    ],
)
def test_declares_its_taxonomy(grader_cls: type, measure: Measure) -> None:
    assert grader_cls.taxonomy.model_dump() == {
        "measure": measure,
        "scopes": (Scope.SESSION,),
        "grader_types": (GraderType.DETERMINISTIC,),
        "reference_types": (ReferenceType.POLICY_RULE,),
        "judgment_forms": (JudgmentForm.BINARY,),
        "aggregations": (Aggregation.NONE_SINGLE_SCORE,),
    }


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _session_with_children() -> GradingInput:
    """A session with one trace containing a root AGENT, 2 GENERATION, 1 TOOL, and 1 SPAN."""
    return GradingInput(
        traces=(
            _trace(
                "t1",
                _obs("root", type="AGENT", start=0, end=10, input="hi", output="bye"),
                _obs("gen-1", type="GENERATION", parent="root", start=1, end=3),
                _obs("gen-2", type="GENERATION", parent="root", start=4, end=6),
                _obs("tool-1", type="TOOL", parent="root", start=6, end=7),
                _obs("span-1", type="SPAN", parent="root", start=7, end=9),
            ),
        )
    )


# ---------------------------------------------------------------------------
# ElapsedTimeGrader
# ---------------------------------------------------------------------------


def test_elapsed_time_under_budget_scores_one() -> None:
    gi = _session_with_children()
    grader = ElapsedTimeGrader(ElapsedTimeArgs(max_seconds=20.0))
    [result] = _grade(grader, gi)

    assert result.status == "scored"
    assert result.score == 1.0
    assert result.scope == "session"
    assert "10.0 second(s)" in result.reason
    assert "20.0" in result.reason
    assert result.measurements == {"elapsed_seconds": 10.0}


def test_elapsed_time_over_budget_scores_zero() -> None:
    gi = _session_with_children()
    grader = ElapsedTimeGrader(ElapsedTimeArgs(max_seconds=5.0))
    [result] = _grade(grader, gi)

    assert result.status == "scored"
    assert result.score == 0.0


def test_elapsed_time_exactly_at_budget_scores_one() -> None:
    gi = _session_with_children()
    grader = ElapsedTimeGrader(ElapsedTimeArgs(max_seconds=10.0))
    [result] = _grade(grader, gi)

    assert result.score == 1.0


def test_elapsed_time_no_traces_errors() -> None:
    grader = ElapsedTimeGrader(ElapsedTimeArgs(max_seconds=10.0))
    [result] = _grade(grader, EMPTY)

    assert result.status == "errored"


def test_elapsed_time_no_timestamps_errors() -> None:
    gi = GradingInput(
        traces=(
            _trace(
                "t1",
                _obs("root", type="AGENT", input="hi", output="bye"),
            ),
        )
    )
    grader = ElapsedTimeGrader(ElapsedTimeArgs(max_seconds=10.0))
    [result] = _grade(grader, gi)

    assert result.status == "errored"
    assert "start time" in result.reason or "end time" in result.reason


# ---------------------------------------------------------------------------
# ExecutionStepCountGrader
# ---------------------------------------------------------------------------


def test_step_count_under_budget_scores_one() -> None:
    gi = _session_with_children()
    grader = ExecutionStepCountGrader(ExecutionStepCountArgs(max_steps=10))
    [result] = _grade(grader, gi)

    assert result.status == "scored"
    assert result.score == 1.0
    assert "3 execution step(s)" in result.reason
    assert result.measurements == {"execution_steps": 3.0}


def test_step_count_over_budget_scores_zero() -> None:
    gi = _session_with_children()
    grader = ExecutionStepCountGrader(ExecutionStepCountArgs(max_steps=2))
    [result] = _grade(grader, gi)

    assert result.status == "scored"
    assert result.score == 0.0


def test_step_count_no_traces_errors() -> None:
    grader = ExecutionStepCountGrader(ExecutionStepCountArgs(max_steps=5))
    [result] = _grade(grader, EMPTY)

    assert result.status == "errored"


# ---------------------------------------------------------------------------
# ModelCallCountGrader
# ---------------------------------------------------------------------------


def test_model_calls_under_budget_scores_one() -> None:
    gi = _session_with_children()
    grader = ModelCallCountGrader(ModelCallCountArgs(max_calls=5))
    [result] = _grade(grader, gi)

    assert result.status == "scored"
    assert result.score == 1.0
    assert "2 model call(s)" in result.reason
    assert result.measurements == {"model_calls": 2.0}


def test_model_calls_over_budget_scores_zero() -> None:
    gi = _session_with_children()
    grader = ModelCallCountGrader(ModelCallCountArgs(max_calls=1))
    [result] = _grade(grader, gi)

    assert result.status == "scored"
    assert result.score == 0.0


def test_model_calls_no_traces_errors() -> None:
    grader = ModelCallCountGrader(ModelCallCountArgs(max_calls=5))
    [result] = _grade(grader, EMPTY)

    assert result.status == "errored"


# ---------------------------------------------------------------------------
# ToolCallCountGrader
# ---------------------------------------------------------------------------


def test_tool_calls_under_budget_scores_one() -> None:
    gi = _session_with_children()
    grader = ToolCallCountGrader(ToolCallCountArgs(max_calls=5))
    [result] = _grade(grader, gi)

    assert result.status == "scored"
    assert result.score == 1.0
    assert "1 tool call(s)" in result.reason
    assert result.measurements == {"tool_calls": 1.0}


def test_tool_calls_over_budget_scores_zero() -> None:
    gi = GradingInput(
        traces=(
            _trace(
                "t1",
                _obs("root", type="AGENT", start=0, end=10, input="hi", output="bye"),
                _obs("tool-1", type="TOOL", parent="root", start=1, end=2),
                _obs("tool-2", type="TOOL", parent="root", start=3, end=4),
                _obs("tool-3", type="TOOL", parent="root", start=5, end=6),
            ),
        )
    )
    grader = ToolCallCountGrader(ToolCallCountArgs(max_calls=2))
    [result] = _grade(grader, gi)

    assert result.status == "scored"
    assert result.score == 0.0


def test_tool_calls_no_traces_errors() -> None:
    grader = ToolCallCountGrader(ToolCallCountArgs(max_calls=5))
    [result] = _grade(grader, EMPTY)

    assert result.status == "errored"


# ---------------------------------------------------------------------------
# MonetaryCostGrader — minimal (no cost data in real traces)
# ---------------------------------------------------------------------------


def test_monetary_cost_no_traces_errors() -> None:
    grader = MonetaryCostGrader(MonetaryCostArgs(max_cost=1.0))
    [result] = _grade(grader, EMPTY)

    assert result.status == "errored"


def test_monetary_cost_no_cost_data_errors() -> None:
    gi = _session_with_children()
    grader = MonetaryCostGrader(MonetaryCostArgs(max_cost=1.0))
    [result] = _grade(grader, gi)

    assert result.status == "errored"


# ---------------------------------------------------------------------------
# TokenUsageGrader — minimal (no token data in real traces)
# ---------------------------------------------------------------------------


def test_token_usage_no_traces_errors() -> None:
    grader = TokenUsageGrader(TokenUsageArgs(max_total_tokens=1000))
    [result] = _grade(grader, EMPTY)

    assert result.status == "errored"


def test_token_usage_no_token_data_errors() -> None:
    gi = _session_with_children()
    grader = TokenUsageGrader(TokenUsageArgs(max_total_tokens=1000))
    [result] = _grade(grader, gi)

    assert result.status == "errored"
    assert "token" in result.reason.lower()


# ---------------------------------------------------------------------------
# Args validation
# ---------------------------------------------------------------------------


def test_elapsed_time_rejects_non_positive_budget() -> None:
    with pytest.raises(ValidationError):
        ElapsedTimeArgs(max_seconds=0)
    with pytest.raises(ValidationError):
        ElapsedTimeArgs(max_seconds=-1.0)


def test_step_count_rejects_zero_budget() -> None:
    with pytest.raises(ValidationError):
        ExecutionStepCountArgs(max_steps=0)


def test_model_call_count_rejects_float() -> None:
    with pytest.raises(ValidationError):
        ModelCallCountArgs(max_calls=1.5)  # type: ignore[arg-type]


def test_tool_call_count_rejects_float() -> None:
    with pytest.raises(ValidationError):
        ToolCallCountArgs(max_calls=2.5)  # type: ignore[arg-type]


def test_token_category_rejects_unknown() -> None:
    with pytest.raises(ValidationError):
        TokenUsageArgs(max_total_tokens=1000, token_category="reasoning")  # type: ignore[arg-type]


def test_monetary_cost_rejects_zero() -> None:
    with pytest.raises(ValidationError):
        MonetaryCostArgs(max_cost=0)
