"""Demo graders on the synthetic helpdesk session.

They show grader authors the full grader pattern on a session with sub-agents. The LLM demos run against a
fake client, so these tests check what each grader sends and how it handles the reply, not
what a real judge would think.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from metis.core.traces import GradingInput, Observation, Trace
from metis.library.grader import JudgeArgs, LLMSettings
from metis.library.graders.demo import (
    DemoAnswerHelpfulnessArgs,
    DemoAnswerHelpfulnessGrader,
    DemoRequiredToolArgs,
    DemoRequiredToolGrader,
    DemoTaskCompletionGrader,
    DemoTraceBudgetArgs,
    DemoTraceBudgetGrader,
)
from tests.fixtures.criterion_judge import judge_client
from tests.fixtures.traces import load_session

if TYPE_CHECKING:
    from metis.core.grading import GradingOutput
    from metis.library.grader import Grader

MET = {"status": "scored", "score": 1, "reason": "Helpful."}
UNMET = {"status": "scored", "score": 0, "reason": "No answer."}


def _run(
    grader: Grader, gi: GradingInput, reply: object = MET
) -> tuple[GradingOutput, list[dict[str, Any]]]:
    requests: list[dict[str, Any]] = []
    content = reply if isinstance(reply, str) else json.dumps(reply)
    client = judge_client(content, requests)

    async def run():
        async with client:
            return await grader.grade(gi, LLMSettings(client))

    return asyncio.run(run()), requests


def _evidence(request: dict[str, Any]) -> str:
    [content] = request["input"][1]["content"]
    return content["text"]


HELPFULNESS = DemoAnswerHelpfulnessGrader(
    DemoAnswerHelpfulnessArgs(model="judge-model")
)
COMPLETION = DemoTaskCompletionGrader(JudgeArgs(model="judge-model"))


class TestRequiredTool:
    def test_required_tool_finds_build_report_deep_in_turn_5(self) -> None:
        out, requests = _run(
            DemoRequiredToolGrader(DemoRequiredToolArgs(tool_name="build_report")),
            load_session(),
        )
        (result,) = out.results
        assert (result.status, result.score, result.scope) == ("scored", 1.0, "session")
        assert "turn 5" in result.reason
        assert "Report_Writer.arun" in result.reason
        assert requests == []

    def test_required_tool_absent_scores_zero(self) -> None:
        out, _ = _run(
            DemoRequiredToolGrader(DemoRequiredToolArgs(tool_name="send_email")),
            load_session(),
        )
        (result,) = out.results
        assert (result.status, result.score) == ("scored", 0.0)


class TestAnswerHelpfulness:
    def test_each_turn_is_judged_with_the_turns_before_it(self) -> None:
        out, requests = _run(HELPFULNESS, load_session())
        assert [(r.status, r.score, r.scope) for r in out.results] == [
            ("scored", 1.0, f"turns:1-{n}") for n in range(1, 6)
        ]
        third = _evidence(requests[2])
        assert "## Turn 1" in third and "## Turn 3" in third
        assert "## Turn 4" not in third

    def test_the_judge_model_is_the_one_configured(self) -> None:
        _, requests = _run(HELPFULNESS, load_session())
        assert requests[0]["model"] == "judge-model"

    def test_a_window_limits_the_turns_the_judge_sees(self) -> None:
        grader = DemoAnswerHelpfulnessGrader(
            DemoAnswerHelpfulnessArgs(model="judge-model", window=2)
        )
        out, requests = _run(grader, load_session())
        assert out.results[-1].scope == "turns:4-5"
        assert "## Turn 3" not in _evidence(requests[-1])


class TestTaskCompletion:
    def test_task_completion_gives_one_result_for_the_session(self) -> None:
        out, [request] = _run(COMPLETION, load_session())
        (result,) = out.results
        assert (result.status, result.score, result.scope) == ("scored", 1.0, "session")
        assert "## Turn 5" in _evidence(request)
        assert "Collect everything the user asked for" in request["input"][0]["content"]


def test_an_off_menu_judge_reply_is_errored() -> None:
    for reply in (
        "looks good",
        '{"reason": "x"}',
        '{"status": "scored", "score": 0.7, "reason": "x"}',
    ):
        out, _ = _run(COMPLETION, load_session(), reply)
        (result,) = out.results
        assert result.status == "errored", reply
        assert result.score is None


def test_every_demo_errors_on_an_empty_session() -> None:
    graders: list[Grader] = [
        DemoTraceBudgetGrader(DemoTraceBudgetArgs()),
        DemoRequiredToolGrader(DemoRequiredToolArgs(tool_name="build_report")),
        HELPFULNESS,
        COMPLETION,
    ]
    for grader in graders:
        out, requests = _run(grader, GradingInput(traces=()))
        (result,) = out.results
        assert result.status == "errored", type(grader).__name__
        assert requests == []


def test_demos_produce_different_units_from_one_session() -> None:
    """The same saved data, without the target or the network, yields different units."""
    gi = load_session()
    per_turn, _ = _run(HELPFULNESS, gi)
    per_session, _ = _run(COMPLETION, gi)
    assert (len(per_turn.results), len(per_session.results)) == (5, 1)


def test_demos_are_not_in_the_catalogue() -> None:
    import metis.library.graders as catalog

    assert not [name for name in vars(catalog) if name.startswith("Demo")]


def _one_turn(output: object) -> GradingInput:
    return GradingInput(
        traces=(
            Trace(
                id="t1",
                session_id="s",
                observations=(
                    Observation(
                        id="root",
                        trace_id="t1",
                        type="SPAN",
                        input="help me",
                        output=output,
                        start_time=datetime(2026, 1, 1, tzinfo=UTC),
                    ),
                ),
            ),
        )
    )


def test_a_turn_the_target_crashed_on_is_judged() -> None:
    """No reply is the target's failure, so it is evidence to grade, never an error (#431)."""
    out, [request] = _run(HELPFULNESS, _one_turn(None), UNMET)
    (result,) = out.results
    assert (result.status, result.score) == ("scored", 0.0)
    assert "[target error: the target returned no reply]" in _evidence(request)
