"""Fakes and folders for the engine route tests.

`FakeEngine` stands in for the engine library functions. Each fake writes the phase lines that
the real function writes to ``logs/events.jsonl``, prints to the console that it gets, and
records its call, so no test runs a trial, calls a model, or reaches the network. The checks
before a run starts (``prepare_experiment``, ``resolve_experiment_dir``, the trace wait, and
``evaluation_is_complete``) are the real library functions on real folders.

`FakeEngine.mode` chooses what the next run does:

- ``complete``: ``started``, then ``completed``.
- ``hold``: ``started``, then it waits. A stop gives ``interrupted`` and ``RunStopped``.
  ``release`` gives ``completed``.
- ``slow_stop``: as ``hold``, but it takes half a second to end after a stop, so a test
  can tell a caller that waits for the run from one that does not.
- ``stubborn``: ``started``, then it waits for ``release`` only, and ignores the stop flag.
- ``fail``: ``started``, then ``failed`` and a ``RunError``.
- ``crash``: ``started``, then ``failed`` and a ``ValueError``, as the engine does for an
  error that it does not expect.

``begin`` holds a run before it writes its ``started`` line, while it is clear.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from metis.api.engine_runs import EngineFunctions
from metis.api.main import create_app
from metis.core import execution_layout, project_layout
from metis.core.phase_events import INTERRUPTED_REASON, PhaseEventLog
from metis.engine.run import RunError, RunStopped
from tests.fixtures.api._shared import scripted_interview_handler
from tests.unit.engine.test_cli_simulate import MINIMAL_EXPERIMENT

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from rich.console import Console

    from metis.api.store import Store
    from metis.core.phase_events import Phase

SPECIFICATION_ID = "test-exp"
"""The id of ``MINIMAL_EXPERIMENT``, the Specification of the input folders."""


@dataclass
class Call:
    name: str
    experiment_dir: Path
    options: dict[str, Any]


@dataclass
class FakeEngine:
    mode: str = "complete"
    calls: list[Call] = field(default_factory=list)
    setups: int = 0
    begin: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)

    def __post_init__(self) -> None:
        self.begin.set()

    def functions(self, **overrides: Any) -> EngineFunctions:
        functions: dict[str, Any] = {
            "simulate": self._fake("simulate", "simulating"),
            "resume_simulation": self._fake("resume_simulation", "simulating"),
            "evaluate": self._fake("evaluate", "evaluating"),
            "resume_evaluation": self._fake("resume_evaluation", "evaluating"),
            "setup_process": self._set_up,
        }
        return EngineFunctions(**{**functions, **overrides})

    def _set_up(self) -> None:
        self.setups += 1

    def _fake(self, name: str, phase: Phase) -> Callable[..., None]:
        def run(
            experiment_dir: Path,
            *,
            stop: threading.Event,
            console: Console,
            **options: Any,
        ) -> None:
            self.calls.append(Call(name, experiment_dir, options))
            mode = self.mode
            self.begin.wait()
            events = PhaseEventLog.for_experiment_dir(experiment_dir)
            console.print(f"fake {name} of {experiment_dir.name}")
            events.emit(phase, "started", total=2, done=0)
            if mode in ("hold", "slow_stop"):
                while not (stop.wait(0.01) or self.release.is_set()):
                    pass
                if stop.is_set():
                    if mode == "slow_stop":
                        time.sleep(0.5)
                    events.emit(phase, "interrupted", reason=INTERRUPTED_REASON)
                    raise RunStopped("stopped")
            elif mode == "stubborn":
                self.release.wait()
            elif mode == "fail":
                events.emit(phase, "failed", reason="boom")
                raise RunError("boom")
            elif mode == "crash":
                events.emit(phase, "failed", reason="ValueError: boom")
                raise ValueError("boom")
            events.emit(phase, "completed")

        return run


def wait_until(check: Callable[[], bool], timeout: float = 5.0) -> None:
    """Wait until ``check()`` is true, and fail the test after ``timeout`` seconds."""
    deadline = time.monotonic() + timeout
    while not check():
        if time.monotonic() > deadline:
            raise AssertionError("the condition did not become true in time")
        time.sleep(0.01)


def write_input_dir(folder: Path, specification: str = MINIMAL_EXPERIMENT) -> Path:
    """Write an input folder of ``simulate --input-dir`` that the engine accepts."""
    folder.mkdir(parents=True)
    (folder / "specification.yaml").write_text(specification)
    return folder


@pytest.fixture
def fake_engine() -> Iterator[FakeEngine]:
    engine = FakeEngine()
    yield engine
    engine.begin.set()
    engine.release.set()


@pytest.fixture
def input_dir(project_dir: Path) -> Path:
    """An input folder under the project folder, as the wizard writes it."""
    return write_input_dir(project_dir / "evaluations" / "specifications" / "t1")


@pytest.fixture
def make_experiment_dir(project_dir: Path) -> Callable[[str], Path]:
    """Make an experiment folder as ``prepare_experiment`` makes it, with a fixed name."""

    def make(name: str = f"{SPECIFICATION_ID}-20260101-000000") -> Path:
        folder = project_dir / project_layout.EXPERIMENTS / name
        write_input_dir(folder / execution_layout.SPECIFICATION_DIR)
        return folder

    return make


@pytest.fixture
def make_engine_client(
    store: Store, fake_engine: FakeEngine
) -> Iterator[Callable[..., TestClient]]:
    """Start an app over the fake engine. Each client runs its lifespan, and stops at exit."""
    clients: list[TestClient] = []

    def make(**overrides: Any) -> TestClient:
        app = create_app(
            interview_handler=scripted_interview_handler(),
            store=store,
            engine_functions=fake_engine.functions(**overrides),
        )
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield make
    # A held run ends at once, so the shutdown of each app does not wait for it.
    fake_engine.begin.set()
    fake_engine.release.set()
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def engine_client(make_engine_client: Callable[..., TestClient]) -> TestClient:
    return make_engine_client()
