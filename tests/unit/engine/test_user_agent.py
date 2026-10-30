"""The user agent: one plain-language action per turn, facts apart from readings."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import httpx
import openai
import pytest
import structlog.testing

from metis.core import Artifact
from metis.engine.simulation import llm_calls
from metis.engine.simulation.artifacts import file_facts
from metis.engine.simulation.exceptions import UserAgentUnavailableError
from metis.engine.simulation.llm_calls import LLMCallLog
from metis.engine.simulation.types import (
    Observation,
    Persona,
    Promise,
    Reading,
    Scenario,
    UserAgentOutput,
)
from metis.engine.simulation.user_agent.agent import HISTORY_TURNS, UserAgent

if TYPE_CHECKING:
    from pathlib import Path


class FakeClient:
    """Stands in for ``AsyncOpenAI``: returns canned outputs and keeps every request."""

    def __init__(self, *outputs: UserAgentOutput, refusal: str | None = None) -> None:
        self._outputs = list(outputs)
        self._refusal = refusal
        self.requests: list[list[dict[str, Any]]] = []
        self.beta = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(parse=self._parse))
        )

    async def _parse(self, *, messages: list[dict[str, Any]], **_kw: Any) -> Any:
        self.requests.append(messages)
        message = SimpleNamespace(
            parsed=None if self._refusal else self._outputs.pop(0),
            refusal=self._refusal,
            content=None,
        )
        return SimpleNamespace(
            model="m",
            usage=None,
            choices=[SimpleNamespace(message=message, finish_reason="stop")],
        )


class FailingClient(FakeClient):
    """A client whose every request raises ``error``."""

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error

    async def _parse(self, *, messages: list[dict[str, Any]], **_kw: Any) -> Any:
        raise self._error


_REQUEST = httpx.Request("POST", "https://llm.example/v1/chat/completions")


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_calls, "_retry_delay", lambda _: 0.0)


def _out(action: str = "Say ⟦hi⟧", decision: str = "continue") -> UserAgentOutput:
    return UserAgentOutput(reasoning="because", action=action, decision=decision)  # type: ignore[arg-type]


def _agent(tmp_path: Path, client: FakeClient) -> UserAgent:
    return UserAgent(
        persona=Persona(
            id="p1", name="p1", description="A careful accountant named Dana."
        ),
        scenario=Scenario(
            id="s1", description="Get a Q3 summary report.", persona_refs=["p1"]
        ),
        llm_log=LLMCallLog.for_trial(tmp_path),
        client=client,  # type: ignore[arg-type]
    )


def _text(messages: list[dict[str, Any]]) -> str:
    return "\n".join(m["content"] for m in messages)


@pytest.mark.asyncio
async def test_the_prompt_has_the_persona_and_scenario_and_no_target_knowledge(
    tmp_path: Path,
) -> None:
    client = FakeClient(_out())
    await _agent(tmp_path, client).decide(1, [], [])

    system = client.requests[0][0]
    assert system["role"] == "system"
    assert "A careful accountant named Dana." in system["content"]
    assert "Get a Q3 summary report." in system["content"]
    assert "⟦" in system["content"]
    for advice in ("Haiku", "Sonnet", "AI Model", "Slide Maker", "dropdown"):
        assert advice not in _text(client.requests[0])


@pytest.mark.asyncio
async def test_the_prompt_says_an_error_status_need_not_be_the_assistants_fault(
    tmp_path: Path,
) -> None:
    client = FakeClient(_out())
    await _agent(tmp_path, client).decide(1, [], [])

    system = client.requests[0][0]["content"]
    assert "error status" in system
    assert "need not" in system


@pytest.mark.asyncio
async def test_the_prompt_lists_persona_and_scenario_metadata_as_written(
    tmp_path: Path,
) -> None:
    client = FakeClient(_out())
    agent = UserAgent(
        persona=Persona(
            id="p1",
            name="p1",
            description="A careful accountant named Dana.",
            metadata={"age": "In their fifties.", "input_style": "Terse."},
        ),
        scenario=Scenario(
            id="s1",
            description="Get a Q3 summary report.",
            metadata={"stop_condition": "Dana has the report."},
            persona_refs=["p1"],
        ),
        llm_log=LLMCallLog.for_trial(tmp_path),
        client=client,  # type: ignore[arg-type]
    )
    await agent.decide(1, [], [])

    system = client.requests[0][0]["content"]
    assert "- age: In their fifties.\n- input_style: Terse." in system
    assert "- stop_condition: Dana has the report." in system


@pytest.mark.asyncio
async def test_the_prompt_has_no_metadata_section_when_there_is_none(
    tmp_path: Path,
) -> None:
    client = FakeClient(_out())
    await _agent(tmp_path, client).decide(1, [], [])

    system = client.requests[0][0]["content"]
    assert "More about" not in system


@pytest.mark.asyncio
async def test_a_held_file_is_its_facts_line_and_never_its_content(
    tmp_path: Path,
) -> None:
    csv = tmp_path / "q3_sales.csv"
    csv.write_text("region,amount\nNORTH-SECRET-ROW,1\nSOUTH,2\n")
    held = Artifact(
        name="q3_sales.csv",
        source="fixture",
        state="received",
        path="q3_sales.csv",
        content_description=file_facts(csv, "q3_sales.csv"),
    )
    client = FakeClient(_out())

    await _agent(tmp_path, client).decide(1, [held], [])

    prompt = _text(client.requests[0])
    assert "q3_sales.csv (text/csv," in prompt
    assert "2 data rows, 2 columns; header: region,amount" in prompt
    assert "NORTH-SECRET-ROW" not in prompt


@pytest.mark.asyncio
async def test_files_the_user_sent_and_received_are_told_apart(tmp_path: Path) -> None:
    sent = Artifact(
        name="in.csv",
        source="fixture",
        state="received",
        path="in.csv",
        content_description="in.csv (x)",
    )
    got = Artifact(
        name="out.csv",
        source="target",
        state="received",
        path="out.csv",
        content_description="out.csv (y)",
    )
    client = FakeClient(_out())

    await _agent(tmp_path, client).decide(2, [sent, got], [])

    prompt = client.requests[0][-1]["content"]
    assert prompt.index("in.csv (x)") < prompt.index("out.csv (y)")
    assert "from the assistant" in prompt.split("out.csv (y)")[0].split("in.csv (x)")[1]


@pytest.mark.asyncio
async def test_promised_files_are_listed_with_the_turn_they_were_promised(
    tmp_path: Path,
) -> None:
    client = FakeClient(_out())

    await _agent(tmp_path, client).decide(3, [], [Promise(name="report.pdf", turn=2)])

    last = client.requests[0][-1]["content"]
    assert "report.pdf" in last
    assert "turn 2" in last


@pytest.mark.asyncio
async def test_with_nothing_promised_the_prompt_says_so(tmp_path: Path) -> None:
    client = FakeClient(_out())

    await _agent(tmp_path, client).decide(1, [], [])

    assert "promised" in client.requests[0][-1]["content"].lower()
    assert "none" in client.requests[0][-1]["content"].lower()


@pytest.mark.asyncio
async def test_the_reply_is_copied_and_the_reading_is_labelled_an_interpretation(
    tmp_path: Path,
) -> None:
    client = FakeClient(_out(), _out())
    agent = _agent(tmp_path, client)
    first = await agent.decide(1, [], [])
    reply = 'Sure! Here is "the report" — 42 rows.\n\nAnything else?'
    agent.remember(
        first,
        Observation(
            reply=reply,
            reading=Reading(
                outcome="sent", why="it answered", next_options="ask a follow-up"
            ),
        ),
    )

    await agent.decide(2, [], [])

    history = client.requests[1]
    assert history[1] == {
        "role": "assistant",
        "content": json.dumps(
            {"action": first.action, "decision": "continue"}, ensure_ascii=False
        ),
    }
    seen = history[2]["content"]
    assert reply in seen
    facts, reading = seen.split("interpretation", 1)
    assert reply in facts
    assert "it answered" in reading
    assert "ask a follow-up" in reading
    assert "it answered" not in facts


@pytest.mark.asyncio
async def test_a_turn_without_a_reply_says_so_and_carries_the_notice(
    tmp_path: Path,
) -> None:
    client = FakeClient(_out(), _out())
    agent = _agent(tmp_path, client)
    first = await agent.decide(1, [], [])
    agent.remember(
        first,
        Observation(
            reply=None,
            reading=Reading(outcome="not_completed", why="no reply"),
            observed=False,
            notice="Response timeout — no response received",
        ),
    )

    await agent.decide(2, [], [])

    seen = client.requests[1][2]["content"]
    assert "no reply was shown" in seen.lower()
    assert "Response timeout — no response received" in seen


@pytest.mark.asyncio
async def test_only_the_last_turns_of_history_are_sent(tmp_path: Path) -> None:
    turns = HISTORY_TURNS + 5
    client = FakeClient(*[_out(f"Say ⟦{i}⟧") for i in range(turns + 1)])
    agent = _agent(tmp_path, client)
    for i in range(turns):
        out = await agent.decide(i + 1, [], [])
        agent.remember(
            out, Observation(reply=f"r{i}", reading=Reading(outcome="sent", why="w"))
        )

    await agent.decide(turns + 1, [], [])

    roles = [m["role"] for m in client.requests[-1]]
    assert roles.count("assistant") == HISTORY_TURNS
    assert "Say ⟦0⟧" not in _text(client.requests[-1])
    assert f"Say ⟦{turns - 1}⟧" in _text(client.requests[-1])


@pytest.mark.asyncio
async def test_each_call_is_logged_to_the_trial_llm_log(tmp_path: Path) -> None:
    await _agent(tmp_path, FakeClient(_out())).decide(1, [], [])

    rows = LLMCallLog.for_trial(tmp_path).path.read_text().splitlines()
    assert [json.loads(r)["component"] for r in rows] == ["user_agent"]


@pytest.mark.asyncio
async def test_a_refusal_raises(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="refused"):
        await _agent(tmp_path, FakeClient(refusal="no")).decide(1, [], [])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        openai.APIConnectionError(request=_REQUEST),
        openai.APITimeoutError(request=_REQUEST),
        openai.InternalServerError(
            "bad gateway", response=httpx.Response(502, request=_REQUEST), body=None
        ),
        openai.RateLimitError(
            "slow down", response=httpx.Response(429, request=_REQUEST), body=None
        ),
    ],
    ids=["connection", "timeout", "5xx", "429"],
)
async def test_a_transient_failure_that_outlasts_the_retries_is_unavailable(
    tmp_path: Path, error: Exception
) -> None:
    with pytest.raises(UserAgentUnavailableError) as raised:
        await _agent(tmp_path, FailingClient(error)).decide(1, [], [])

    assert raised.value.__cause__ is error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        openai.AuthenticationError(
            "bad key", response=httpx.Response(401, request=_REQUEST), body=None
        ),
        openai.BadRequestError(
            "bad schema", response=httpx.Response(400, request=_REQUEST), body=None
        ),
    ],
    ids=["401", "400"],
)
async def test_a_permanent_failure_is_not_unavailable(
    tmp_path: Path, error: Exception
) -> None:
    with pytest.raises(RuntimeError, match="LLM call failed") as raised:
        await _agent(tmp_path, FailingClient(error)).decide(1, [], [])

    assert not isinstance(raised.value, UserAgentUnavailableError)


def test_a_continue_decision_needs_an_action() -> None:
    with pytest.raises(ValueError, match="action"):
        UserAgentOutput(reasoning="", action="  ", decision="continue")


@pytest.mark.asyncio
async def test_the_decision_line_holds_the_whole_action(tmp_path: Path) -> None:
    action = "Ask ⟦" + "a long question. " * 30 + "⟧"
    agent = _agent(tmp_path, FakeClient(_out(action)))

    with structlog.testing.capture_logs() as logs:
        await agent.decide(1, [], [])

    (line,) = [e for e in logs if e["event"] == "user_agent_decided"]
    assert line["turn"] == 1
    assert line["decision"] == "continue"
    assert line["action"] == action
    assert line["reasoning"] == "because"


def test_the_action_field_the_model_fills_says_the_message_goes_inside_the_quotes() -> (
    None
):
    schema = UserAgentOutput.model_json_schema()

    description = schema["properties"]["action"]["description"]

    assert "⟦" in description and "⟧" in description
    assert "whole message" in description
    assert "nothing is sent" in description


def test_every_field_the_model_fills_has_a_description() -> None:
    properties = UserAgentOutput.model_json_schema()["properties"]

    assert set(properties) == {"reasoning", "action", "decision"}
    assert all(p.get("description") for p in properties.values())
    assert "not shown to the assistant" in properties["reasoning"]["description"]
    assert "goal_achieved" in properties["decision"]["description"]
    assert "giving_up" in properties["decision"]["description"]
