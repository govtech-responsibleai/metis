"""Relative paths shared by execution writers and report readers."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING
from urllib.parse import quote

if TYPE_CHECKING:
    from pathlib import Path

EXECUTIONS = PurePosixPath("experiments/execute")
INPUTS = PurePosixPath("inputs")
SPECIFICATION = INPUTS / "specification.yaml"
FIXTURES = INPUTS / "fixtures"
TRIALS = PurePosixPath("outputs/trials")
TRIAL_RECORD = "record.json"
"""File name of a trial's ``TrialRecord``, inside its folder under ``TRIALS``."""
REPORTS = PurePosixPath("outputs/reports")
RESULTS = REPORTS / "results.json"
TRACES = PurePosixPath("outputs/traces")
"""Folder of the traces `evaluate` saved, one file per session, named by `trace_file_name`."""
EVALUATION = PurePosixPath("outputs/evaluation")
"""Folder of each trial's evaluation outcome, private to the engine; one file per trial, named by `evaluation_file_name`."""
LOGS = PurePosixPath("logs")
EVENTS_FILE = "events.jsonl"
"""File name of the event log inside ``LOGS``: one ``PhaseEvent`` per line."""


def trace_file_name(session_id: str) -> str:
    """The file name of a session's saved traces. Percent-encoded, so no id can name a path."""
    return quote(session_id, safe="") + ".json"


def evaluation_file_name(trial: str) -> str:
    """The file name of a trial's evaluation outcome. Percent-encoded, so no id can name a path."""
    return quote(trial, safe="") + ".json"


def experiment_root_from_results(results_file: Path) -> Path:
    """Find the execution root for a results file in outputs/reports/."""
    root = results_file.parent
    for part in reversed(REPORTS.parts):
        if root.name != part:
            raise ValueError("The results file must be in outputs/reports/.")
        root = root.parent
    return root
