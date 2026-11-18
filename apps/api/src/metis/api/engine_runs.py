"""The engine runs that are alive or queued now, and the library calls that they make.

The API runs up to ``max_runs`` jobs at a time, each on its own thread, in its own process.
A start that finds every slot taken waits in a first-in-first-out queue, and starts when a
slot frees. The limit and the queue are for the whole server, so they cover the jobs of every
user account. A job is the steps that one start asks for, such as a simulate and then its
evaluate, and one thread runs all its steps in order. Each simulation sends its logs to its
own files (``metis.engine.logging.router``), and each evaluation has its own Langfuse client,
so runs on two threads do not share a log file or a connection.

The run in memory holds only what a thread needs: its project folder, its experiment id and
folder, its steps, its stop flag, and the last ``seq`` of ``logs/events.jsonl`` when it was
accepted. Two user accounts can have an experiment folder with the same name, so a run is the
run of a request only when both its project folder and its experiment id are the same. The
experiment folders on disk are the source of truth for everything else. A restart loses the
queue.

The text of a run goes to ``logs/console.log`` of its experiment, never to the stdout of the
API. Its progress goes to ``logs/events.jsonl``, which the engine writes.
"""

from __future__ import annotations

import functools
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol

from rich.console import Console

from metis.api.errors import RouteError
from metis.core import execution_layout
from metis.core.logging import get_logger
from metis.core.phase_events import EVENTS_FILE, PhaseEvent
from metis.engine import run as engine_run

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from metis.core.phase_events import Phase
    from metis.engine.extractor import TraceWaitSettings

logger = get_logger(__name__)

CONSOLE_FILE = "console.log"
"""The file in ``logs/`` that gets the text of a run. No engine log uses this name."""


@functools.cache
def setup_engine_process() -> None:
    """Set up the process for the engine library functions, one time.

    It loads ``.env``, registers the METIS-internal Langfuse client, and sets up process
    logging. ``METIS_LOG_LEVEL`` sets the log level, WARNING by default. The level also
    decides what reaches the per-trial log files of a simulation.
    """
    from metis.core.logging import configure_logging
    from metis.core.model_settings import load_env
    from metis.engine.tracing import tracing_key

    load_env()
    tracing_key()
    configure_logging()


class PrepareExperiment(Protocol):
    """``metis.engine.run.prepare_experiment``."""

    def __call__(
        self, input_dir: Path, /, *, project_dir: Path, console: Console
    ) -> Path: ...


class Simulate(Protocol):
    """``metis.engine.run.simulate`` and ``resume_simulation``, as the routes call them."""

    def __call__(
        self,
        experiment_dir: Path,
        /,
        *,
        concurrency: int,
        stop: threading.Event,
        console: Console,
    ) -> object: ...


class Evaluate(Protocol):
    """``metis.engine.run.evaluate`` and ``resume_evaluation``, as the routes call them."""

    def __call__(
        self,
        experiment_dir: Path,
        /,
        *,
        trace_wait: TraceWaitSettings,
        concurrency: int,
        stop: threading.Event,
        console: Console,
        command: Literal["evaluate", "run"] = ...,
    ) -> object: ...


@dataclass(frozen=True)
class EngineFunctions:
    """The library calls of the engine routes. The tests give fakes for some of them.

    Each field has the type of the engine function, so the type checker checks each call
    of a route against the signature in ``metis.engine.run``.
    """

    prepare_experiment: PrepareExperiment = engine_run.prepare_experiment
    simulate: Simulate = engine_run.simulate
    resume_simulation: Simulate = engine_run.resume_simulation
    evaluate: Evaluate = engine_run.evaluate
    resume_evaluation: Evaluate = engine_run.resume_evaluation
    setup_process: Callable[[], None] = field(
        default_factory=lambda: setup_engine_process
    )


@dataclass(frozen=True)
class Step:
    """One engine call of a job: its phase, and the call on the experiment folder."""

    phase: Phase
    work: Callable[[Path, threading.Event, Console], object]


@dataclass
class Run:
    """A job that is alive or queued now."""

    project_dir: Path
    experiment_id: str
    experiment_dir: Path
    steps: tuple[Step, ...]
    start_seq: int
    """The last ``seq`` of the events log when the start was accepted."""
    stop: threading.Event = field(default_factory=threading.Event)

    @property
    def key(self) -> tuple[Path, str]:
        """The project folder and the experiment id, which name the run of a request."""
        return (self.project_dir, self.experiment_id)


@dataclass(frozen=True)
class LiveRun:
    """A run of a request, and its place in the queue."""

    run: Run
    queue_ahead: int | None
    """The jobs before it in the queue, across all user accounts. ``None`` when it runs."""


class EngineRuns:
    """Starts, queues, stops, and reports the engine jobs of the process.

    One lock covers the check for a live or queued run, the checks of a start, the queue,
    and the start of each thread. A refused start therefore changes nothing, and two starts
    of the same experiment cannot both pass.
    """

    def __init__(self, functions: EngineFunctions, max_runs: int = 1) -> None:
        self.functions = functions
        self.max_runs = max_runs
        """The jobs that run at the same time. The lifespan sets it from the settings."""
        self._lock = threading.Lock()
        self._running: dict[tuple[Path, str], tuple[Run, threading.Thread]] = {}
        self._queue: deque[Run] = deque()
        self._closed = False

    def start(
        self,
        *,
        project_dir: Path,
        experiment_id: str | None,
        prepare: Callable[[], Path],
        steps: Sequence[Step],
    ) -> str:
        """Check that the experiment has no live or queued run, prepare it, and accept it.

        ``project_dir`` is the project folder of the request. ``experiment_id`` is the folder
        of a resume or an evaluate, and ``None`` for a new simulation. ``prepare`` makes the
        checks of the start and returns the experiment folder. It runs under the lock, so an
        error from it leaves no run. The job starts on a thread at once when a slot is free,
        else it waits at the end of the queue.

        :raises RouteError: 409 ``run_in_progress`` when the run of ``experiment_id`` is
            alive or queued, or an error of ``prepare``.
        """
        with self._lock:
            if experiment_id is not None and self._find(project_dir, experiment_id):
                raise RouteError(
                    409,
                    "run_in_progress",
                    f"The experiment {experiment_id!r} runs now, or waits to run.",
                )
            experiment_dir = prepare()
            run = Run(
                project_dir=project_dir,
                experiment_id=experiment_dir.name,
                experiment_dir=experiment_dir,
                steps=tuple(steps),
                start_seq=last_seq(experiment_dir),
            )
            self._queue.append(run)
            self._start_next()
            return run.experiment_id

    def stop(self, project_dir: Path, experiment_id: str) -> None:
        """Stop the run of ``experiment_id`` in ``project_dir``.

        A running job gets its stop flag, and runs no further step. A queued job leaves the
        queue at once.

        :raises RouteError: 409 ``no_run`` when that experiment does not run or wait.
        """
        with self._lock:
            found = self._find(project_dir, experiment_id)
            if found is None:
                raise RouteError(
                    409, "no_run", f"The experiment {experiment_id!r} does not run."
                )
            found.run.stop.set()
            if found.queue_ahead is not None:
                self._queue.remove(found.run)

    def current(self, project_dir: Path, experiment_id: str) -> LiveRun | None:
        """The run of ``experiment_id`` in ``project_dir`` when it runs or waits, else ``None``."""
        with self._lock:
            return self._find(project_dir, experiment_id)

    def shutdown(self, timeout: float) -> None:
        """Empty the queue, stop every run, and wait for the threads.

        The wait is at most ``timeout`` seconds in all. A thread that is still alive then is
        logged. No queued job starts after this.
        """
        with self._lock:
            self._closed = True
            self._queue.clear()
            running = list(self._running.values())
            for run, _ in running:
                run.stop.set()
        deadline = time.monotonic() + timeout
        for run, thread in running:
            thread.join(max(0.0, deadline - time.monotonic()))
            if thread.is_alive():
                logger.warning(
                    "engine_run_did_not_stop",
                    experiment_id=run.experiment_id,
                    timeout_seconds=timeout,
                )

    def _find(self, project_dir: Path, experiment_id: str) -> LiveRun | None:
        """The live or queued run of the experiment. The caller holds the lock."""
        key = (project_dir, experiment_id)
        if key in self._running:
            return LiveRun(run=self._running[key][0], queue_ahead=None)
        for ahead, run in enumerate(self._queue):
            if run.key == key:
                return LiveRun(run=run, queue_ahead=ahead)
        return None

    def _start_next(self) -> None:
        """Start queued jobs while a slot is free. The caller holds the lock."""
        while not self._closed and self._queue and len(self._running) < self.max_runs:
            run = self._queue.popleft()
            thread = threading.Thread(
                target=self._run_thread,
                args=(run,),
                name=f"metis-engine-{run.experiment_id}",
                daemon=True,
            )
            self._running[run.key] = (run, thread)
            thread.start()

    def _run_thread(self, run: Run) -> None:
        """Run the steps of the job with the console file of the experiment, then free its slot.

        A step runs only when the stop flag is clear. The engine ends the events log with
        ``interrupted`` or ``failed`` before it raises, so a ``RunStopped`` or a ``RunError``
        ends the job and needs nothing more. Any other error is logged and ends the job.
        """
        step = run.steps[0] if run.steps else None
        try:
            logs = run.experiment_dir / execution_layout.LOGS
            logs.mkdir(parents=True, exist_ok=True)
            with (logs / CONSOLE_FILE).open("a", encoding="utf-8") as handle:
                console = Console(file=handle, color_system=None, width=120)
                for step in run.steps:
                    if run.stop.is_set():
                        break
                    step.work(run.experiment_dir, run.stop, console)
        except (engine_run.RunStopped, engine_run.RunError):
            pass
        except Exception:
            logger.exception(
                "engine_run_failed",
                experiment_id=run.experiment_id,
                phase=step.phase if step else None,
            )
        finally:
            with self._lock:
                self._running.pop(run.key, None)
                self._start_next()


def read_events(experiment_dir: Path) -> list[tuple[PhaseEvent, str]]:
    """The events of ``logs/events.jsonl``, in file order, each with its line.

    A last line with no newline is skipped, because the engine can still be writing it. A
    line that ``PhaseEvent.parse_line`` refuses is skipped, as ``PhaseEventLog`` does,
    because a crash can leave a cut line in the middle of the file. No file gives ``[]``.
    """
    path = experiment_dir / execution_layout.LOGS / EVENTS_FILE
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return []
    events: list[tuple[PhaseEvent, str]] = []
    for line in text.split("\n")[:-1]:
        try:
            events.append((PhaseEvent.parse_line(line), line))
        except ValueError:
            continue
    return events


def last_seq(experiment_dir: Path) -> int:
    """The highest ``seq`` in the events log of ``experiment_dir``, 0 when it has none."""
    return max((event.seq for event, _ in read_events(experiment_dir)), default=0)


__all__ = [
    "CONSOLE_FILE",
    "EngineFunctions",
    "EngineRuns",
    "LiveRun",
    "Run",
    "Step",
    "last_seq",
    "read_events",
    "setup_engine_process",
]
