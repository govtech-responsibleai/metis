"""Writes experiment-level simulation and evaluation logs."""

from __future__ import annotations

import json as json_mod
from typing import IO, TYPE_CHECKING, Literal

from metis.core.logging import iso_timestamp

from .router import _trial_log_filename

if TYPE_CHECKING:
    from pathlib import Path


class OrchestrationLogger:
    """Writes simulate.log — the experiment-level timeline index.

    Records scenario/run start and completion events with timestamps
    and pointers to per-run detail logs. Intended for quick post-hoc
    triage: scan this file to find the run you care about, then follow
    the log path to full DEBUG output.
    """

    def __init__(
        self,
        log_dir: Path,
        log_format: Literal["text", "json"] = "text",
        *,
        append: bool = False,
    ) -> None:
        self._log_dir = log_dir
        self._log_format = log_format
        log_dir.mkdir(parents=True, exist_ok=True)
        self._handle: IO[str] = open(  # noqa: SIM115
            log_dir / "simulate.log", "a" if append else "w", encoding="utf-8"
        )

    def _timestamp(self) -> str:
        return iso_timestamp()

    def _write_text(self, line: str) -> None:
        self._handle.write(f"[{self._timestamp()}] {line}\n")
        self._handle.flush()

    def _write_json(self, data: dict) -> None:
        data["timestamp"] = self._timestamp()
        self._handle.write(json_mod.dumps(data, default=str) + "\n")
        self._handle.flush()

    def scenario_started(self, scenario_id: str) -> None:
        if self._log_format == "json":
            self._write_json(
                {"event_type": "SCENARIO_STARTED", "scenario_id": scenario_id}
            )
        else:
            self._write_text(f"SCENARIO {scenario_id} STARTED")

    def resume_started(self, redo_count: int, complete_count: int) -> None:
        """Record the start and plan of a resumed simulation session."""
        if self._log_format == "json":
            self._write_json(
                {
                    "event_type": "RESUME_STARTED",
                    "redo_count": redo_count,
                    "complete_count": complete_count,
                }
            )
        else:
            self._write_text(
                f"RESUME STARTED ({redo_count} trials to redo, "
                f"{complete_count} already complete)"
            )

    def trial_started(
        self, scenario_id: str, persona_id: str, trial_index: int, num_trials: int
    ) -> None:
        log_filename = _trial_log_filename(
            scenario_id, persona_id, trial_index, num_trials
        )
        pointer = f"logs/{log_filename}"
        if self._log_format == "json":
            self._write_json(
                {
                    "event_type": "TRIAL_STARTED",
                    "scenario_id": scenario_id,
                    "persona_id": persona_id,
                    "trial_index": trial_index,
                    "num_trials": num_trials,
                    "log_file": pointer,
                }
            )
        else:
            self._write_text(
                f"TRIAL {scenario_id} x {persona_id} [trial {trial_index}/{num_trials}] "
                f"STARTED → {pointer}"
            )

    def trial_completed(
        self,
        scenario_id: str,
        persona_id: str,
        trial_index: int,
        num_trials: int,
        stop_reason: str,
        simulated_turns_completed: int,
        duration_seconds: float,
    ) -> None:
        duration_str = f"{duration_seconds:.0f}s"
        if self._log_format == "json":
            self._write_json(
                {
                    "event_type": "TRIAL_COMPLETED",
                    "scenario_id": scenario_id,
                    "persona_id": persona_id,
                    "trial_index": trial_index,
                    "num_trials": num_trials,
                    "stop_reason": stop_reason,
                    "simulated_turns_completed": simulated_turns_completed,
                    "duration_seconds": duration_seconds,
                }
            )
        else:
            self._write_text(
                f"TRIAL {scenario_id} x {persona_id} [trial {trial_index}/{num_trials}] "
                f"COMPLETED ({stop_reason}, {simulated_turns_completed} simulated turns, {duration_str})"
            )

    def scenario_completed(
        self, scenario_id: str, trials_passed: int, trials_total: int
    ) -> None:
        if self._log_format == "json":
            self._write_json(
                {
                    "event_type": "SCENARIO_COMPLETED",
                    "scenario_id": scenario_id,
                    "trials_passed": trials_passed,
                    "trials_total": trials_total,
                }
            )
        else:
            self._write_text(
                f"SCENARIO {scenario_id} COMPLETED ({trials_passed}/{trials_total} trials passed)"
            )

    def close(self) -> None:
        self._handle.flush()
        self._handle.close()


class EvaluationLogger:
    """Write the complete evaluation timeline to one text log."""

    def __init__(self, log_dir: Path, *, reset: bool = True) -> None:
        log_dir.mkdir(parents=True, exist_ok=True)
        self.path = log_dir / "evaluate.log"
        if reset:
            self.path.write_text("", encoding="utf-8")

    def write(self, message: str) -> None:
        """Append one timestamped evaluation event."""
        timestamp = iso_timestamp()
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {message}\n")
