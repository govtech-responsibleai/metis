"""The synthetic helpdesk session that demo graders and processor tests share.

The counts below are what ``tests.fixtures.traces._helpdesk`` builds. A change to the session
changes them, so re-derive the expected values from the new session instead of editing them to
match.
"""

from __future__ import annotations

from metis.core.trace_processing import turns
from tests.fixtures.traces import load_session


def test_fixture_matches_the_built_session() -> None:
    gi = load_session()
    assert len(gi.traces) == 5
    assert sum(len(t.observations) for t in gi.traces) == 33
    session_turns = turns(gi.traces)
    assert sum(len(turn.tool_calls) for turn in session_turns) == 7
    last = session_turns[4].tool_calls[-1]
    assert (last.name, last.agent) == ("build_report", "Report_Writer.arun")


def test_every_root_resolves_to_the_turn_span() -> None:
    assert all(t.root.parent_observation_id is None for t in load_session().traces)


def test_structured_payloads_are_parsed() -> None:
    observations = [o for t in load_session().traces for o in t.observations]
    assert not [
        o.name for o in observations if o.type == "TOOL" and isinstance(o.input, str)
    ]
    assert not [
        o.name
        for o in observations
        if o.type == "GENERATION" and isinstance(o.input, str)
    ]


def test_the_last_turn_still_holds_the_users_message() -> None:
    """The user's form response sits at the end of a long message; it must be kept whole."""
    user = turns(load_session().traces)[4].user
    assert isinstance(user, str)
    assert '"audience":"support managers"' in user


def test_a_python_syntax_tool_result_reaches_graders_as_text() -> None:
    (call,) = turns(load_session().traces)[0].tool_calls
    assert call.name == "delegate_to_agent"
    assert isinstance(call.observation.output, str)
    assert call.observation.output.startswith("{'_type'")
