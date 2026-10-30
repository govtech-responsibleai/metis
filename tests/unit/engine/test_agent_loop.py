"""The runner agent's loop, prompt and Observation (#481)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import httpx
import openai
import pytest
import structlog.testing

from metis.core.trials import TrialConfig
from metis.engine.simulation.artifacts import ArtifactLedger
from metis.engine.simulation.binding import load_target_binding
from metis.engine.simulation.exceptions import TurnRecoverableError
from metis.engine.simulation.runners import http as http_module
from metis.engine.simulation.runners.http import (
    MAX_ROUNDS,
    HttpRunner,
    HttpRunnerFactory,
)
from metis.engine.simulation.runners.prompts import SYSTEM_PROMPT
from metis.engine.simulation.types import Promise

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

SPEC_URL = "https://app.example/openapi.json"
_BINDING = (
    f"schema_version: 1\nidentity: {{name: App, version: '2'}}\ntransport: http\n"
    f"spec_url: {SPEC_URL}\nforbidden_calls: ['DELETE /**']\n"
    "advice: {notes: 'Chat replies are JSON.'}\n"
)
API = "/api/v1"
Reply = list[tuple[str, dict[str, Any]]]


class Target:
    """A fake app: a chat, a status that follows a script, and a broken path."""

    def __init__(self) -> None:
        self.status: list[httpx.Response] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/openapi.json":
            return httpx.Response(
                200, json={"servers": [{"url": API}], "info": {"title": "Fake App"}}
            )
        if path == f"{API}/chat":
            return httpx.Response(201, json={"sessionId": "s-1", "reply": "hi"})
        if path == f"{API}/status":
            return self.status.pop(0) if len(self.status) > 1 else self.status[0]
        if path == f"{API}/boom":
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json={})


class Clock:
    """A clock that only moves when told to or when the runner sleeps."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


class ScriptedLLM:
    """Stands in for ``AsyncOpenAI``: each reply is a list of tool calls, a callable
    that makes one when asked, or an exception to raise. The last reply repeats."""

    def __init__(self, *replies: Reply | Callable[[], Reply] | Exception) -> None:
        self._replies = list(replies)
        self.requests: list[dict[str, Any]] = []
        self.on_call: Callable[[], None] | None = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, *, model: str, messages: list[Any], **options: Any) -> Any:
        self.requests.append(
            {"model": model, "messages": json.loads(json.dumps(messages)), **options}
        )
        if self.on_call:
            self.on_call()
        reply = self._replies.pop(0) if len(self._replies) > 1 else self._replies[0]
        if isinstance(reply, Exception):
            raise reply
        calls = reply() if callable(reply) else reply
        message = SimpleNamespace(
            content=None,
            tool_calls=[
                SimpleNamespace(
                    id=f"c{len(self.requests)}-{i}",
                    type="function",
                    function=SimpleNamespace(name=name, arguments=json.dumps(args)),
                )
                for i, (name, args) in enumerate(calls)
            ]
            or None,
        )
        return SimpleNamespace(
            model="m", usage=None, choices=[SimpleNamespace(message=message)]
        )

    def first_message(self, n: int = 0) -> str:
        return self.requests[n]["messages"][1]["content"]


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(http_module, "_now", fake)
    monkeypatch.setattr(http_module, "_sleep", fake.sleep)
    return fake


async def _ready(
    tmp_path: Path, llm: ScriptedLLM, *, wait_ms: int = 10000
) -> tuple[HttpRunner, Target]:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "app.yaml").write_text(_BINDING, encoding="utf-8")
    target = Target()
    target.status = [httpx.Response(200, json={"state": "done"})]
    factory = HttpRunnerFactory(
        load_target_binding(inputs, "app.yaml"),
        transport=httpx.MockTransport(target),
        llm=llm,  # type: ignore[arg-type]
    )
    await factory.start()
    trial = tmp_path / "trial"
    runner = await factory.create(trial, tmp_path, tmp_path)
    runner.use_ledger(ArtifactLedger(tmp_path, trial))
    await runner.setup(TrialConfig(persona="p", scenario="s", response_wait_ms=wait_ms))
    return runner, target


def _chat() -> tuple[str, dict[str, Any]]:
    return (
        "http_request",
        {"method": "POST", "path": "/chat", "json": {"text": "{{1}}"}},
    )


def _report(runner: HttpRunner, which: int = -1, **extra: Any) -> Callable[[], Reply]:
    """A report citing the newest logged result as the reply."""

    def build() -> Reply:
        args = {
            "outcome": "done",
            "why": "sent it",
            "submission": "answered",
            "reply_from": {"entry": runner.results[which], "at": "$.reply"},
            **extra,
        }
        return [("report", args)]

    return build


@pytest.mark.asyncio
async def test_a_request_then_a_report_gives_an_observation_built_from_the_log(
    tmp_path: Path,
) -> None:
    llm = ScriptedLLM(
        [_chat()],
        [("poll_until", {"path": "/status", "at": "$.state", "in": ["done"]})],
    )
    runner, _ = await _ready(tmp_path, llm)
    llm._replies.append(_report(runner, 0, next_options="ask more"))

    observation = await runner.act("Say ⟦hello⟧", [])

    assert observation.reply == "hi"
    assert observation.reading.model_dump() == {
        "outcome": "done",
        "why": "sent it",
        "next_options": "ask more",
    }
    assert (observation.observed, observation.notice) == (True, None)
    assert {r["tool_choice"] for r in llm.requests} == {"required"}
    rows = (tmp_path / "trial/evidence/llm_calls.jsonl").read_text().splitlines()
    assert [json.loads(r)["component"] for r in rows] == ["runner_agent"] * 3


@pytest.mark.asyncio
async def test_the_first_message_shows_what_the_agent_needs(tmp_path: Path) -> None:
    llm = ScriptedLLM([("report", {"outcome": "unknown", "why": "x"})])
    runner, _ = await _ready(tmp_path, llm)

    await runner.act("Ask ⟦what is 2 + 2?⟧", [Promise(name="slides.pptx", turn=1)])

    message = llm.first_message()
    assert "Ask {{1}}" in message and "⟦" not in message
    assert '{{1}} = "what is 2 + 2?"' in message
    assert "Fake App" in message  # the specification, from the log
    assert "App" in message and "Chat replies are JSON." in message
    assert "DELETE /**" in message
    assert "slides.pptx" in message
    assert "none open" in message


@pytest.mark.asyncio
async def test_a_note_is_shown_again_in_the_next_action(tmp_path: Path) -> None:
    llm = ScriptedLLM(
        [
            ("note", {"text": "replies come as JSON"}),
            ("report", {"outcome": "done", "why": "x"}),
        ]
    )
    runner, _ = await _ready(tmp_path, llm)
    await runner.act("Say ⟦a⟧", [])

    await runner.act("Say ⟦b⟧", [])

    assert "replies come as JSON" not in llm.first_message(0)
    assert "replies come as JSON" in llm.first_message(1)


@pytest.mark.asyncio
async def test_a_round_without_a_tool_call_is_nudged_once(tmp_path: Path) -> None:
    llm = ScriptedLLM([], [("report", {"outcome": "done", "why": "x"})])
    runner, _ = await _ready(tmp_path, llm)

    observation = await runner.act("Say ⟦a⟧", [])

    nudge = llm.requests[1]["messages"][-1]
    assert nudge["role"] == "user" and "report" in nudge["content"]
    assert observation.reading.outcome == "done"


@pytest.mark.asyncio
async def test_the_round_cap_ends_a_looping_agent(tmp_path: Path) -> None:
    llm = ScriptedLLM([("note", {"text": "again"})])
    runner, _ = await _ready(tmp_path, llm)

    observation = await runner.act("Say ⟦a⟧", [])

    assert len(llm.requests) == MAX_ROUNDS
    assert observation.reply is None
    assert observation.reading.outcome == "unknown"
    assert observation.notice is not None and str(MAX_ROUNDS) in observation.notice


@pytest.mark.asyncio
async def test_the_time_limit_ends_the_action(tmp_path: Path, clock: Clock) -> None:
    llm = ScriptedLLM([("note", {"text": "slow"})])
    llm.on_call = lambda: setattr(clock, "now", clock.now + 100)
    runner, _ = await _ready(tmp_path, llm, wait_ms=10000)

    observation = await runner.act("Say ⟦a⟧", [])

    assert len(llm.requests) == 1
    assert observation.notice is not None and "time limit" in observation.notice


@pytest.mark.asyncio
async def test_a_reply_cited_from_an_earlier_action_is_refused_and_can_be_fixed(
    tmp_path: Path,
) -> None:
    llm = ScriptedLLM([_chat()])
    runner, _ = await _ready(tmp_path, llm)
    llm._replies.append(_report(runner))
    await runner.act("Say ⟦a⟧", [])
    old = runner.results[-1]
    llm._replies[:] = [
        [
            (
                "report",
                {
                    "outcome": "done",
                    "why": "x",
                    "submission": "pending",
                    "reply_from": {"entry": old},
                },
            )
        ],
        [("http_request", {"method": "GET", "path": "/status"})],
        lambda: [
            (
                "report",
                {
                    "outcome": "done",
                    "why": "x",
                    "submission": "pending",
                    "reply_from": {"entry": runner.results[-1], "at": "$.state"},
                },
            )
        ],
    ]

    observation = await runner.act("Say ⟦b⟧", [])

    refusal = llm.requests[3]["messages"][-1]["content"]  # after the first action's two
    assert "not one of the entries you may cite" in refusal
    assert observation.reply == "done"


@pytest.mark.asyncio
async def test_promised_files_are_copied_by_code_from_the_reply(tmp_path: Path) -> None:
    llm = ScriptedLLM([_chat()])
    runner, _ = await _ready(tmp_path, llm)
    llm._replies.append(
        lambda: [
            (
                "report",
                {
                    "outcome": "partial",
                    "why": "x",
                    "submission": "answered",
                    "promised": [
                        {
                            "entry": runner.results[-1],
                            "at": "$.reply",
                            "pattern": "(h)i",
                        }
                    ],
                },
            )
        ]
    )

    observation = await runner.act("Say ⟦a⟧", [])

    assert observation.promised == ["h"]


@pytest.mark.asyncio
async def test_an_open_submission_is_resumed_first_and_an_unsettled_one_is_not_observed(
    tmp_path: Path, clock: Clock
) -> None:
    llm = ScriptedLLM(
        [_chat()],
        [("poll_until", {"path": "/status", "at": "$.state", "not_in": ["working"]})],
        [("report", {"outcome": "partial", "why": "still working"})],
    )
    runner, target = await _ready(tmp_path, llm)
    target.status = [httpx.Response(200, json={"state": "working"})]

    first = await runner.act("Say ⟦a⟧", [])

    assert runner.open_submission is not None
    assert first.observed is False

    target.status = [httpx.Response(200, json={"state": "done"})]
    llm._replies[:] = [[("report", {"outcome": "done", "why": "x"})]]
    second = await runner.act("Say ⟦b⟧", [])

    assert "none open" in llm.first_message(len(llm.requests) - 1)
    assert runner.open_submission is None
    assert second.observed is True


@pytest.mark.asyncio
async def test_unresolved_is_a_notice_once_then_cleared(
    tmp_path: Path, clock: Clock
) -> None:
    llm = ScriptedLLM(
        [_chat()],
        [("poll_until", {"path": "/status", "at": "$.state", "not_in": ["working"]})],
        [("report", {"outcome": "not_done", "why": "x"})],
    )
    runner, target = await _ready(tmp_path, llm)
    target.status = [httpx.Response(404, json={"error": "gone"})]

    first = await runner.act("Say ⟦a⟧", [])
    llm._replies[:] = [[("report", {"outcome": "done", "why": "x"})]]
    second = await runner.act("Say ⟦b⟧", [])

    assert first.notice is not None and "never settled" in first.notice
    assert first.submission_unresolved is True
    assert runner.unresolved is None
    assert second.notice is None
    assert second.submission_unresolved is False


@pytest.mark.asyncio
async def test_a_transport_failure_means_not_observed(tmp_path: Path) -> None:
    llm = ScriptedLLM(
        [("http_request", {"method": "GET", "path": "/boom"})],
        [("report", {"outcome": "not_done", "why": "no connection"})],
    )
    runner, _ = await _ready(tmp_path, llm)

    observation = await runner.act("Say ⟦a⟧", [])

    assert observation.observed is False
    assert observation.notice is not None and "transport" in observation.notice


@pytest.mark.asyncio
async def test_an_llm_failure_is_a_recoverable_turn_error(tmp_path: Path) -> None:
    denied = openai.AuthenticationError(
        "bad key",
        response=httpx.Response(401, request=httpx.Request("POST", "https://x")),
        body=None,
    )
    runner, _ = await _ready(tmp_path, ScriptedLLM(denied))

    with pytest.raises(TurnRecoverableError, match="runner agent"):
        await runner.act("Say ⟦a⟧", [])


def test_the_prompt_keeps_the_rules_and_drops_the_prototypes_browser_parts() -> None:
    for kept in ("{{1}}", "fetch_files", "report", "session_id_from", "note"):
        assert kept in SYSTEM_PROMPT
    for dropped in ("artifact_ledger_append", "form_from", "snapshot", "browser"):
        assert dropped not in SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_an_action_that_quoted_no_message_sends_nothing_and_keeps_its_turn_number(
    tmp_path: Path,
) -> None:
    llm = ScriptedLLM(
        [_chat()],
        [("report", {"outcome": "not_done", "why": "no text to send"})],
        [_chat()],
        [("report", {"outcome": "not_done", "why": "no text to send"})],
    )
    runner, target = await _ready(tmp_path, llm)

    first = await runner.act("Ask about the leave policy", [])
    second = await runner.act("Say ⟦hello⟧", [])

    assert first.sent_nothing
    assert "quoted no message" in (first.notice or "")
    assert first.reply is None
    assert not second.sent_nothing
    assert runner._turn == 1  # only the action that was sent is a turn


@pytest.mark.asyncio
async def test_the_runner_agents_rounds_and_tool_calls_say_which_turn_they_belong_to(
    tmp_path: Path,
) -> None:
    llm = ScriptedLLM([_chat()], [("report", {"outcome": "unknown", "why": "x"})])
    runner, _ = await _ready(tmp_path, llm)

    with structlog.testing.capture_logs() as logs:
        await runner.act("Say ⟦hello⟧", [])
        await runner.act("Say ⟦again⟧", [])

    mine = [
        e
        for e in logs
        if e["event"] in ("runner_agent_round", "runner_agent_tool_call")
    ]
    assert {e["turn"] for e in mine} == {1, 2}


@pytest.mark.asyncio
async def test_the_closing_call_is_labelled_closing_not_as_the_last_turn(
    tmp_path: Path,
) -> None:
    llm = ScriptedLLM([("report", {"outcome": "done", "why": "x"})])
    runner, _ = await _ready(tmp_path, llm)
    await runner.act("Say ⟦hello⟧", [])

    with structlog.testing.capture_logs() as logs:
        await runner.end_chat([])

    mine = [e for e in logs if e["event"].startswith("runner_agent_")]
    assert mine
    assert {e["turn"] for e in mine} == {"closing"}
