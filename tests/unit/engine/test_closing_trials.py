"""Whole trials around the closing step and the checks, on a fake target.

Each trial runs the real orchestrator and ``HttpRunner`` over ``httpx.MockTransport``
with scripted LLM replies, and reads its record back with ``TrialRecord.load_file``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from metis.core.trials import TrialConfig, TrialRecord
from metis.engine.simulation._fixture_artifacts import build_fixture_artifacts
from metis.engine.simulation.binding import load_target_binding
from metis.engine.simulation.orchestrator import Orchestrator
from metis.engine.simulation.runners.http import HttpRunner, HttpRunnerFactory
from metis.engine.simulation.types import Scenario
from tests.unit.engine.test_agent_loop import ScriptedLLM
from tests.unit.engine.test_simulation_orchestrator import ScriptedAgent, _done, _go

if TYPE_CHECKING:
    from pathlib import Path

SPEC_URL = "https://app.example/openapi.json"
_BINDING = f"schema_version: 1\nidentity: {{name: App}}\ntransport: http\nspec_url: {SPEC_URL}\n"
API = "/api/v1"
PDF = b"%PDF-1.7\n"
Call = tuple[str, dict[str, Any]]


class Target:
    """A fake app: a chat, a status, a session file list and file downloads."""

    def __init__(self) -> None:
        self.reply = "hi"
        self.status = httpx.Response(200, json={"state": "done"})
        self.listing: list[dict[str, str]] = []
        self.blobs: dict[str, bytes] = {}
        self.chats = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix(API)
        if request.url.path == "/openapi.json":
            return httpx.Response(200, json={"servers": [{"url": API}]})
        if path == "/chat":
            self.chats += 1
            return httpx.Response(201, json={"sessionId": "s-1", "reply": self.reply})
        if path == "/status":
            return self.status
        if path == "/sessions/s-1/files":
            return httpx.Response(200, json={"files": self.listing})
        if path.startswith("/files/") and path.endswith("/content"):
            blob = self.blobs.get(path.split("/")[2])
            return httpx.Response(200, content=blob) if blob else httpx.Response(404)
        return httpx.Response(404)


class Trial:
    """One trial built and ready to run; scripts read its runner lazily."""

    orchestrator: Orchestrator
    runner: HttpRunner
    llm: ScriptedLLM
    target: Target

    def chat_then_session(self) -> list[Call | Any]:
        send: Call = (
            "http_request",
            {"method": "POST", "path": "/chat", "json": {"text": "{{1}}"}},
        )
        return [
            [send],
            lambda: [("session_id_from", {"entry": self.first(), "at": "$.sessionId"})],
        ]

    def first(self) -> str:
        return self.runner.results[0]

    def report(self, **extra: Any) -> Any:
        def build() -> list[Call]:
            reply = {"entry": self.first(), "at": "$.reply"}
            return [
                (
                    "report",
                    {
                        "outcome": "done",
                        "why": "x",
                        "submission": "answered",
                        "reply_from": reply,
                        **extra,
                    },
                )
            ]

        return build

    def list_and_fetch(self) -> list[Any]:
        listing = [("http_request", {"method": "GET", "path": "/sessions/s-1/files"})]
        fetch = (
            "fetch_files",
            {
                "id_key": "id",
                "name_key": "name",
                "download_path": "/files/{id}/content",
            },
        )
        return [
            listing,
            lambda: [
                (
                    "fetch_files",
                    {
                        **fetch[1],
                        "listing": {"entry": self.runner.results[-1], "at": "$.files"},
                    },
                )
            ],
        ]


NOTHING: list[Call] = [("report", {"outcome": "done", "why": "nothing more"})]


async def _trial(
    tmp_path: Path, agent: ScriptedAgent, fixtures: list[str] | None = None
) -> Trial:
    names = fixtures or []
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "app.yaml").write_text(_BINDING, encoding="utf-8")
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    (fixtures_dir / "q3_sales.csv").write_text("region,amount\nN,1\n", encoding="utf-8")
    trial = Trial()
    trial.target = Target()
    trial.llm = ScriptedLLM([])
    factory = HttpRunnerFactory(
        load_target_binding(inputs, "app.yaml"),
        transport=httpx.MockTransport(trial.target),
        llm=trial.llm,  # type: ignore[arg-type]
    )
    await factory.start()
    run_dir = tmp_path / "outputs" / "trials" / "t1"
    run_dir.mkdir(parents=True)
    runner = await factory.create(run_dir, fixtures_dir, tmp_path)
    assert isinstance(runner, HttpRunner)
    trial.runner = runner
    trial.orchestrator = Orchestrator(
        runner=runner,
        agent=agent,  # type: ignore[arg-type]
        trial_config=TrialConfig(persona="p1", scenario="s1", fixtures=names),
        scenario=Scenario(
            id="s1", description="goal", persona_refs=["p1"], fixtures=names
        ),
        run_dir=run_dir,
        experiment_root=tmp_path,
        fixture_artifacts=build_fixture_artifacts(names, fixtures_dir, tmp_path),
    )
    return trial


async def _record(trial: Trial, tmp_path: Path) -> TrialRecord:
    record = await trial.orchestrator.execute()
    path = tmp_path / "record.json"
    path.write_text(json.dumps(record.model_dump(mode="json")), encoding="utf-8")
    return TrialRecord.load_file(path)


def _files(record: TrialRecord) -> list[tuple[str, str, int | None]]:
    return [(a.name, a.state, a.at_simulated_turn) for a in record.artifacts]


@pytest.mark.asyncio
async def test_the_closing_step_finds_a_file_the_reply_never_named(
    tmp_path: Path,
) -> None:
    agent = ScriptedAgent([_go("Say ⟦hi⟧"), _done()])
    trial = await _trial(tmp_path, agent)
    trial.target.listing = [{"id": "9", "name": "chart.pdf"}]
    trial.target.blobs = {"9": PDF}
    trial.llm._replies[:] = [
        *trial.chat_then_session(),
        trial.report(),
        *trial.list_and_fetch(),
        NOTHING,
    ]

    record = await _record(trial, tmp_path)

    assert record.outcome.stop_reason == "goal_achieved"
    assert record.outcome.simulated_turns_completed == 1
    assert (record.outcome.failure_source, record.outcome.failure_message) == (
        None,
        None,
    )
    assert _files(record) == [("chart.pdf", "received", 1)]
    assert trial.target.chats == 1  # the closing step sent no message


@pytest.mark.asyncio
async def test_a_promise_that_never_arrives_is_unavailable_and_no_longer_promised(
    tmp_path: Path,
) -> None:
    agent = ScriptedAgent([_go("Say ⟦hi⟧"), _done()])
    trial = await _trial(tmp_path, agent)
    trial.target.reply = "Your chart.pdf is coming"
    promise = lambda: {  # noqa: E731
        "promised": [
            {"entry": trial.first(), "at": "$.reply", "pattern": r"(chart\.pdf)"}
        ]
    }
    trial.llm._replies[:] = [
        *trial.chat_then_session(),
        lambda: trial.report(**promise())(),
        NOTHING,
    ]

    record = await _record(trial, tmp_path)

    assert agent.promised == [[], ["chart.pdf"]]  # still promised before the close
    assert _files(record) == [("chart.pdf", "unavailable", 1)]
    assert (
        record.artifacts[0].state_description == "promised in turn 1, never delivered"
    )
    assert trial.orchestrator._still_promised() == []


@pytest.mark.asyncio
async def test_an_unfetched_file_stays_promised_through_the_next_decision(
    tmp_path: Path,
) -> None:
    agent = ScriptedAgent([_go("Say ⟦hi⟧"), _done()])
    trial = await _trial(tmp_path, agent)
    trial.target.reply = "Your report.pdf is ready"
    trial.target.listing = [{"id": "5", "name": "report.pdf"}]  # no blob: a 404
    promise = lambda: {  # noqa: E731
        "promised": [
            {"entry": trial.first(), "at": "$.reply", "pattern": r"(report\.pdf)"}
        ]
    }
    trial.llm._replies[:] = [
        *trial.chat_then_session(),
        *trial.list_and_fetch(),
        lambda: trial.report(**promise())(),
        NOTHING,
    ]

    record = await _record(trial, tmp_path)

    assert agent.promised == [[], ["report.pdf"]]
    assert ("report.pdf", "unfetched", 1) in _files(record)


@pytest.mark.asyncio
async def test_a_fixture_never_uploaded_fails_even_a_goal_achieved_trial(
    tmp_path: Path,
) -> None:
    agent = ScriptedAgent([_go("Say ⟦hi⟧"), _done("goal_achieved")])
    trial = await _trial(tmp_path, agent, ["q3_sales.csv"])
    trial.llm._replies[:] = [*trial.chat_then_session(), trial.report(), NOTHING]

    record = await _record(trial, tmp_path)

    outcome = record.outcome
    assert outcome.stop_reason == "system_error"
    assert outcome.failure_source == "evaluation_runner"
    assert outcome.failure_message == "fixture_never_uploaded: q3_sales.csv"
    assert _files(record) == [("q3_sales.csv", "received", None)]


@pytest.mark.asyncio
async def test_a_reply_that_never_settles_ends_the_loop_and_still_closes(
    tmp_path: Path,
) -> None:
    agent = ScriptedAgent([_go("Say ⟦hi⟧"), _go("Say ⟦more⟧"), _done()])
    trial = await _trial(tmp_path, agent)
    trial.target.status = httpx.Response(404, json={"error": "gone"})
    wait = ("poll_until", {"path": "/status", "at": "$.state", "not_in": ["working"]})
    trial.llm._replies[:] = [
        *trial.chat_then_session(),
        [wait],
        [("report", {"outcome": "not_done", "why": "never settled"})],
        NOTHING,
    ]

    record = await _record(trial, tmp_path)

    outcome = record.outcome
    assert outcome.stop_reason == "system_error"
    assert outcome.failure_source == "evaluation_runner"
    assert outcome.failure_message == "submission_unresolved"
    assert outcome.simulated_turns_completed == 1
    assert agent.turns == [1]  # no second turn was started
    assert trial.target.chats == 1
    closing = [r for r in trial.llm.requests if "closing step" in str(r["messages"][1])]
    assert closing  # the closing step still ran
