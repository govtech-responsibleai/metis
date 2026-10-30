"""The generic HTTP runner's closing step, end_chat (#483)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import pytest

from metis.core.trials import TrialConfig
from metis.engine.simulation.artifacts import ArtifactLedger
from metis.engine.simulation.binding import load_target_binding
from metis.engine.simulation.runners.http import HttpRunner, HttpRunnerFactory
from metis.engine.simulation.types import Promise
from tests.unit.engine.test_agent_loop import ScriptedLLM

if TYPE_CHECKING:
    from pathlib import Path

SPEC_URL = "https://app.example/openapi.json"
_BINDING = f"schema_version: 1\nidentity: {{name: App}}\ntransport: http\nspec_url: {SPEC_URL}\n"
PDF = b"%PDF-1.7\n"
Call = tuple[str, dict[str, Any]]


class Target:
    """A fake app whose chat reply names no file, but whose session lists one."""

    def __init__(self) -> None:
        self.chats = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/openapi.json":
            return httpx.Response(200, json={"servers": [{"url": "/api/v1"}]})
        if path == "/api/v1/chat":
            self.chats += 1
            return httpx.Response(201, json={"sessionId": "s-1", "reply": "hi"})
        if path == "/api/v1/sessions/s-1/files":
            return httpx.Response(
                200, json={"files": [{"id": "9", "name": "late.pdf"}]}
            )
        if path == "/api/v1/files/9/content":
            return httpx.Response(200, content=PDF)
        return httpx.Response(404)


class Trial:
    """A runner that has played turn 1, a chat that opened session ``s-1``."""

    runner: HttpRunner
    target: Target
    llm: ScriptedLLM

    def newest(self) -> str:
        return self.runner.results[-1]

    def list_session_files(self) -> list[Call]:
        return [("http_request", {"method": "GET", "path": "/sessions/s-1/files"})]

    def fetch_listed(self) -> list[Call]:
        listing = {"entry": self.newest(), "at": "$.files"}
        return [
            (
                "fetch_files",
                {
                    "listing": listing,
                    "id_key": "id",
                    "name_key": "name",
                    "download_path": "/files/{id}/content",
                },
            )
        ]


async def _after_one_turn(tmp_path: Path, collect: bool) -> Trial:
    """Play turn 1, then script the closing step: list and fetch, or just report."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "app.yaml").write_text(_BINDING, encoding="utf-8")
    trial = Trial()
    trial.target = Target()
    done: list[Call] = [("report", {"outcome": "done", "why": "x"})]
    closing = (
        [trial.list_session_files, trial.fetch_listed, lambda: done]
        if collect
        else [lambda: done]
    )
    chat: Call = (
        "http_request",
        {"method": "POST", "path": "/chat", "json": {"text": "{{1}}"}},
    )
    trial.llm = ScriptedLLM(
        [chat],
        lambda: [("session_id_from", {"entry": trial.newest(), "at": "$.sessionId"})],
        done,
        *closing,
    )
    factory = HttpRunnerFactory(
        load_target_binding(inputs, "app.yaml"),
        transport=httpx.MockTransport(trial.target),
        llm=trial.llm,  # type: ignore[arg-type]
    )
    await factory.start()
    trial.runner = await factory.create(tmp_path / "trial", tmp_path, tmp_path)
    trial.runner.use_ledger(ArtifactLedger(tmp_path, tmp_path / "trial"))
    await trial.runner.setup(TrialConfig(persona="p", scenario="s"))
    await trial.runner.act("Say ⟦hi⟧", [])
    trial.llm.requests.clear()
    return trial


def _target_files(runner: HttpRunner) -> list[tuple[str, str, int | None]]:
    return [
        (a.name, a.state, a.at_simulated_turn)
        for a in runner.ledger.artifacts()
        if a.source == "target"
    ]


@pytest.mark.asyncio
async def test_the_closing_step_collects_a_late_file_under_the_last_turn(
    tmp_path: Path,
) -> None:
    trial = await _after_one_turn(tmp_path, collect=True)

    await trial.runner.end_chat([])

    assert _target_files(trial.runner) == [("late.pdf", "received", 1)]
    assert trial.target.chats == 1  # nothing was sent to the chat
    assert trial.runner._turn == 1  # not a turn


@pytest.mark.asyncio
async def test_the_closing_step_tells_the_agent_to_send_no_message(
    tmp_path: Path,
) -> None:
    trial = await _after_one_turn(tmp_path, collect=True)

    await trial.runner.end_chat([])

    first = trial.llm.first_message().lower()
    assert "closing" in first and "send no message" in first
    assert "## the user's action" not in first


@pytest.mark.asyncio
async def test_a_promise_the_closing_step_cannot_meet_is_recorded_unavailable(
    tmp_path: Path,
) -> None:
    trial = await _after_one_turn(tmp_path, collect=False)

    await trial.runner.end_chat([Promise(name="chart.vl.json", turn=1)])

    [entry] = [a for a in trial.runner.ledger.artifacts() if a.name == "chart.vl.json"]
    assert (entry.state, entry.at_simulated_turn) == ("unavailable", 1)
    assert entry.state_description == "promised in turn 1, never delivered"


@pytest.mark.asyncio
async def test_a_promise_the_closing_step_meets_is_not_recorded_unavailable(
    tmp_path: Path,
) -> None:
    trial = await _after_one_turn(tmp_path, collect=True)

    await trial.runner.end_chat([Promise(name="late.pdf", turn=1)])

    assert _target_files(trial.runner) == [("late.pdf", "received", 1)]
