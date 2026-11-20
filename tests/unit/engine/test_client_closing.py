"""An engine run closes every async model client it made before its event loop closes.

Each run calls ``asyncio.run``, so its clients belong to a loop that closes when the run ends.
The API runs many runs in one process. A client left open is deleted later, and openai's
``AsyncHttpxClientWrapper.__del__`` then closes it as a task on whatever loop is running. Its
connections belong to the closed loop, so that task fails, and asyncio logs "Task exception
was never retrieved" (issue #183).

The fake model's transport stands in for a real connection: closing it calls ``call_soon`` on
the loop of its first request, as the real socket transport does, so it fails once that loop
has closed. Nothing touches the network.
"""

from __future__ import annotations

import asyncio
import gc
import json
import logging
import threading
from typing import TYPE_CHECKING, Any

import httpx
import pytest
import structlog
from langfuse.openai import AsyncOpenAI
from openai._base_client import AsyncHttpxClientWrapper
from rich.console import Console

from metis.engine.extractor import TraceWaitSettings
from metis.engine.run import evaluate, prepare_experiment, simulate
from tests.unit.engine.test_cli_evaluate import NoLangfuse
from tests.unit.engine.test_cli_simulate import MINIMAL_EXPERIMENT

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from metis.core.model_settings import RoleSettings

# The user agent ends the trial on its first call, and the criterion uses the judge, so
# both the simulation and the evaluation make a model client.
SPECIFICATION = MINIMAL_EXPERIMENT.replace("FixedScoreGrader", "EchoJudgeGrader")
_USER_AGENT_REPLY = {"reasoning": "r", "action": "", "decision": "goal_achieved"}


@pytest.fixture(autouse=True)
def _reset_logging():
    yield
    structlog.reset_defaults()
    logging.getLogger().handlers.clear()


class _LoopBoundTransport(httpx.AsyncBaseTransport):
    """Answers every chat call, and is bound to the loop of its first request."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self._loop = asyncio.get_running_loop()
        return httpx.Response(
            200,
            json={
                "id": "c1",
                "object": "chat.completion",
                "created": 0,
                "model": "served-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(_USER_AGENT_REPLY),
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 2,
                    "total_tokens": 5,
                },
            },
        )

    async def aclose(self) -> None:
        if self._loop is not None:
            # Raises "Event loop is closed" when the loop of the connection has closed.
            self._loop.call_soon(lambda: None)


def _fake_model(settings: RoleSettings) -> AsyncOpenAI:
    """``llm_client`` with the fake transport, in the wrapper openai uses by default."""
    return AsyncOpenAI(
        api_key="k",
        base_url="https://model.example/v1",
        max_retries=0,
        http_client=AsyncHttpxClientWrapper(transport=_LoopBoundTransport()),
    )


def _patch_models(
    monkeypatch: pytest.MonkeyPatch, made: Callable[[AsyncOpenAI], None]
) -> None:
    """Every model client the engine makes is a fake one, which ``made`` is given."""

    def llm_client(settings: RoleSettings) -> AsyncOpenAI:
        client = _fake_model(settings)
        made(client)
        return client

    for module in (
        "metis.engine.simulation.user_agent.agent",
        "metis.engine.simulation.runners.http",
        "metis.engine.simulation.runners.browser",
    ):
        monkeypatch.setattr(f"{module}.llm_client", llm_client)

    from metis.engine import evaluation

    build_llm_settings = evaluation.build_llm_settings

    def judge(*args: Any, **kwargs: Any) -> Any:
        settings = build_llm_settings(*args, **kwargs)
        made(settings.client)
        return settings

    monkeypatch.setattr(evaluation, "build_llm_settings", judge)


@pytest.fixture
def fake_services(monkeypatch: pytest.MonkeyPatch) -> None:
    """The stub runner reports a session, and Langfuse returns one trace for it."""
    from tests.unit.engine.test_cli_evaluate import _session

    monkeypatch.setattr(
        "tests.unit.engine.test_runner_ref.StubRunner.session_id",
        property(lambda _self: "session-1"),
    )
    monkeypatch.setattr("metis.engine.extractor.get_langfuse_client", NoLangfuse)

    async def fetch(session_id: str, *_args: object, **_kwargs: object) -> Any:
        return _session(session_id, 1)

    monkeypatch.setattr("metis.engine.extractor.fetch_session", fetch)


def _experiment(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    (source / "specification.yaml").write_text(SPECIFICATION)
    project = tmp_path / "project"
    project.mkdir()
    return prepare_experiment(source, project_dir=project, console=Console(quiet=True))


def _simulate_and_evaluate(experiment_dir: Path) -> None:
    console = Console(quiet=True)
    simulate(experiment_dir, concurrency=1, stop=threading.Event(), console=console)
    evaluate(
        experiment_dir,
        trace_wait=TraceWaitSettings(timeout_seconds=90),
        concurrency=1,
        stop=threading.Event(),
        console=console,
    )


@pytest.mark.usefixtures("fake_services")
def test_simulate_and_evaluate_close_every_model_client_they_make(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clients: list[AsyncOpenAI] = []
    _patch_models(monkeypatch, clients.append)
    experiment_dir = _experiment(tmp_path)

    _simulate_and_evaluate(experiment_dir)

    # One user agent client for the trial's attempt, and the judge client.
    assert len(clients) == 2
    assert [client.is_closed() for client in clients] == [True, True]


@pytest.mark.usefixtures("fake_services")
def test_a_run_beside_a_running_loop_leaves_no_failed_close_task(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """As in the API: the run has its own loop on a thread, and another loop keeps running."""
    _patch_models(monkeypatch, lambda _client: None)  # keeps no reference to a client
    experiment_dir = _experiment(tmp_path)
    errors: list[str] = []

    async def api() -> None:
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(
            lambda _loop, context: errors.append(context["message"])
        )
        await asyncio.to_thread(_simulate_and_evaluate, experiment_dir)
        gc.collect()  # a client left open schedules its close on this loop
        for _ in range(5):
            await asyncio.sleep(0)
        gc.collect()  # and the failed task, once deleted, logs its error

    asyncio.run(api())

    assert "Task exception was never retrieved" not in errors


@pytest.mark.usefixtures("fake_services")
def test_an_evaluation_that_fails_before_grading_leaves_no_judge_client_open(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clients: list[AsyncOpenAI] = []
    _patch_models(monkeypatch, clients.append)
    experiment_dir = _experiment(tmp_path)
    simulate(
        experiment_dir,
        concurrency=1,
        stop=threading.Event(),
        console=Console(quiet=True),
    )
    clients.clear()

    def no_langfuse() -> object:
        raise RuntimeError("Langfuse is not configured")

    monkeypatch.setattr("metis.engine.extractor.get_langfuse_client", no_langfuse)
    with pytest.raises(RuntimeError, match="Langfuse is not configured"):
        evaluate(
            experiment_dir,
            trace_wait=TraceWaitSettings(timeout_seconds=90),
            concurrency=1,
            stop=threading.Event(),
            console=Console(quiet=True),
        )

    # The judge client is made only once nothing can fail before the `finally` that closes it.
    assert [client for client in clients if not client.is_closed()] == []
