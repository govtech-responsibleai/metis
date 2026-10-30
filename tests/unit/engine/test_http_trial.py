"""A whole trial through the generic HTTP runner, against a fake target.

The target is a small app served by ``httpx.MockTransport``; both LLMs are scripted. The
orchestrator, the ledger, the transport log and the record are the real ones.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import openai
import pytest

from metis.core.trials import TrialConfig, TrialRecord
from metis.engine.simulation._fixture_artifacts import build_fixture_artifacts
from metis.engine.simulation.binding import load_target_binding
from metis.engine.simulation.orchestrator import Orchestrator
from metis.engine.simulation.runners.http import (
    MAX_ROUNDS,
    HttpRunner,
    HttpRunnerFactory,
)
from metis.engine.simulation.types import Scenario, UserAgentOutput
from tests.unit.engine.test_agent_loop import ScriptedLLM
from tests.unit.engine.test_simulation_orchestrator import ScriptedAgent

if TYPE_CHECKING:
    from pathlib import Path

SPEC_URL = "https://app.example/openapi.json"
_BINDING = f"schema_version: 1\nidentity: {{name: App}}\ntransport: http\nspec_url: {SPEC_URL}\n"
API = "/api/v1"
REPORT_CSV = b"region,amount\nN,1\nS,2\n"
SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Fake App"},
    "servers": [{"url": API}],
    "paths": {
        "/files": {"post": {"summary": "upload a file"}},
        "/chat": {"post": {"summary": "send a message"}},
        "/status": {"get": {"summary": "is the reply ready"}},
        "/files/{id}": {"get": {"summary": "download a file"}},
    },
}


class Target:
    """A fake app that answers a chat with a reply, a session and one file to fetch."""

    def __init__(self) -> None:
        self.seen: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        path = request.url.path
        if path == "/openapi.json":
            return httpx.Response(200, json=SPEC)
        if path == f"{API}/files" and request.method == "POST":
            return httpx.Response(200, json={"fileId": "up-1"})
        if path == f"{API}/chat":
            return httpx.Response(
                201,
                json={
                    "sessionId": "s-1",
                    "reply": "Here is your report",
                    "files": [{"id": "f-9", "name": "report.csv"}],
                },
            )
        if path == f"{API}/status":
            return httpx.Response(200, json={"state": "done"})
        if path == f"{API}/files/f-9":
            return httpx.Response(
                200, content=REPORT_CSV, headers={"content-type": "text/csv"}
            )
        return httpx.Response(404)

    def bodies(self, path: str) -> list[bytes]:
        return [r.content for r in self.seen if r.url.path == f"{API}{path}"]


def _go(action: str) -> UserAgentOutput:
    return UserAgentOutput(reasoning="r", action=action, decision="continue")


def _done() -> UserAgentOutput:
    return UserAgentOutput(reasoning="r", action="", decision="goal_achieved")


async def _trial(
    tmp_path: Path,
    llm: ScriptedLLM,
    agent: ScriptedAgent,
    names: list[str] | None = None,
) -> tuple[Orchestrator, HttpRunner, Target, Path]:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "app.yaml").write_text(_BINDING, encoding="utf-8")
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "q3_sales.csv").write_text("region,amount\nN,1\n", encoding="utf-8")
    names = ["q3_sales.csv"] if names is None else names
    target = Target()
    factory = HttpRunnerFactory(
        load_target_binding(inputs, "app.yaml"),
        transport=httpx.MockTransport(target),
        llm=llm,  # type: ignore[arg-type]
    )
    await factory.start()
    run_dir = tmp_path / "outputs" / "trials" / "t1"
    run_dir.mkdir(parents=True)
    runner = await factory.create(run_dir, fixtures, tmp_path)
    orchestrator = Orchestrator(
        runner=runner,
        agent=agent,  # type: ignore[arg-type]
        trial_config=TrialConfig(persona="p1", scenario="s1", fixtures=names),
        scenario=Scenario(
            id="s1",
            description="goal",
            persona_refs=["p1"],
            fixtures=names,
        ),
        run_dir=run_dir,
        experiment_root=tmp_path,
        fixture_artifacts=build_fixture_artifacts(names, fixtures, tmp_path),
    )
    return orchestrator, runner, target, run_dir


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.mark.asyncio
async def test_a_full_trial_writes_a_record_from_a_real_session_and_a_real_download(
    tmp_path: Path,
) -> None:
    llm = ScriptedLLM([])
    agent = ScriptedAgent(
        [_go("Upload q3_sales.csv, then say ⟦hi⟧"), _go("Say ⟦thanks⟧"), _done()]
    )
    orchestrator, runner, target, run_dir = await _trial(tmp_path, llm, agent)
    ids = runner.results  # entries of the agent's calls, in order
    llm._replies[:] = [
        [
            (
                "http_request",
                {
                    "method": "POST",
                    "path": "/files",
                    "multipart": {"file": "@q3_sales.csv"},
                    "file_id_from": "$.fileId",
                },
            )
        ],
        [
            (
                "http_request",
                {"method": "POST", "path": "/chat", "json": {"text": "{{1}}"}},
            )
        ],
        lambda: [("session_id_from", {"entry": ids[1], "at": "$.sessionId"})],
        [("poll_until", {"path": "/status", "at": "$.state", "in": ["done"]})],
        lambda: [
            (
                "fetch_files",
                {
                    "listing": {"entry": ids[1], "at": "$.files"},
                    "id_key": "id",
                    "name_key": "name",
                    "download_path": "/files/{id}",
                },
            )
        ],
        lambda: [
            (
                "report",
                {
                    "outcome": "done",
                    "why": "sent and fetched",
                    "reply_from": {"entry": ids[1], "at": "$.reply"},
                },
            )
        ],
        # the second action
        [
            (
                "http_request",
                {"method": "POST", "path": "/chat", "json": {"text": "{{1}}"}},
            )
        ],
        [("poll_until", {"path": "/status", "at": "$.state", "in": ["done"]})],
        lambda: [
            (
                "report",
                {
                    "outcome": "done",
                    "why": "thanked",
                    "reply_from": {"entry": ids[3], "at": "$.reply"},
                },
            )
        ],
        # the closing step: nothing to collect, so it reports at once
        [("report", {"outcome": "done", "why": "nothing more"})],
    ]

    record = await orchestrator.execute()

    path = tmp_path / "record.json"
    path.write_text(json.dumps(record.model_dump(mode="json")), encoding="utf-8")
    loaded = TrialRecord.load_file(path)
    assert loaded.outcome.stop_reason == "goal_achieved"
    assert loaded.outcome.simulated_turns_completed == 2
    assert loaded.target_session_id == "s-1"  # copied from the reply, not written
    assert [
        (a.name, a.source, a.state, a.at_simulated_turn) for a in loaded.artifacts
    ] == [
        ("q3_sales.csv", "fixture", "received", 1),
        ("report.csv", "target", "received", 1),
    ]
    assert loaded.artifacts[0].external_id == "up-1"
    downloaded = loaded.artifacts[1]
    assert downloaded.path is not None
    assert (tmp_path / downloaded.path).read_bytes() == REPORT_CSV
    # the user's words reached the target exactly, in the order they were quoted
    assert [json.loads(b)["text"] for b in target.bodies("/chat")] == ["hi", "thanks"]
    assert [o.reply for o in agent.remembered] == ["Here is your report"] * 2
    assert all(o.observed and o.notice is None for o in agent.remembered)

    transport = _jsonl(run_dir / "evidence" / "log.jsonl")
    summaries = [e["summary"] for e in transport]
    assert summaries.count(f"POST {API}/chat") == 2
    assert f"GET {API}/files/f-9 -> 200" in summaries
    calls = _jsonl(run_dir / "evidence" / "llm_calls.jsonl")
    assert [c["component"] for c in calls] == ["runner_agent"] * 10
    assert runner.open_submission is None


@pytest.mark.asyncio
async def test_the_round_cap_ends_a_looping_agent_and_the_trial_goes_on(
    tmp_path: Path,
) -> None:
    llm = ScriptedLLM([("note", {"text": "thinking"})])
    agent = ScriptedAgent([_go("Say ⟦hi⟧"), _done()])
    orchestrator, _, target, run_dir = await _trial(tmp_path, llm, agent, [])

    record = await orchestrator.execute()

    assert record.outcome.stop_reason == "goal_achieved"
    assert record.outcome.simulated_turns_completed == 1
    [seen] = agent.remembered
    assert seen.reply is None
    assert seen.notice is not None and f"{MAX_ROUNDS} rounds" in seen.notice
    assert target.bodies("/chat") == []  # a looping agent sent nothing
    # the action and the closing step each run to the cap
    assert len(_jsonl(run_dir / "evidence" / "llm_calls.jsonl")) == 2 * MAX_ROUNDS


@pytest.mark.asyncio
async def test_a_failed_runner_agent_call_costs_one_turn_not_the_trial(
    tmp_path: Path,
) -> None:
    denied = openai.AuthenticationError(
        "bad key",
        response=httpx.Response(401, request=httpx.Request("POST", "https://x")),
        body=None,
    )
    llm = ScriptedLLM(denied, [("report", {"outcome": "done", "why": "fine"})])
    agent = ScriptedAgent([_go("Say ⟦a⟧"), _go("Say ⟦b⟧"), _done()])
    orchestrator, _, _, _ = await _trial(tmp_path, llm, agent, [])

    record = await orchestrator.execute()

    assert record.outcome.stop_reason == "goal_achieved"
    assert record.outcome.simulated_turns_completed == 2
    first, second = agent.remembered
    assert first.observed is False and first.reply is None
    assert first.notice is not None and "No reply was captured" in first.notice
    assert second.reading.outcome == "done"
