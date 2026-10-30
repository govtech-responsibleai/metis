"""The select and render functions, find_artifacts and find_fixtures (#431).

The transcript is the one text view every LLM judge sees, so its layout is pinned exactly.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from pathlib import Path

import pytest

from metis.core import Artifact
from metis.core.trace_processing import (
    FileInput,
    Problem,
    find_artifacts,
    find_fixtures,
    render_artifact,
    render_dialogue,
    render_session,
    select_by_artifact,
    select_by_turn,
    select_by_window,
    select_session,
    turns,
)
from metis.core.traces import GradingInput, Observation, Trace


def _t(second: int) -> datetime:
    return datetime(2026, 1, 1, 0, 0, second, tzinfo=UTC)


def _session(*, reply: object = "a") -> GradingInput:
    t = "t1"
    observations = (
        Observation(
            id="root",
            trace_id=t,
            type="SPAN",
            input="q",
            output=reply,
            start_time=_t(0),
        ),
        Observation(
            id="agent",
            trace_id=t,
            type="AGENT",
            name="A",
            parent_observation_id="root",
            start_time=_t(1),
        ),
        Observation(
            id="tool",
            trace_id=t,
            type="TOOL",
            name="search",
            input={"q": "x"},
            parent_observation_id="agent",
            start_time=_t(2),
        ),
    )
    return GradingInput(
        traces=(Trace(id=t, session_id="s", observations=observations),)
    )


def test_transcript_tags_each_part_in_order() -> None:
    assert render_session(turns(_session().traces)) == (
        '## Turn 1\nUser: q\nTool search (A): {"q": "x"}\nAssistant: a'
    )


def test_transcript_marks_unreadable_and_target_errors() -> None:
    text = render_session(turns(_session(reply=None).traces))
    assert "Assistant: [unreadable: missing: no value]" in text
    assert text.endswith("[target error: the target returned no reply]")


def test_turns_are_separated_by_a_blank_line() -> None:
    gi = _session()
    two = GradingInput(traces=gi.traces * 2)
    assert render_session(turns(two.traces)).count("\n\n## Turn ") == 1


def test_dialogue_keeps_only_the_user_and_assistant_lines() -> None:
    assert render_dialogue(turns(_session().traces)) == (
        "## Turn 1\nUser: q\nAssistant: a"
    )


def test_assistant_only_dialogue_keeps_only_the_replies() -> None:
    assert render_dialogue(turns(_session().traces), assistant_only=True) == (
        "## Turn 1\nAssistant: a"
    )


def _tool_session(arguments: object = None, **tool: object) -> GradingInput:
    t = "t1"
    observations = (
        Observation(id="root", trace_id=t, input="q", output="done", start_time=_t(0)),
        Observation(
            id="tool",
            trace_id=t,
            type="TOOL",
            name="search",
            input=arguments or {"q": "x"},
            parent_observation_id="root",
            start_time=_t(1),
            **tool,  # type: ignore[arg-type]
        ),
    )
    return GradingInput(
        traces=(Trace(id=t, session_id="s", observations=observations),)
    )


def test_tool_results_follow_each_call_with_its_status() -> None:
    gi = _tool_session(
        output="ERROR: index unavailable",
        level="ERROR",
        status_message="index unavailable",
    )
    assert render_session(turns(gi.traces), tool_results=True) == (
        "## Turn 1\nUser: q\n"
        'Tool search: {"q": "x"}\n'
        "Tool result [error: index unavailable]: ERROR: index unavailable\n"
        "Assistant: done"
    )


def test_a_tool_warning_is_labelled_a_warning() -> None:
    gi = _tool_session(output="slow", level="WARNING", status_message="slow upstream")
    text = render_session(turns(gi.traces), tool_results=True)
    assert "Tool result [warning: slow upstream]: slow" in text


def test_the_default_transcript_shows_no_tool_results() -> None:
    gi = _tool_session(output={"hits": 2})
    assert render_session(turns(gi.traces)) == (
        '## Turn 1\nUser: q\nTool search: {"q": "x"}\nAssistant: done'
    )


def test_max_chars_cuts_long_arguments_and_results() -> None:
    gi = _tool_session({"q": "y" * 700}, output="x" * 700)
    text = render_session(turns(gi.traces), tool_results=True, max_chars=600)
    assert f"Tool result [ok]: {'x' * 600} …[cut off]" in text
    assert "…[cut off]\nTool result" in text
    uncut = render_session(turns(gi.traces), tool_results=True)
    assert "cut off" not in uncut


def _artifact(name: str, **fields: object) -> Artifact:
    defaults: dict[str, object] = {
        "source": "target",
        "state": "received",
        "path": f"/tmp/{name}",
    }
    defaults.update(fields)
    return Artifact(name=name, **defaults)  # type: ignore[arg-type]


def test_find_artifacts_returns_every_received_target_match() -> None:
    first = _artifact("deck.pptx", path="/tmp/1/deck.pptx")
    second = _artifact("deck.pptx", path="/tmp/2/deck.pptx")
    gi = GradingInput(
        traces=(),
        artifacts=(
            first,
            _artifact("deck.pptx", source="fixture"),
            _artifact("deck.pptx", state="unavailable", path=None),
            _artifact("other.docx"),
            second,
        ),
    )
    assert find_artifacts(gi, "deck.pptx") == (first, second)


def test_find_fixtures_returns_every_received_file_the_user_gave() -> None:
    brief = _artifact("brief.pdf", source="fixture")
    data = _artifact("data.csv", source="fixture")
    gi = GradingInput(
        traces=(),
        artifacts=(
            brief,
            _artifact("deck.pptx"),
            _artifact("lost.csv", source="fixture", state="unavailable", path=None),
            data,
        ),
    )
    assert find_fixtures(gi) == (brief, data)
    assert find_fixtures(GradingInput(traces=())) == ()


def test_find_artifacts_with_no_match_is_artifact_unavailable() -> None:
    problem = find_artifacts(GradingInput(traces=()), "deck.pptx")
    assert isinstance(problem, Problem)
    assert problem.kind == "artifact_unavailable"
    assert "deck.pptx" in problem.detail


def _turns(count: int, *, last_reply: object = "a"):
    replies = ["a"] * (count - 1) + [last_reply]
    return turns(
        tuple(
            Trace(
                id=f"t{i}",
                session_id="s",
                observations=(
                    Observation(id=f"r{i}", trace_id=f"t{i}", input="q", output=reply),
                ),
            )
            for i, reply in enumerate(replies)
        )
    )


def test_select_by_turn_gives_each_turn_on_its_own() -> None:
    selected = select_by_turn(_turns(3))
    assert not isinstance(selected, Problem)
    assert {label: [t.index for t in turns_] for label, turns_ in selected.items()} == {
        "turn:1": [0],
        "turn:2": [1],
        "turn:3": [2],
    }
    last = select_by_turn(_turns(3), last_only=True)
    assert not isinstance(last, Problem)
    assert list(last) == ["turn:3"]


def test_an_unreadable_reply_is_a_problem_that_render_passes_through() -> None:
    selected = select_by_turn(_turns(1, last_reply=42))
    assert not isinstance(selected, Problem)
    problem = selected["turn:1"]
    assert isinstance(problem, Problem)
    assert "turn 1 cannot be read" in problem.detail
    assert render_session(problem) is problem


def test_select_by_window_ends_a_window_at_each_turn() -> None:
    selected = select_by_window(_turns(4), 3)
    assert not isinstance(selected, Problem)
    assert {label: [t.index for t in turns_] for label, turns_ in selected.items()} == {
        "turns:1-1": [0],
        "turns:1-2": [0, 1],
        "turns:1-3": [0, 1, 2],
        "turns:2-4": [1, 2, 3],
    }
    last = select_by_window(_turns(4), 3, last_only=True)
    assert not isinstance(last, Problem)
    assert list(last) == ["turns:2-4"]


def test_a_window_with_no_size_holds_every_turn_before_it() -> None:
    selected = select_by_window(_turns(3))
    assert not isinstance(selected, Problem)
    assert {label: len(turns_) for label, turns_ in selected.items()} == {
        "turns:1-1": 1,
        "turns:1-2": 2,
        "turns:1-3": 3,
    }


def test_select_session_gives_every_turn() -> None:
    selected = select_session(_turns(2))
    assert not isinstance(selected, Problem)
    assert {label: len(turns_) for label, turns_ in selected.items()} == {"session": 2}


def test_an_empty_session_selects_nothing() -> None:
    for selected in (select_by_turn(()), select_by_window(()), select_session(())):
        assert isinstance(selected, Problem)
        assert selected.detail == "The session has no turns."


def test_select_by_artifact_gives_the_latest_revision_of_the_file() -> None:
    gi = GradingInput(
        traces=(),
        artifacts=(
            _artifact("deck.pptx", path="/tmp/turn3/deck.pptx", at_simulated_turn=3),
            _artifact("deck.pptx", path="/tmp/turn1/deck.pptx", at_simulated_turn=1),
            _artifact("deck.pptx", path="/tmp/unknown/deck.pptx"),
            _artifact(
                "deck.pptx", path="/tmp/turn3-later/deck.pptx", at_simulated_turn=3
            ),
            _artifact("other.docx", at_simulated_turn=4),
        ),
    )
    selected = select_by_artifact(gi, "deck.pptx")
    assert not isinstance(selected, Problem)
    assert {label: str(path) for label, path in selected.items()} == {
        "artifact:deck.pptx": "/tmp/turn3-later/deck.pptx"
    }


def test_select_by_artifact_without_turns_keeps_the_last_listed_revision() -> None:
    gi = GradingInput(
        traces=(),
        artifacts=(
            _artifact("deck.pptx", path="/tmp/1/deck.pptx"),
            _artifact("deck.pptx", path="/tmp/2/deck.pptx"),
        ),
    )
    selected = select_by_artifact(gi, "deck.pptx")
    assert not isinstance(selected, Problem)
    assert str(selected["artifact:deck.pptx"]) == "/tmp/2/deck.pptx"


def test_select_by_artifact_with_no_such_file_is_a_problem() -> None:
    gi = GradingInput(traces=(), artifacts=(_artifact("other.docx"),))
    missing = select_by_artifact(gi, "report.pdf")
    assert isinstance(missing, Problem)
    assert missing.detail == "No received target file named 'report.pdf'."


def test_render_artifact_sends_the_file_as_base64_data(tmp_path: Path) -> None:
    report = tmp_path / "report.pdf"
    report.write_bytes(b"%PDF-1.4 body")
    rendered = render_artifact(report)
    assert isinstance(rendered, FileInput)
    assert rendered.filename == "report.pdf"
    prefix, data = rendered.data_url.split(",", 1)
    assert prefix == "data:application/pdf;base64"
    assert base64.b64decode(data) == b"%PDF-1.4 body"


def test_render_artifact_of_a_missing_file_is_a_problem(tmp_path: Path) -> None:
    rendered = render_artifact(tmp_path / "gone.docx")
    assert isinstance(rendered, Problem)
    assert "cannot be read" in rendered.detail


def _agent_session() -> GradingInput:
    """A planner that thinks, hands work to a researcher, and replies."""
    t = "t1"
    system = {"role": "system", "content": "You plan trips."}
    observations = (
        Observation(
            id="root",
            trace_id=t,
            type="SPAN",
            input="Plan Osaka",
            output="Here is your plan.",
            start_time=_t(0),
        ),
        Observation(
            id="planner",
            trace_id=t,
            type="AGENT",
            name="planner",
            parent_observation_id="root",
            start_time=_t(1),
        ),
        Observation(
            id="think",
            trace_id=t,
            type="GENERATION",
            name="llm",
            parent_observation_id="planner",
            start_time=_t(2),
            input={"messages": [system, {"role": "user", "content": "Plan Osaka"}]},
            output={"role": "assistant", "content": "I should ask the researcher."},
        ),
        Observation(
            id="researcher",
            trace_id=t,
            type="AGENT",
            name="researcher",
            parent_observation_id="planner",
            input="Find hotels",
            output="Hotel A",
            start_time=_t(3),
            end_time=_t(6),
        ),
        Observation(
            id="tool",
            trace_id=t,
            type="TOOL",
            name="search",
            parent_observation_id="researcher",
            input={"q": "hotels"},
            output=[{"name": "Hotel A"}],
            start_time=_t(4),
        ),
        Observation(
            id="retry",
            trace_id=t,
            type="GENERATION",
            name="llm",
            parent_observation_id="researcher",
            level="ERROR",
            status_message="rate limited",
            start_time=_t(5),
        ),
        Observation(
            id="final",
            trace_id=t,
            type="GENERATION",
            name="llm",
            parent_observation_id="planner",
            start_time=_t(7),
            input={"messages": [system, {"role": "user", "content": "Plan Osaka"}]},
            output={"role": "assistant", "content": "Here is your plan."},
        ),
    )
    return GradingInput(
        traces=(Trace(id=t, session_id="s", observations=observations),)
    )


def test_the_session_shows_every_recorded_event_in_time_order() -> None:
    assert render_session(turns(_agent_session().traces), tool_results=True) == (
        "## Turn 1\nUser: Plan Osaka\n"
        "System prompt (planner): You plan trips.\n"
        "Model (planner): I should ask the researcher.\n"
        "Handoff to researcher (from planner): Find hotels\n"
        'Tool search (researcher): {"q": "hotels"}\n'
        'Tool result [ok]: [{"name": "Hotel A"}]\n'
        "[error on GENERATION llm (researcher): rate limited]\n"
        "researcher returned (to planner): Hotel A\n"
        "Assistant: Here is your plan."
    )


def test_a_structured_model_output_is_shown_as_recorded() -> None:
    action = '{"kind": "answer", "markdown": "Revenue rose.", "references": [{"section": "Overview"}]}'
    rows = (
        {"id": "root", "traceId": "t1", "input": "q", "output": "Revenue rose."},
        {
            "id": "llm",
            "traceId": "t1",
            "type": "GENERATION",
            "parentObservationId": "root",
            "output": action,
        },
    )
    trace = Trace(
        id="t1",
        session_id="s",
        observations=tuple(Observation.model_validate(row) for row in rows),
    )
    assert render_session(turns((trace,))) == (
        f"## Turn 1\nUser: q\nModel: {action}\nAssistant: Revenue rose."
    )


def test_a_system_prompt_is_shown_once_per_session() -> None:
    gi = _agent_session()
    two = GradingInput(traces=gi.traces * 2)
    assert render_session(turns(two.traces)).count("System prompt (planner)") == 1


@pytest.mark.parametrize(
    ("output", "reply"),
    [
        ('{\n  "total": 10.50\n}', '{\n  "total": 10.50\n}'),
        ({"total": 10.5}, '{"total": 10.5}'),
    ],
)
def test_a_json_reply_is_shown_as_recorded(output: object, reply: str) -> None:
    row = {"id": "root", "traceId": "t1", "input": "q", "output": output}
    trace = Trace(
        id="t1", session_id="s", observations=(Observation.model_validate(row),)
    )
    [turn] = turns((trace,))
    assert turn.reply == reply
