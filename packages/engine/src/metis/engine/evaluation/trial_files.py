"""The per-trial evaluation file, private to the engine.

``results.json`` stays the only published contract. This file is how a later
``evaluate --resume`` learns that a trial's evaluation ended. Its existence is the record
that the trial was attempted: a trial that failed keeps its reason and has no records.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Literal

from pydantic import AwareDatetime, BaseModel, ValidationError

from metis.core.execution_layout import EVALUATION, evaluation_file_name
from metis.core.reporting import GraderRecord  # noqa: TC002 - Pydantic field type

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from datetime import datetime
    from pathlib import Path


class TrialEvaluation(BaseModel):
    """How the evaluation of one trial ended."""

    schema_version: Literal[1] = 1
    trial: str
    records: list[GraderRecord]
    failure_reason: str | None
    started_at: AwareDatetime
    finished_at: AwareDatetime


def trial_evaluation_path(experiment_dir: Path, trial: str) -> Path:
    """The file holding the evaluation of ``trial``."""
    return experiment_dir / EVALUATION / evaluation_file_name(trial)


def save_trial_evaluation(experiment_dir: Path, evaluation: TrialEvaluation) -> None:
    """Write the evaluation of one trial, creating the folder."""
    path = trial_evaluation_path(experiment_dir, evaluation.trial)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(evaluation.model_dump_json(indent=2) + "\n", encoding="utf-8")


def load_trial_evaluations(
    experiment_dir: Path, trials: Sequence[str]
) -> dict[str, TrialEvaluation]:
    """Read the files of ``trials``, in that order.

    A file that is missing, unreadable, invalid, or names another trial leaves its trial
    out, so the trial counts as not attempted. Other files are never read or deleted.
    """
    loaded: dict[str, TrialEvaluation] = {}
    for trial in trials:
        path = trial_evaluation_path(experiment_dir, trial)
        try:
            evaluation = TrialEvaluation.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError, ValidationError):
            continue
        if evaluation.trial == trial:
            loaded[trial] = evaluation
    return loaded


def grading_seconds(evaluations: Iterable[TrialEvaluation]) -> float:
    """Wall-clock seconds in which any evaluation was running: the union of the intervals."""
    spans = sorted((e.started_at, e.finished_at) for e in evaluations)
    total = timedelta()
    current: tuple[datetime, datetime] | None = None
    for start, end in spans:
        if current is None or start > current[1]:
            if current is not None:
                total += current[1] - current[0]
            current = (start, end)
        elif end > current[1]:
            current = (current[0], end)
    if current is not None:
        total += current[1] - current[0]
    return total.total_seconds()
