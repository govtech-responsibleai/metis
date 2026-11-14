"""Helpers that the simulation and the evaluation of an experiment folder share."""

from __future__ import annotations

import shlex
import shutil
from typing import TYPE_CHECKING

from metis.core import execution_layout
from metis.core.phase_events import INTERRUPTED_REASON
from metis.engine.runs.errors import RunError, RunStopped

if TYPE_CHECKING:
    from pathlib import Path

    from metis.core.phase_events import Phase, PhaseEventLog


def trial_record_files(experiment_dir: Path) -> list[Path]:
    """Return the trial records of ``experiment_dir``, oldest first."""
    return sorted(
        (experiment_dir / execution_layout.TRIALS).glob(
            f"*/{execution_layout.TRIAL_RECORD}"
        ),
        key=lambda path: path.stat().st_mtime,
    )


def clear_evaluation_outputs(experiment_dir: Path) -> None:
    """Remove the previous evaluation's trial files, saved traces and ``results.json``.

    None of them may outlive the evaluation that made them: the report would show grades
    or a conversation that the new evaluation did not produce. ``logs/`` is kept.
    """
    shutil.rmtree(experiment_dir / execution_layout.EVALUATION, ignore_errors=True)
    shutil.rmtree(experiment_dir / execution_layout.TRACES, ignore_errors=True)
    (experiment_dir / execution_layout.RESULTS).unlink(missing_ok=True)


def end_phase_on_error(events: PhaseEventLog, phase: Phase, exc: BaseException) -> None:
    """Write the last line of a phase that stopped with ``exc``.

    A stop, a ``KeyboardInterrupt``, or an exit with code 130 is ``interrupted``. Any other
    error is ``failed``. The reason of a ``RunError`` is its text, which the run printed.
    An exit has no reason. The reason of any other error is its type and text.
    """
    if isinstance(exc, RunStopped | KeyboardInterrupt) or (
        isinstance(exc, SystemExit) and exc.code == 130
    ):
        events.emit(phase, "interrupted", reason=INTERRUPTED_REASON)
    elif isinstance(exc, RunError):
        events.emit(phase, "failed", reason=str(exc))
    elif isinstance(exc, SystemExit):
        events.emit(phase, "failed")
    else:
        events.emit(phase, "failed", reason=f"{type(exc).__name__}: {exc}")


def evaluate_command(experiment_dir: Path) -> str:
    """Build the shell-safe command for evaluating a simulation output."""
    return shlex.join(
        ["metis", "engine", "evaluate", "--experiment-dir", str(experiment_dir)]
    )


def resume_command(experiment_dir: Path, command: str) -> str:
    """Build the shell-safe command for resuming a simulation output."""
    return shlex.join(
        [
            "metis",
            "engine",
            command,
            "--resume",
            "--experiment-dir",
            str(experiment_dir),
        ]
    )
