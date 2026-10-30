"""Run the report page renderers in Node and return the HTML they build."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import TYPE_CHECKING, Any

import pytest

from metis.core.reporting import EvaluationResults, GraderRecord
from metis.insights._models import Report
from metis.insights._report import build_report, load_report_sources
from metis.insights._report_page import RENDER_SCRIPT
from tests.fixtures.insights.report_experiment import grader_records

if TYPE_CHECKING:
    from pathlib import Path


def build(
    experiment: Path, records: list[GraderRecord] | None = None
) -> dict[str, Any]:
    """The report dictionary for the experiment that holds ``experiment``."""
    sources = load_report_sources(experiment.parents[2])
    assert sources is not None
    specification, trials = sources
    results = EvaluationResults(
        run_id="run-1", records=grader_records() if records is None else records
    )
    data = build_report(specification, results, trial_outcomes=trials)
    return Report.model_validate(data).model_dump(by_alias=True)


def render_js(report: dict[str, Any], call: str) -> str:
    """The string that the JavaScript expression ``call`` returns, with ``V`` set to ``report``."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed to run the report renderers")
    script = (
        f"const V={json.dumps(report)};\n{RENDER_SCRIPT}\n"
        f"process.stdout.write(String({call}));"
    )
    return subprocess.run(
        [node, "-e", script], check=True, capture_output=True, text=True
    ).stdout


def open_case(report: dict[str, Any], task_id: str, trial: int = 1) -> str:
    """The trials panel of the test case ``task_id``, with ``trial`` selected."""
    state = json.dumps(
        {
            "openCase": task_id,
            "trialByCase": {task_id: trial},
            "markCol": None,
            "markRow": None,
        }
    )
    return render_js(report, f"renderDrawer(V,{state})")
