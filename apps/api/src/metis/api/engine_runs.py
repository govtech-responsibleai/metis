"""The engine run that is alive now, and the library calls that it makes.

The API runs at most one engine function at a time, on its own thread, in its own process.
Logging and the METIS-internal Langfuse clients are shared by the whole process, so a
second run at the same time is not safe. The limit is for the whole server, so it covers the
runs of every user account. The run in memory holds only what a live thread needs: its
project folder, its experiment id and folder, its phase, its stop flag, and the last ``seq`` of
``logs/events.jsonl`` when it started. Two user accounts can have an experiment folder with the
same name, so a run is the run of a request only when both its project folder and its
experiment id are the same. The experiment folders on disk are the source of truth
for everything else.

The text of a run goes to ``logs/console.log`` of its experiment, never to the stdout of the
API. Its progress goes to ``logs/events.jsonl``, which the engine writes.
"""

from __future__ import annotations

import functools
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from rich.console import Console

from metis.api.errors import RouteError
from metis.core import execution_layout
from metis.core.logging import get_logger
from metis.core.phase_events import EVENTS_FILE, PhaseEvent
from metis.engine import run as engine_run

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
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


@dataclass
class Run:
    """The run that is alive now."""

    project_dir: Path
    experiment_id: str
    experiment_dir: Path
    phase: Phase
    start_seq: int
    """The last ``seq`` of the events log before the run started."""
    stop: threading.Event = field(default_factory=threading.Event)

    def is_of(self, project_dir: Path, experiment_id: str) -> bool:
        """Whether this is the run of ``experiment_id`` in ``project_dir``."""
        return self.project_dir == project_dir and self.experiment_id == experiment_id


class EngineRuns:
    """Starts, stops, and reports the one engine run of the process.

    One lock covers the busy check, the checks of a start, and the start of the thread, so a
    refused start changes nothing and two starts at the same time cannot both pass.
    """

    def __init__(self, functions: EngineFunctions) -> None:
        self.functions = functions
        self._lock = threading.Lock()
        self._run: Run | None = None
        self._thread: threading.Thread | None = None

    def start(
        self,
        *,
        project_dir: Path,
        experiment_id: str | None,
        phase: Phase,
        prepare: Callable[[], Path],
        work: Callable[[Path, threading.Event, Console], object],
    ) -> str:
        """Check that no run is alive, prepare the folder, and start ``work`` on a thread.

        ``project_dir`` is the project folder of the request. ``experiment_id`` is the folder
        of a resume or an evaluate, and ``None`` for a new simulation. ``prepare`` makes the
        checks of the start and returns the experiment folder. It runs under the lock, so an
        error from it leaves no run.

        :raises RouteError: 409 ``run_in_progress`` when the run of ``experiment_id`` is
            alive, 503 ``engine_busy`` when another run is alive, or an error of ``prepare``.
            ``engine_busy`` names the run only when it is in the same project folder.
        """
        with self._lock:
            if self._run is not None:
                if experiment_id is not None and self._run.is_of(
                    project_dir, experiment_id
                ):
                    raise RouteError(
                        409,
                        "run_in_progress",
                        f"The experiment {experiment_id!r} runs now.",
                    )
                if self._run.project_dir == project_dir:
                    running = f"the experiment {self._run.experiment_id!r}"
                else:
                    running = "an experiment of another user account"
                raise RouteError(
                    503,
                    "engine_busy",
                    f"The engine runs {running}. Start this run when that run ends.",
                    retryable=True,
                )
            experiment_dir = prepare()
            run = Run(
                project_dir=project_dir,
                experiment_id=experiment_dir.name,
                experiment_dir=experiment_dir,
                phase=phase,
                start_seq=last_seq(experiment_dir),
            )
            thread = threading.Thread(
                target=self._run_thread,
                args=(run, work),
                name=f"metis-engine-{run.experiment_id}",
                daemon=True,
            )
            self._run, self._thread = run, thread
            thread.start()
            return run.experiment_id

    def stop(self, project_dir: Path, experiment_id: str) -> None:
        """Set the stop flag of the run of ``experiment_id`` in ``project_dir``.

        :raises RouteError: 409 ``no_run`` when that experiment does not run.
        """
        with self._lock:
            if self._run is None or not self._run.is_of(project_dir, experiment_id):
                raise RouteError(
                    409, "no_run", f"The experiment {experiment_id!r} does not run."
                )
            self._run.stop.set()

    def current(self, project_dir: Path, experiment_id: str) -> Run | None:
        """The run of ``experiment_id`` in ``project_dir`` when it is alive, else ``None``."""
        with self._lock:
            if self._run is not None and self._run.is_of(project_dir, experiment_id):
                return self._run
            return None

    @contextmanager
    def idle_in(self, project_dir: Path) -> Iterator[bool]:
        """Yield whether no run is alive in ``project_dir``, and hold the lock of the runs.

        No run starts until the block ends, so the answer stays true for the full block.
        """
        with self._lock:
            yield self._run is None or self._run.project_dir != project_dir

    def shutdown(self, timeout: float) -> None:
        """Stop the run and wait for its thread, for at most ``timeout`` seconds."""
        with self._lock:
            run, thread = self._run, self._thread
            if run is not None:
                run.stop.set()
        if run is None or thread is None:
            return
        thread.join(timeout)
        if thread.is_alive():
            logger.warning(
                "engine_run_did_not_stop",
                experiment_id=run.experiment_id,
                timeout_seconds=timeout,
            )

    def _run_thread(
        self,
        run: Run,
        work: Callable[[Path, threading.Event, Console], object],
    ) -> None:
        """Run ``work`` with the console file of the experiment, then forget the run.

        The engine ends the events log with ``interrupted`` or ``failed`` before it raises,
        so a ``RunStopped`` or a ``RunError`` needs nothing more. Any other error is logged.
        """
        try:
            logs = run.experiment_dir / execution_layout.LOGS
            logs.mkdir(parents=True, exist_ok=True)
            with (logs / CONSOLE_FILE).open("a", encoding="utf-8") as handle:
                console = Console(file=handle, color_system=None, width=120)
                work(run.experiment_dir, run.stop, console)
        except (engine_run.RunStopped, engine_run.RunError):
            pass
        except Exception:
            logger.exception(
                "engine_run_failed",
                experiment_id=run.experiment_id,
                phase=run.phase,
            )
        finally:
            with self._lock:
                if self._run is run:
                    self._run, self._thread = None, None


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
    "Run",
    "last_seq",
    "read_events",
    "setup_engine_process",
]
