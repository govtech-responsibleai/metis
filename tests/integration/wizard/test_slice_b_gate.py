"""Slice B gate: the whole interview walks to DONE through the turn contract, with no network.

The corridor is proven here — `handle_interview`, the driver, the screens and patch application — on a
scripted stand-in for the model. Every turn round-trips the client-held state through JSON, so the
gate also proves the interview survives the wire. Nothing in this file touches a gateway.
"""

from pathlib import Path

from metis.wizard import compile_specification
from metis.wizard.application.config import clarify_turn_cap
from metis.wizard.contracts import (
    ChatRequest,
    ChoiceRequest,
    FormRequest,
    WarningSource,
)
from metis.wizard.contracts.interview_state import HISTORY_LIMIT
from tests.fixtures.wizard.scripted import (
    RejectingInterviewer,
    ScriptedInterviewer,
    walk,
)


def test_the_whole_flow_walks_to_done() -> None:
    interviewer = ScriptedInterviewer(clarify_questions=clarify_turn_cap())

    result = walk(interviewer)

    assert result.state.confirmed
    assert result.state.pending is None
    assert result.used_end
    assert "It answers research questions." in result.state.specification.target.detail
    assert {ChatRequest, ChoiceRequest, FormRequest} <= {
        type(request) for request in result.seen
    }
    stages = [request.stage for request in result.seen]
    first_criteria = stages.index("criteria")
    assert "behaviours" in stages[first_criteria + 1 :]
    assert any(
        not behaviour.measured for behaviour in result.state.specification.behaviours()
    )
    # every drafting step was reached
    assert {
        "clarify",
        "draft_behaviours",
        "draft_criteria",
        "draft_personas",
        "draft_scenarios",
        "draft_test_cases",
    } <= set(interviewer.calls)


def test_it_produces_an_experiment_the_engine_loads(tmp_path: Path) -> None:
    result = walk(ScriptedInterviewer())

    compiled = compile_specification(result.state.specification)
    experiment_path = tmp_path / "specification.yaml"
    experiment_path.write_text(compiled.specification_yaml, encoding="utf-8")

    from metis.engine.simulation.types import Specification

    assert Specification.load_file(experiment_path).scenarios


def test_the_state_on_the_wire_stays_bounded() -> None:
    """The client-held state carries the interview, not a transcript — it must stay small.

    At DONE there is no live screen, the clarification history never grows past its limit, and the
    state holds no resolved-request log or document bytes. This is what keeps a stateless HTTP turn
    cheap however long the interview ran.
    """
    result = walk(ScriptedInterviewer())

    assert result.state.pending is None  # one live screen at most, and none at DONE
    assert (
        len(result.state.history) <= HISTORY_LIMIT
    )  # trimmed, not an ever-growing log
    # The largest payload seen across the whole walk stays well inside a request body — the
    # state carries the interview, not a transcript. (The field set itself is fixed in
    # tests/contracts/test_interview_state.py.)
    assert result.max_state_bytes < 32_768


def test_a_rejected_patch_reaches_the_user_as_a_runtime_warning() -> None:
    """The model tries to set a tick. The criteria land; the write does not, and is said."""
    result = walk(RejectingInterviewer())

    runtime = [
        w
        for request in result.seen
        if isinstance(request, ChoiceRequest)
        for w in request.warnings
        if w.source is WarningSource.RUNTIME
    ]
    assert runtime, "the refusal should have been shown, not swallowed"
    assert "scope you selected" in runtime[0].text
    assert not runtime[0].blocking
