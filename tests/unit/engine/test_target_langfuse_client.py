"""Each evaluation reads the target's Langfuse on connections that its own event loop owns.

Each run calls ``asyncio.run``, so it has its own loop, and the API runs many runs in one
process. A pooled connection belongs to the loop that opened it. If a later run reused one, its
first request would fail with "Event loop is closed", and its first trial would not be graded
(issue #190). So a run makes its own client, and closes it before its loop closes.

Every ``httpx.AsyncClient`` made in a test gets a fake transport that acts like a pooled
connection: its first request binds it to the running loop, and a request or a close after that
loop has closed fails as a real socket does. Nothing touches the network.
"""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from langfuse._client.resource_manager import LangfuseResourceManager

from metis.engine import tracing
from metis.engine.evaluation.trial_files import load_trial_evaluations
from metis.engine.extractor import TraceWaitSettings
from metis.engine.run import RunStopped, evaluate
from tests.unit.engine.test_cli_evaluate import _write_experiment_dir, _write_records
from tests.unit.engine.test_run_evaluate import _console, _in_a_thread

if TYPE_CHECKING:
    from pathlib import Path

_WAIT = TraceWaitSettings(timeout_seconds=90)
_TARGET = {
    "LANGFUSE_PUBLIC_KEY": "pk-target",
    "LANGFUSE_SECRET_KEY": "sk-target",
    "LANGFUSE_BASE_URL": "https://target.example",
    "LANGFUSE_TRACING_ENABLED": "false",
}
_TRIALS = ["run-01", "run-02"]


def _row(session_id: str) -> dict[str, Any]:
    """One observation of the session, long settled, as Observations API v2 returns it."""
    return {
        "id": f"{session_id}-o1",
        "traceId": f"{session_id}-t1",
        "sessionId": session_id,
        "name": "chat-turn",
        "type": "AGENT",
        "input": "a question",
        "output": "an answer",
        "startTime": "2026-01-01T00:00:00Z",
        "endTime": "2026-01-01T00:00:01Z",
        "updatedAt": "2026-01-01T00:00:02Z",
    }


class _PooledConnection(httpx.AsyncBaseTransport):
    """Answers every observations request with the one settled row of its session.

    Like a kept-alive connection, it is bound to the loop of its first request. A request after
    that loop has closed fails with "Event loop is closed" and drops the connection, so the
    request after it opens a new one, as httpx does. A close after that loop has closed fails
    the same way. With ``started``, it sets the event and waits until it is cancelled.
    """

    def __init__(self, started: threading.Event | None) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._started = started

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self._loop is not None and self._loop.is_closed():
            self._loop = None
            raise RuntimeError("Event loop is closed")
        self._loop = asyncio.get_running_loop()
        if self._started is not None:
            self._started.set()
            await asyncio.sleep(30)
        (condition,) = json.loads(request.url.params["filter"])
        session_id = condition["value"].removesuffix("-t1")
        return httpx.Response(
            200, json={"data": [_row(session_id)], "meta": {"cursor": None}}
        )

    async def aclose(self) -> None:
        if self._loop is not None:
            # Raises "Event loop is closed" when the loop of the connection has closed.
            self._loop.call_soon(lambda: None)


@dataclass
class _Clients:
    """Every async HTTP client made in the test. Set ``started`` to make requests wait."""

    made: list[httpx.AsyncClient] = field(default_factory=list)
    started: threading.Event | None = None


@pytest.fixture
def clients(monkeypatch: pytest.MonkeyPatch) -> _Clients:
    """The target's Langfuse is configured, and no client of it is registered yet.

    The METIS-internal client is registered first, as the caller of a run does, so the
    clients listed are the ones the run makes.
    """
    tracing.tracing_key()
    for name, value in _TARGET.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        LangfuseResourceManager,
        "_instances",
        {
            key: instance
            for key, instance in LangfuseResourceManager._instances.items()
            if key != _TARGET["LANGFUSE_PUBLIC_KEY"]
        },
    )
    clients = _Clients()

    class _AsyncClient(httpx.AsyncClient):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(
                *args, **kwargs, transport=_PooledConnection(clients.started)
            )
            clients.made.append(self)

    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClient)
    return clients


def _evaluate(experiment_dir: Path) -> Any:
    return evaluate(
        experiment_dir,
        trace_wait=_WAIT,
        concurrency=1,
        stop=threading.Event(),
        console=_console()[0],
    )


def _failure_reasons(experiment_dir: Path) -> list[str | None]:
    saved = load_trial_evaluations(experiment_dir, _TRIALS)
    return [saved[trial].failure_reason for trial in _TRIALS]


@pytest.mark.usefixtures("clients")
def test_a_second_evaluation_in_the_process_grades_its_first_trial(
    tmp_path: Path,
) -> None:
    experiment_dir = _write_experiment_dir(tmp_path)
    _write_records(experiment_dir, len(_TRIALS))

    _evaluate(experiment_dir)
    assert _failure_reasons(experiment_dir) == [None, None]
    _evaluate(experiment_dir)

    assert _failure_reasons(experiment_dir) == [None, None]


def test_an_evaluation_closes_the_client_it_made(
    clients: _Clients, tmp_path: Path
) -> None:
    experiment_dir = _write_experiment_dir(tmp_path)
    _write_records(experiment_dir, len(_TRIALS))

    _evaluate(experiment_dir)

    assert [client.is_closed for client in clients.made] == [True]


def test_a_stopped_evaluation_closes_the_client_it_made(
    clients: _Clients, tmp_path: Path
) -> None:
    experiment_dir = _write_experiment_dir(tmp_path)
    _write_records(experiment_dir, 1)
    clients.started = threading.Event()
    stop = threading.Event()

    thread, outcome = _in_a_thread(
        evaluate,
        experiment_dir,
        trace_wait=_WAIT,
        concurrency=1,
        stop=stop,
        console=_console()[0],
    )
    assert clients.started.wait(timeout=5)
    stop.set()
    thread.join(timeout=10)

    assert isinstance(outcome[0], RunStopped)
    assert [client.is_closed for client in clients.made] == [True]


def test_a_failed_evaluation_closes_the_client_it_made(
    clients: _Clients, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    experiment_dir = _write_experiment_dir(tmp_path)
    _write_records(experiment_dir, 1)

    def disk_full(*_args: object) -> None:
        raise OSError("No space left on device")

    monkeypatch.setattr(
        "metis.engine.evaluation.trial_files.save_trial_evaluation", disk_full
    )
    with pytest.raises(OSError, match="No space left on device"):
        _evaluate(experiment_dir)

    assert [client.is_closed for client in clients.made] == [True]
