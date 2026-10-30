"""The turn loop, driven by a scripted runner and a scripted user agent."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
import structlog.testing

from metis.core.trials import TrialConfig, TrialRecord
from metis.engine.simulation._fixture_artifacts import build_fixture_artifacts
from metis.engine.simulation.exceptions import (
    ConsecutiveFailureEscalation,
    ResponseTimeoutError,
    TargetSessionEnded,
    TrialRecoverableError,
    TurnRecoverableError,
    UserAgentUnavailableError,
)
from metis.engine.simulation.orchestrator import Orchestrator
from metis.engine.simulation.runner import Runner
from metis.engine.simulation.types import (
    Observation,
    Promise,
    Reading,
    Scenario,
    UserAgentOutput,
)

if TYPE_CHECKING:
    from pathlib import Path

    from metis.core import Artifact


def _observation(reply: str = "ok", **kwargs: Any) -> Observation:
    return Observation(
        reply=reply,
        reading=Reading(outcome="sent", why="the message went through"),
        **kwargs,
    )


@dataclass
class Step:
    """What one scripted ``act`` does: records files, then answers or raises."""

    observation: Observation | None = None
    raises: Exception | None = None
    uploads: list[str] = field(default_factory=list)
    unfetched: list[str] = field(default_factory=list)
    downloads: dict[str, bytes] = field(default_factory=dict)
    set_event: threading.Event | None = None


class FakeRunner(Runner):
    """A runner that follows a script and records what it was asked."""

    def __init__(self, script: list[Step], *, late: dict[str, bytes] | None = None):
        self._script = script
        self._late = late or {}
        self.events: list[str] = []
        self.actions: list[str] = []
        self.promised_seen: list[list[Promise]] = []
        self.turn = 0
        self._session_id: str | None = None

    @property
    def session_id(self) -> str | None:
        return self._session_id

    async def setup(self, config: TrialConfig) -> None:
        self.events.append("setup")

    async def act(self, action: str, promised: list[Promise]) -> Observation:
        self.turn += 1
        self.events.append("act")
        self.actions.append(action)
        self.promised_seen.append(list(promised))
        step = self._script[self.turn - 1]
        self._session_id = "sess-1"
        if step.set_event is not None:
            step.set_event.set()
        for name in step.uploads:
            self.ledger.record_upload(name, at_simulated_turn=self.turn)
        for name in step.unfetched:
            self.ledger.record_failure(
                name, "unfetched", "404", at_simulated_turn=self.turn
            )
        for name, data in step.downloads.items():
            self.ledger.record_download(name, data, at_simulated_turn=self.turn)
        if step.raises is not None:
            raise step.raises
        assert step.observation is not None
        return step.observation

    async def end_chat(self, promised: list[Promise]) -> None:
        self.events.append("end_chat")
        for name, data in self._late.items():
            self.ledger.record_download(name, data, at_simulated_turn=self.turn)

    async def teardown(self) -> None:
        self.events.append("teardown")


class ScriptedAgent:
    """A user agent that plays back decisions and records what it was shown."""

    def __init__(self, outputs: list[UserAgentOutput | Exception]) -> None:
        self._outputs = outputs
        self.turns: list[int] = []
        self.held: list[list[str]] = []
        self.promised: list[list[str]] = []
        self.remembered: list[Observation] = []

    async def decide(
        self, turn: int, held: list[Artifact], promised: list[Promise]
    ) -> UserAgentOutput:
        self.turns.append(turn)
        self.held.append([a.name for a in held])
        self.promised.append([p.name for p in promised])
        out = self._outputs[min(len(self.turns), len(self._outputs)) - 1]
        if isinstance(out, Exception):
            raise out
        return out

    def remember(self, output: UserAgentOutput, observation: Observation) -> None:
        self.remembered.append(observation)


def _go(action: str = "Say ⟦hi⟧") -> UserAgentOutput:
    return UserAgentOutput(reasoning="r", action=action, decision="continue")


def _done(decision: str = "goal_achieved") -> UserAgentOutput:
    return UserAgentOutput(reasoning="r", action="", decision=decision)


def _build(
    tmp_path: Path,
    runner: FakeRunner,
    agent: ScriptedAgent,
    *,
    fixtures: list[str] | None = None,
    max_turns: int = 20,
    timeout_minutes: int = 15,
    state: Any = None,
    tui_ctx: Any = None,
    shutdown_event: threading.Event | None = None,
) -> Orchestrator:
    fixtures = fixtures or []
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir(exist_ok=True)
    (fixtures_dir / "q3_sales.csv").write_text("region,amount\nN,1\nS,2\n")
    run_dir = tmp_path / "outputs" / "trials" / "t1"
    run_dir.mkdir(parents=True)
    config = TrialConfig(
        persona="p1",
        scenario="s1",
        max_turns=max_turns,
        timeout_minutes=timeout_minutes,
        fixtures=fixtures,
    )
    return Orchestrator(
        runner=runner,
        agent=agent,
        trial_config=config,
        scenario=Scenario(
            id="s1", description="goal", persona_refs=["p1"], fixtures=fixtures
        ),
        run_dir=run_dir,
        experiment_root=tmp_path,
        fixture_artifacts=build_fixture_artifacts(fixtures, fixtures_dir, tmp_path),
        trial_index=1,
        state=state,
        tui_ctx=tui_ctx,
        shutdown_event=shutdown_event,
    )


@pytest.mark.asyncio
async def test_full_trial_writes_a_record_that_load_file_reads(tmp_path: Path) -> None:
    runner = FakeRunner(
        [
            Step(_observation("got the file"), uploads=["q3_sales.csv"]),
            Step(
                _observation("here is the report"),
                downloads={"report.csv": b"a,b\n1,2\n"},
            ),
        ],
        late={"chart.vl.json": b"{}"},
    )
    agent = ScriptedAgent([_go("Upload q3_sales.csv"), _go(), _done()])
    orch = _build(tmp_path, runner, agent, fixtures=["q3_sales.csv"])

    record = await orch.execute()

    path = tmp_path / "record.json"
    path.write_text(json.dumps(record.model_dump()), encoding="utf-8")
    loaded = TrialRecord.load_file(path)
    assert loaded.outcome.stop_reason == "goal_achieved"
    assert loaded.outcome.simulated_turns_completed == 2
    assert loaded.target_session_id == "sess-1"
    assert [(a.name, a.source, a.at_simulated_turn) for a in loaded.artifacts] == [
        ("q3_sales.csv", "fixture", 1),
        ("report.csv", "target", 2),
        ("chart.vl.json", "target", 2),
    ]
    assert runner.events == ["setup", "act", "act", "end_chat", "teardown"]


@pytest.mark.asyncio
async def test_a_fixture_uploaded_twice_is_one_entry(tmp_path: Path) -> None:
    runner = FakeRunner(
        [
            Step(_observation(), uploads=["q3_sales.csv"]),
            Step(_observation(), uploads=["q3_sales.csv"]),
        ]
    )
    orch = _build(
        tmp_path,
        runner,
        ScriptedAgent([_go(), _go(), _done()]),
        fixtures=["q3_sales.csv"],
    )

    record = await orch.execute()

    assert [(a.name, a.at_simulated_turn) for a in record.artifacts] == [
        ("q3_sales.csv", 1)
    ]


@pytest.mark.asyncio
async def test_the_user_agent_is_shown_the_fixture_before_any_turn(
    tmp_path: Path,
) -> None:
    agent = ScriptedAgent([_done()])
    orch = _build(tmp_path, FakeRunner([]), agent, fixtures=["q3_sales.csv"])

    await orch.execute()

    assert agent.held == [["q3_sales.csv"]]


@pytest.mark.asyncio
async def test_closing_call_is_not_a_turn(tmp_path: Path) -> None:
    runner = FakeRunner([Step(_observation())], late={"late.txt": b"x"})
    orch = _build(tmp_path, runner, ScriptedAgent([_go(), _done()]))

    record = await orch.execute()

    assert record.outcome.simulated_turns_completed == 1
    assert [(a.name, a.at_simulated_turn) for a in record.artifacts] == [
        ("late.txt", 1)
    ]


@pytest.mark.asyncio
async def test_no_closing_call_when_no_action_was_taken(tmp_path: Path) -> None:
    runner = FakeRunner([])
    orch = _build(tmp_path, runner, ScriptedAgent([_done("giving_up")]))

    record = await orch.execute()

    assert record.outcome.stop_reason == "user_abandoned"
    assert record.outcome.simulated_turns_completed == 0
    assert runner.events == ["setup", "teardown"]


@pytest.mark.asyncio
async def test_max_turns_stops_without_asking_the_user_again(tmp_path: Path) -> None:
    runner = FakeRunner([Step(_observation()) for _ in range(3)])
    agent = ScriptedAgent([_go()])
    orch = _build(tmp_path, runner, agent, max_turns=3)

    record = await orch.execute()

    assert record.outcome.stop_reason == "max_turns"
    assert record.outcome.simulated_turns_completed == 3
    assert agent.turns == [1, 2, 3]
    assert runner.events[-2:] == ["end_chat", "teardown"]


@pytest.mark.asyncio
async def test_timeout_stops_before_the_first_turn(tmp_path: Path) -> None:
    runner = FakeRunner([])
    orch = _build(tmp_path, runner, ScriptedAgent([_go()]), timeout_minutes=0)

    record = await orch.execute()

    assert record.outcome.stop_reason == "timeout"
    assert record.outcome.simulated_turns_completed == 0


@pytest.mark.asyncio
async def test_set_shutdown_event_ends_the_trial_cleanly(tmp_path: Path) -> None:
    event = threading.Event()
    event.set()
    runner = FakeRunner([])
    orch = _build(tmp_path, runner, ScriptedAgent([_go()]), shutdown_event=event)

    record = await orch.execute()

    assert record.outcome.stop_reason == "interrupted"
    assert runner.events == ["setup", "teardown"]


@pytest.mark.asyncio
async def test_shutdown_during_a_turn_keeps_that_turn_and_skips_the_closing_call(
    tmp_path: Path,
) -> None:
    event = threading.Event()
    runner = FakeRunner([Step(_observation(), set_event=event)])
    orch = _build(tmp_path, runner, ScriptedAgent([_go()]), shutdown_event=event)

    record = await orch.execute()

    assert record.outcome.stop_reason == "interrupted"
    assert record.outcome.simulated_turns_completed == 1
    assert runner.events == ["setup", "act", "teardown"]


@pytest.mark.asyncio
async def test_progress_state_advances_each_turn(tmp_path: Path) -> None:
    state, tui_ctx = MagicMock(), MagicMock()
    runner = FakeRunner([Step(_observation()) for _ in range(2)])
    orch = _build(
        tmp_path,
        runner,
        ScriptedAgent([_go()]),
        max_turns=2,
        state=state,
        tui_ctx=tui_ctx,
    )

    await orch.execute()

    turns = [c.kwargs["turn"] for c in state.mark_trial_turn.call_args_list]
    assert sorted(set(turns)) == [1, 2]
    assert turns == sorted(turns)
    for call in state.mark_trial_turn.call_args_list:
        assert call.args == ("s1", "p1")
        assert call.kwargs["trial_index"] == 1
        assert call.kwargs["max_turns"] == 2
    assert tui_ctx.refresh.call_count == state.mark_trial_turn.call_count


@pytest.mark.asyncio
async def test_target_session_ended_is_target_exhausted(tmp_path: Path) -> None:
    runner = FakeRunner([Step(raises=TargetSessionEnded("spent"))])
    orch = _build(tmp_path, runner, ScriptedAgent([_go()]))

    record = await orch.execute()

    assert record.outcome.stop_reason == "target_exhausted"
    assert record.target_session_id == "sess-1"
    assert "end_chat" not in runner.events
    assert runner.events[-1] == "teardown"


@pytest.mark.asyncio
async def test_a_failing_user_agent_is_a_system_error(tmp_path: Path) -> None:
    runner = FakeRunner([Step(_observation())])
    orch = _build(tmp_path, runner, ScriptedAgent([_go(), RuntimeError("llm down")]))

    record = await orch.execute()

    assert record.outcome.stop_reason == "system_error"
    assert record.outcome.simulated_turns_completed == 1
    assert "end_chat" not in runner.events


@pytest.mark.asyncio
async def test_an_unavailable_user_agent_raises_so_the_trial_is_retried(
    tmp_path: Path,
) -> None:
    runner = FakeRunner([Step(_observation())])
    orch = _build(
        tmp_path,
        runner,
        ScriptedAgent([_go(), UserAgentUnavailableError("gateway down")]),
    )

    with pytest.raises(UserAgentUnavailableError):
        await orch.execute()

    assert orch.partial_record("system_error").outcome.simulated_turns_completed == 1
    assert runner.events[-1] == "teardown"


@pytest.mark.asyncio
async def test_a_recoverable_turn_error_counts_and_tells_the_user(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(
        [Step(raises=TurnRecoverableError("dom")), Step(_observation())]
    )
    agent = ScriptedAgent([_go(), _go(), _done()])
    orch = _build(tmp_path, runner, agent)

    record = await orch.execute()

    assert record.outcome.simulated_turns_completed == 2
    failed = agent.remembered[0]
    assert failed.reply is None
    assert failed.observed is False
    assert failed.notice
    assert agent.remembered[1].notice is None


@pytest.mark.asyncio
async def test_a_timed_out_reply_is_told_apart_from_an_unsent_message(
    tmp_path: Path,
) -> None:
    runner = FakeRunner([Step(raises=ResponseTimeoutError("slow"))])
    agent = ScriptedAgent([_go(), _done()])

    await _build(tmp_path, runner, agent).execute()

    assert "timeout" in (agent.remembered[0].notice or "").lower()


@pytest.mark.asyncio
async def test_two_consecutive_turn_errors_escalate_and_keep_progress(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(
        [
            Step(_observation(), downloads={"a.txt": b"x"}),
            Step(raises=TurnRecoverableError("1")),
            Step(raises=TurnRecoverableError("2")),
        ]
    )
    orch = _build(tmp_path, runner, ScriptedAgent([_go()]))

    with pytest.raises(ConsecutiveFailureEscalation):
        await orch.execute()

    partial = orch.partial_record("system_error")
    assert partial.outcome.stop_reason == "system_error"
    assert partial.outcome.simulated_turns_completed == 2
    assert partial.target_session_id == "sess-1"
    assert [a.name for a in partial.artifacts] == ["a.txt"]
    assert runner.events[-1] == "teardown"


@pytest.mark.asyncio
async def test_a_trial_level_error_propagates_for_the_retry_loop(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(
        [
            Step(_observation(), downloads={"a.txt": b"x"}),
            Step(raises=TrialRecoverableError("out")),
        ]
    )
    orch = _build(tmp_path, runner, ScriptedAgent([_go()]))

    with pytest.raises(TrialRecoverableError):
        await orch.execute()

    partial = orch.partial_record("system_error")
    assert partial.outcome.simulated_turns_completed == 1
    assert [a.name for a in partial.artifacts] == ["a.txt"]
    assert runner.events[-1] == "teardown"


@pytest.mark.asyncio
async def test_partial_record_before_execute_has_the_fixtures(tmp_path: Path) -> None:
    orch = _build(
        tmp_path, FakeRunner([]), ScriptedAgent([_go()]), fixtures=["q3_sales.csv"]
    )

    partial = orch.partial_record("system_error")

    assert partial.outcome.simulated_turns_completed == 0
    assert [a.name for a in partial.artifacts] == ["q3_sales.csv"]


@pytest.mark.asyncio
async def test_promised_files_are_listed_until_they_arrive(tmp_path: Path) -> None:
    runner = FakeRunner(
        [
            Step(_observation(promised=["report.csv", "report.csv"])),
            Step(_observation(), downloads={"report.csv": b"a\n1\n"}),
            Step(_observation()),
        ]
    )
    agent = ScriptedAgent([_go(), _go(), _go(), _done()])
    orch = _build(tmp_path, runner, agent)

    await orch.execute()

    assert agent.promised == [[], ["report.csv"], [], []]
    assert runner.promised_seen[0] == []
    assert runner.promised_seen[1] == [Promise(name="report.csv", turn=1)]
    assert runner.promised_seen[2] == []


@pytest.mark.asyncio
async def test_an_unfetched_file_is_still_promised(tmp_path: Path) -> None:
    runner = FakeRunner(
        [
            Step(_observation(promised=["report.csv"]), unfetched=["report.csv"]),
            Step(_observation()),
        ]
    )
    agent = ScriptedAgent([_go(), _go(), _done()])
    orch = _build(tmp_path, runner, agent)

    await orch.execute()

    assert agent.promised == [[], ["report.csv"], ["report.csv"]]


@pytest.mark.asyncio
async def test_a_promise_recorded_unavailable_is_no_longer_promised(
    tmp_path: Path,
) -> None:
    runner = FakeRunner([Step(_observation(promised=["report.csv"]))])
    orch = _build(tmp_path, runner, ScriptedAgent([_go(), _done()]))

    await orch.execute()
    assert [p.name for p in orch._still_promised()] == ["report.csv"]
    orch._ledger.record_failure(
        "report.csv", "unavailable", "never delivered", at_simulated_turn=1
    )

    assert orch._still_promised() == []


def _failure(record: TrialRecord) -> tuple[str, str | None, str | None]:
    o = record.outcome
    return o.stop_reason, o.failure_source, o.failure_message


@pytest.mark.asyncio
async def test_an_unsettled_submission_ends_the_loop_and_still_closes(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(
        [Step(_observation(submission_unresolved=True)), Step(_observation())]
    )
    agent = ScriptedAgent([_go(), _go(), _done()])
    orch = _build(tmp_path, runner, agent)

    record = await orch.execute()

    assert _failure(record) == (
        "system_error",
        "evaluation_runner",
        "submission_unresolved",
    )
    assert record.outcome.simulated_turns_completed == 1
    assert agent.turns == [1]  # the user is not asked again
    assert runner.events == ["setup", "act", "end_chat", "teardown"]


@pytest.mark.asyncio
async def test_a_fixture_never_sent_is_a_system_error_even_after_goal_achieved(
    tmp_path: Path,
) -> None:
    runner = FakeRunner([Step(_observation())])
    orch = _build(
        tmp_path, runner, ScriptedAgent([_go(), _done()]), fixtures=["q3_sales.csv"]
    )

    record = await orch.execute()

    assert _failure(record) == (
        "system_error",
        "evaluation_runner",
        "fixture_never_uploaded: q3_sales.csv",
    )


@pytest.mark.asyncio
async def test_a_fixture_sent_in_time_is_no_failure(tmp_path: Path) -> None:
    runner = FakeRunner([Step(_observation(), uploads=["q3_sales.csv"])])
    orch = _build(
        tmp_path, runner, ScriptedAgent([_go(), _done()]), fixtures=["q3_sales.csv"]
    )

    record = await orch.execute()

    assert _failure(record) == ("goal_achieved", None, None)


@pytest.mark.asyncio
async def test_no_fixture_check_on_an_interrupted_or_zero_turn_trial(
    tmp_path: Path,
) -> None:
    event = threading.Event()
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    interrupted = _build(
        tmp_path / "a",
        FakeRunner([Step(_observation(), set_event=event)]),
        ScriptedAgent([_go(), _go()]),
        fixtures=["q3_sales.csv"],
        shutdown_event=event,
    )
    empty = _build(
        tmp_path / "b",
        FakeRunner([]),
        ScriptedAgent([_done("giving_up")]),
        fixtures=["q3_sales.csv"],
    )

    assert _failure(await interrupted.execute()) == ("interrupted", None, None)
    assert _failure(await empty.execute()) == ("user_abandoned", None, None)


def _unsent() -> Observation:
    return Observation(
        reply=None,
        reading=Reading(outcome="not_done", why="no text"),
        notice="Nothing was sent: your action quoted no message.",
        sent_nothing=True,
    )


@pytest.mark.asyncio
async def test_an_action_that_sent_nothing_is_not_a_turn_and_the_user_is_told(
    tmp_path: Path,
) -> None:
    runner = FakeRunner([Step(_unsent()), Step(_observation())])
    agent = ScriptedAgent([_go("Ask about leave"), _go(), _done()])

    record = await _build(tmp_path, runner, agent).execute()

    assert record.outcome.simulated_turns_completed == 1
    assert record.outcome.stop_reason == "goal_achieved"
    assert agent.turns == [1, 1, 2]  # the empty action did not use up turn 1
    assert agent.remembered[0].sent_nothing
    assert "quoted no message" in (agent.remembered[0].notice or "")


@pytest.mark.asyncio
async def test_an_action_that_sent_nothing_does_not_spend_the_turn_budget(
    tmp_path: Path,
) -> None:
    runner = FakeRunner([Step(_unsent()), Step(_unsent()), Step(_observation())])
    agent = ScriptedAgent([_go("a"), _go("b"), _go(), _go()])

    record = await _build(tmp_path, runner, agent, max_turns=1).execute()

    assert record.outcome.stop_reason == "max_turns"
    assert record.outcome.simulated_turns_completed == 1
    assert runner.actions == ["a", "b", "Say ⟦hi⟧"]


@pytest.mark.asyncio
async def test_three_empty_actions_in_a_row_end_the_trial_and_blame_the_user_agent(
    tmp_path: Path,
) -> None:
    runner = FakeRunner([Step(_unsent()), Step(_unsent()), Step(_unsent())])
    agent = ScriptedAgent([_go("a")])

    record = await _build(tmp_path, runner, agent).execute()

    assert _failure(record) == (
        "system_error",
        "user_agent",
        "no_message_quoted",
    )
    assert record.outcome.simulated_turns_completed == 0
    assert agent.turns == [1, 1, 1]  # the user is not asked a fourth time
    assert runner.events == ["setup", "act", "act", "act", "teardown"]


@pytest.mark.asyncio
async def test_a_sent_action_resets_the_run_of_empty_actions(tmp_path: Path) -> None:
    runner = FakeRunner(
        [
            Step(_unsent()),
            Step(_unsent()),
            Step(_observation()),
            Step(_unsent()),
            Step(_unsent()),
            Step(_observation()),
        ]
    )
    agent = ScriptedAgent([_go()] * 6 + [_done()])

    record = await _build(tmp_path, runner, agent).execute()

    assert record.outcome.stop_reason == "goal_achieved"
    assert record.outcome.simulated_turns_completed == 2


@pytest.mark.asyncio
async def test_the_turn_line_holds_the_whole_action_and_reply(tmp_path: Path) -> None:
    action = "Ask ⟦" + "a long question. " * 20 + "⟧"
    reply = "a long answer. " * 20
    runner = FakeRunner([Step(_observation(reply))])
    agent = ScriptedAgent([_go(action), _done()])

    with structlog.testing.capture_logs() as logs:
        await _build(tmp_path, runner, agent).execute()

    (line,) = [e for e in logs if e["event"] == "orchestrator_turn_result"]
    assert line["turn"] == 1
    assert line["action"] == action
    assert line["reply"] == reply
    assert line["outcome"] == "sent"
    assert line["sent_nothing"] is False
    assert line["notice"] is None


@pytest.mark.asyncio
async def test_the_turn_line_shows_an_action_that_sent_nothing(tmp_path: Path) -> None:
    runner = FakeRunner([Step(_unsent()), Step(_observation())])
    agent = ScriptedAgent([_go("Ask about leave"), _go(), _done()])

    with structlog.testing.capture_logs() as logs:
        await _build(tmp_path, runner, agent).execute()

    first = [e for e in logs if e["event"] == "orchestrator_turn_result"][0]
    assert first["sent_nothing"] is True
    assert first["reply"] is None
    assert "quoted no message" in first["notice"]
