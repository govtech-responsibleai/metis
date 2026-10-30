"""The trace processor's views and selection (#431).

Turns and tool calls are built from structural fields only. Target errors are evidence on a
turn; an empty selection is a ``no_match`` problem.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from metis.core import trace_processing
from metis.core.trace_processing import (
    Problem,
    TargetError,
    turns,
)
from metis.core.traces import GradingInput, Observation, Trace


def _t(second: int) -> datetime:
    return datetime(2026, 1, 1, 0, 0, second, tzinfo=UTC)


def _obs(trace_id: str, obs_id: str, second: int, **fields: object) -> Observation:
    return Observation(id=obs_id, trace_id=trace_id, start_time=_t(second), **fields)  # type: ignore[arg-type]


def _turn_trace(
    trace_id: str, second: int, *, user: object = "q", reply: object = "a"
) -> Trace:
    root = _obs(
        trace_id, f"{trace_id}-root", second, type="SPAN", input=user, output=reply
    )
    return Trace(id=trace_id, session_id="s", observations=(root,))


def _session(*traces: Trace) -> GradingInput:
    return GradingInput(traces=traces)


class TestTurns:
    def test_turns_follow_trace_order_and_keep_ids(self) -> None:
        result = turns(
            _session(_turn_trace("t1", 0), _turn_trace("t2", 5, user="q2")).traces
        )
        assert [turn.index for turn in result] == [0, 1]
        assert result[1].trace_id == "t2"
        assert result[1].user == "q2"
        assert result[0].reply == "a"

    def test_tool_calls_at_any_depth_name_their_agent(self) -> None:
        t = "t1"
        observations = (
            _obs(t, "root", 0, type="SPAN", input="q", output="a"),
            _obs(
                t,
                "router",
                1,
                type="AGENT",
                name="Router",
                parent_observation_id="root",
            ),
            _obs(
                t,
                "delegate",
                2,
                type="TOOL",
                name="delegate",
                parent_observation_id="router",
            ),
            _obs(
                t, "sub", 3, type="SPAN", name="sub", parent_observation_id="delegate"
            ),
            _obs(
                t,
                "analyst",
                4,
                type="AGENT",
                name="Analyst",
                parent_observation_id="sub",
            ),
            _obs(t, "run", 5, type="TOOL", name="run", parent_observation_id="analyst"),
        )
        (turn,) = turns(
            _session(Trace(id=t, session_id="s", observations=observations)).traces
        )
        assert [(c.name, c.agent) for c in turn.tool_calls] == [
            ("delegate", "Router"),
            ("run", "Analyst"),
        ]
        assert turn.tool_calls[1].turn_index == 0
        assert turn.tool_calls[1].observation_id == "run"

    def test_a_tool_call_with_no_agent_above_it_has_none(self) -> None:
        t = "t1"
        observations = (
            _obs(t, "root", 0, type="SPAN", input="q", output="a"),
            _obs(t, "tool", 1, type="TOOL", name="lone", parent_observation_id="root"),
        )
        (turn,) = turns(
            _session(Trace(id=t, session_id="s", observations=observations)).traces
        )
        assert turn.tool_calls[0].agent is None

    def test_a_crashed_turn_keeps_its_place(self) -> None:
        """No reply is evidence the target failed, not a reason to drop the turn."""
        (turn,) = turns(_session(_turn_trace("t1", 0, reply=None)).traces)
        assert isinstance(turn.reply, Problem)
        assert turn.reply.kind == "missing"
        assert turn.target_errors == (
            TargetError(
                message="the target returned no reply",
                trace_id="t1",
                observation_id="t1-root",
            ),
        )

    def test_an_error_level_observation_is_a_target_error(self) -> None:
        t = "t1"
        observations = (
            _obs(t, "root", 0, type="SPAN", input="q", output="a"),
            _obs(
                t,
                "tool",
                1,
                type="TOOL",
                name="fetch",
                parent_observation_id="root",
                level="ERROR",
                status_message="timeout",
            ),
            _obs(t, "gen", 2, type="GENERATION", name="llm", level="WARNING"),
        )
        (turn,) = turns(
            _session(Trace(id=t, session_id="s", observations=observations)).traces
        )
        assert [e.message for e in turn.target_errors] == ["timeout", "WARNING on llm"]
        assert turn.target_errors[0].observation_id == "tool"

    def test_a_clean_turn_has_no_target_errors(self) -> None:
        (turn,) = turns(_session(_turn_trace("t1", 0)).traces)
        assert turn.target_errors == ()

    def test_a_chat_message_reply_is_its_text(self) -> None:
        message = {"role": "assistant", "content": "done"}
        (turn,) = turns(_session(_turn_trace("t1", 0, reply=message)).traces)
        assert turn.reply == "done"

    def test_no_traces_is_no_turns(self) -> None:
        assert turns(()) == ()

    def test_turns_takes_traces_directly(self) -> None:
        session = _session(_turn_trace("t1", 0), _turn_trace("t2", 5))
        assert [turn.trace_id for turn in turns(session.traces)] == ["t1", "t2"]


def test_processing_names_no_application() -> None:
    """The processor is generic: no application's names belong in metis-core."""
    source = Path(trace_processing.__file__).read_text(encoding="utf-8").lower()
    for name in ("delegate_to_agent", "form response", "current message"):
        assert name not in source, name
