"""Paths inside one Experiment folder, shared by execution writers and report readers.

``project_layout`` gives the folder that holds the Experiment folders.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING
from urllib.parse import quote

if TYPE_CHECKING:
    from pathlib import Path

SPECIFICATION_DIR = PurePosixPath("specification")
"""The frozen copy of the input folder that the Experiment ran."""
SPECIFICATION = SPECIFICATION_DIR / "specification.yaml"
FIXTURES = SPECIFICATION_DIR / "fixtures"
TRIALS = PurePosixPath("outputs/trials")
TRIAL_RECORD = "record.json"
"""File name of a trial's ``TrialRecord``, inside its folder under ``TRIALS``."""
REPORTS = PurePosixPath("outputs/reports")
RESULTS = REPORTS / "results.json"
REPORT_JSON = REPORTS / "report.json"
REPORT_HTML = REPORTS / "report.html"
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
