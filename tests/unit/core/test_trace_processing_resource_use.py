"""The trace processor's resource-use measurement functions.

Each function reads structural fields from observations (types, timestamps) or cost/token
data from ``Observation.raw``.  Graders call these rather than reading observations directly.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from metis.core.trace_processing import (
    Problem,
    execution_step_count,
    generation_count,
    session_cost,
    session_elapsed_seconds,
    token_usage,
    tool_call_count,
)
from metis.core.traces import Observation, Trace


def _t(second: int) -> datetime:
    return datetime(2026, 1, 1, 0, 0, second, tzinfo=UTC)


def _obs(trace_id: str, obs_id: str, **kw: object) -> Observation:
    return Observation(id=obs_id, trace_id=trace_id, **kw)  # type: ignore[arg-type]


def _trace(trace_id: str, *observations: Observation) -> Trace:
    return Trace(id=trace_id, session_id="s1", observations=observations)


# ---------------------------------------------------------------------------
# session_elapsed_seconds
# ---------------------------------------------------------------------------


class TestSessionElapsedSeconds:
    def test_normal_span(self) -> None:
        traces = (
            _trace(
                "t1",
                _obs("t1", "root", type="SPAN", start_time=_t(0), end_time=_t(10)),
            ),
        )
        result = session_elapsed_seconds(traces)
        assert result == 10.0

    def test_sub_observation_widens_the_span(self) -> None:
        traces = (
            _trace(
                "t1",
                _obs("t1", "root", type="SPAN", start_time=_t(2), end_time=_t(8)),
                _obs(
                    "t1",
                    "child",
                    type="GENERATION",
                    parent_observation_id="root",
                    start_time=_t(1),
                    end_time=_t(12),
                ),
            ),
        )
        result = session_elapsed_seconds(traces)
        assert result == 11.0

    def test_multiple_traces(self) -> None:
        traces = (
            _trace(
                "t1",
                _obs("t1", "r1", type="SPAN", start_time=_t(0), end_time=_t(5)),
            ),
            _trace(
                "t2",
                _obs("t2", "r2", type="SPAN", start_time=_t(10), end_time=_t(20)),
            ),
        )
        result = session_elapsed_seconds(traces)
        assert result == 20.0

    def test_missing_timestamps_returns_problem(self) -> None:
        traces = (_trace("t1", _obs("t1", "root", type="SPAN")),)
        result = session_elapsed_seconds(traces)
        assert isinstance(result, Problem)
        assert result.kind == "missing"

    def test_empty_traces(self) -> None:
        result = session_elapsed_seconds(())
        assert isinstance(result, Problem)
        assert result.kind == "missing"

    def test_only_start_times_returns_problem(self) -> None:
        traces = (_trace("t1", _obs("t1", "root", type="SPAN", start_time=_t(0))),)
        result = session_elapsed_seconds(traces)
        assert isinstance(result, Problem)

    def test_evaluator_observations_excluded(self) -> None:
        traces = (
            _trace(
                "t1",
                _obs("t1", "root", type="AGENT", start_time=_t(0), end_time=_t(10)),
                _obs(
                    "t1",
                    "eval1",
                    type="EVALUATOR",
                    parent_observation_id="root",
                    start_time=_t(11),
                    end_time=_t(20),
                ),
            ),
        )
        result = session_elapsed_seconds(traces)
        assert result == 10.0


# ---------------------------------------------------------------------------
# execution_step_count
# ---------------------------------------------------------------------------


class TestExecutionStepCount:
    def test_counts_generation_tool_agent_excludes_span(self) -> None:
        traces = (
            _trace(
                "t1",
                _obs("t1", "root", type="SPAN"),
                _obs("t1", "gen1", type="GENERATION", parent_observation_id="root"),
                _obs("t1", "tool1", type="TOOL", parent_observation_id="root"),
                _obs("t1", "agent1", type="AGENT", parent_observation_id="root"),
                _obs("t1", "span1", type="SPAN", parent_observation_id="root"),
            ),
        )
        assert execution_step_count(traces) == 3

    def test_excludes_root_observation(self) -> None:
        traces = (
            _trace(
                "t1",
                _obs("t1", "root", type="AGENT"),
                _obs("t1", "gen1", type="GENERATION", parent_observation_id="root"),
            ),
        )
        assert execution_step_count(traces) == 1

    def test_multiple_traces_sum(self) -> None:
        traces = (
            _trace(
                "t1",
                _obs("t1", "root1", type="SPAN"),
                _obs("t1", "gen1", type="GENERATION", parent_observation_id="root1"),
                _obs("t1", "tool1", type="TOOL", parent_observation_id="root1"),
            ),
            _trace(
                "t2",
                _obs("t2", "root2", type="SPAN"),
                _obs("t2", "gen2", type="GENERATION", parent_observation_id="root2"),
            ),
        )
        assert execution_step_count(traces) == 3

    def test_empty_traces_returns_zero(self) -> None:
        assert execution_step_count(()) == 0


# ---------------------------------------------------------------------------
# generation_count
# ---------------------------------------------------------------------------


class TestGenerationCount:
    def test_counts_all_generations(self) -> None:
        traces = (
            _trace(
                "t1",
                _obs("t1", "root", type="SPAN"),
                _obs("t1", "gen1", type="GENERATION", parent_observation_id="root"),
                _obs("t1", "gen2", type="GENERATION", parent_observation_id="root"),
            ),
            _trace(
                "t2",
                _obs("t2", "root2", type="SPAN"),
                _obs("t2", "gen3", type="GENERATION", parent_observation_id="root2"),
            ),
        )
        assert generation_count(traces) == 3

    def test_includes_root_generation(self) -> None:
        traces = (_trace("t1", _obs("t1", "root", type="GENERATION")),)
        assert generation_count(traces) == 1

    def test_no_generations_returns_zero(self) -> None:
        traces = (
            _trace(
                "t1",
                _obs("t1", "root", type="SPAN"),
                _obs("t1", "tool1", type="TOOL", parent_observation_id="root"),
            ),
        )
        assert generation_count(traces) == 0


# ---------------------------------------------------------------------------
# tool_call_count
# ---------------------------------------------------------------------------


class TestToolCallCount:
    def test_counts_all_tools(self) -> None:
        traces = (
            _trace(
                "t1",
                _obs("t1", "root", type="SPAN"),
                _obs("t1", "tool1", type="TOOL", parent_observation_id="root"),
                _obs("t1", "tool2", type="TOOL", parent_observation_id="root"),
            ),
            _trace(
                "t2",
                _obs("t2", "root2", type="SPAN"),
                _obs("t2", "tool3", type="TOOL", parent_observation_id="root2"),
            ),
        )
        assert tool_call_count(traces) == 3

    def test_no_tools_returns_zero(self) -> None:
        traces = (
            _trace(
                "t1",
                _obs("t1", "root", type="SPAN"),
                _obs("t1", "gen1", type="GENERATION", parent_observation_id="root"),
            ),
        )
        assert tool_call_count(traces) == 0


# ---------------------------------------------------------------------------
# session_cost (smoke tests)
# ---------------------------------------------------------------------------


class TestSessionCost:
    def test_no_cost_data_returns_problem(self) -> None:
        traces = (_trace("t1", _obs("t1", "root", type="GENERATION")),)
        result = session_cost(traces)
        assert isinstance(result, Problem)
        assert result.kind == "missing"

    def test_calculated_total_cost(self) -> None:
        traces = (
            _trace(
                "t1",
                _obs("t1", "root", type="SPAN"),
                _obs(
                    "t1",
                    "gen1",
                    type="GENERATION",
                    parent_observation_id="root",
                    calculatedTotalCost=0.05,
                ),
            ),
        )
        result = session_cost(traces)
        assert result == pytest.approx(0.05)

    def test_sums_across_generations(self) -> None:
        traces = (
            _trace(
                "t1",
                _obs("t1", "root", type="SPAN"),
                _obs(
                    "t1",
                    "gen1",
                    type="GENERATION",
                    parent_observation_id="root",
                    calculatedTotalCost=0.03,
                ),
                _obs(
                    "t1",
                    "gen2",
                    type="GENERATION",
                    parent_observation_id="root",
                    calculatedTotalCost=0.02,
                ),
            ),
        )
        result = session_cost(traces)
        assert result == pytest.approx(0.05)

    def test_cost_details_fallback(self) -> None:
        traces = (
            _trace(
                "t1",
                _obs("t1", "root", type="SPAN"),
                _obs(
                    "t1",
                    "gen1",
                    type="GENERATION",
                    parent_observation_id="root",
                    costDetails={"total": 0.04},
                ),
            ),
        )
        result = session_cost(traces)
        assert result == pytest.approx(0.04)

    def test_total_price_fallback(self) -> None:
        traces = (
            _trace(
                "t1",
                _obs("t1", "root", type="SPAN"),
                _obs(
                    "t1",
                    "gen1",
                    type="GENERATION",
                    parent_observation_id="root",
                    totalPrice=0.01,
                ),
            ),
        )
        result = session_cost(traces)
        assert result == pytest.approx(0.01)

    def test_empty_traces_returns_problem(self) -> None:
        result = session_cost(())
        assert isinstance(result, Problem)


# ---------------------------------------------------------------------------
# token_usage (smoke tests)
# ---------------------------------------------------------------------------


class TestTokenUsage:
    def test_no_token_data_returns_problem(self) -> None:
        traces = (_trace("t1", _obs("t1", "root", type="GENERATION")),)
        result = token_usage(traces)
        assert isinstance(result, Problem)
        assert result.kind == "missing"

    def test_usage_dict(self) -> None:
        traces = (
            _trace(
                "t1",
                _obs("t1", "root", type="SPAN"),
                _obs(
                    "t1",
                    "gen1",
                    type="GENERATION",
                    parent_observation_id="root",
                    usage={"input": 100, "output": 50, "total": 150},
                ),
            ),
        )
        result = token_usage(traces)
        assert result == {"input": 100, "output": 50, "total": 150}

    def test_sums_across_generations(self) -> None:
        traces = (
            _trace(
                "t1",
                _obs("t1", "root", type="SPAN"),
                _obs(
                    "t1",
                    "gen1",
                    type="GENERATION",
                    parent_observation_id="root",
                    usage={"input": 100, "output": 50, "total": 150},
                ),
                _obs(
                    "t1",
                    "gen2",
                    type="GENERATION",
                    parent_observation_id="root",
                    usage={"input": 200, "output": 80, "total": 280},
                ),
            ),
        )
        result = token_usage(traces)
        assert result == {"input": 300, "output": 130, "total": 430}

    def test_legacy_token_fields(self) -> None:
        traces = (
            _trace(
                "t1",
                _obs("t1", "root", type="SPAN"),
                _obs(
                    "t1",
                    "gen1",
                    type="GENERATION",
                    parent_observation_id="root",
                    promptTokens=100,
                    completionTokens=50,
                    totalTokens=150,
                ),
            ),
        )
        result = token_usage(traces)
        assert result == {"input": 100, "output": 50, "total": 150}

    def test_empty_traces_returns_problem(self) -> None:
        result = token_usage(())
        assert isinstance(result, Problem)
