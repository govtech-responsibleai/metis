from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from metis.core.reporting import EvaluationResults
from metis.insights._aggregation import wilson_interval
from metis.insights._models import Report
from metis.insights._report import build_report
from metis.insights.report import save_report
from tests.fixtures.insights.report_experiment import (
    grader_record,
    grader_records,
    specification,
    write_experiment,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("passed", "failed", "lower", "upper"),
    [
        (0, 3, 0.0, 0.5614970317550454),
        (3, 0, 0.4385029682449546, 1.0),
        (8, 2, 0.4901624715366417, 0.9433178485456247),
        (1, 0, 0.2065493143772374, 1.0),
        (0, 1, 0.0, 0.7934506856227626),
    ],
)
def test_wilson_limits(passed: int, failed: int, lower: float, upper: float) -> None:
    interval = wilson_interval(passed, failed)
    assert interval is not None
    assert interval.method == "wilson"
    assert interval.confidence_level == 0.95
    assert interval.lower == pytest.approx(lower, abs=1e-12)
    assert interval.upper == pytest.approx(upper, abs=1e-12)


def test_no_evaluated_trials_has_no_interval() -> None:
    assert wilson_interval(0, 0) is None


def test_case_intervals_keep_each_task_and_trial_separate() -> None:
    results = EvaluationResults(
        run_id="run-1",
        records=[
            grader_record("T-1", 1, "C-1", 0.9, 0.8, "errored"),
            grader_record("T-1", 2, "C-1", 0.1, 0.2),
            grader_record("T-2", 1, "C-1", 0.9),
        ],
    )
    report = Report.model_validate(build_report(specification(), results))
    first, second = report.resultTable.rows
    cell = first.results["C-1"]
    assert (cell.pass_, cell.fail, cell.evaluated) == (1, 1, 2)
    assert cell.confidence_interval == wilson_interval(1, 1)
    assert second.results["C-1"].confidence_interval == wilson_interval(1, 0)


def test_case_interval_uses_only_passed_and_failed_trials() -> None:
    plan = specification()
    plan["tasks"][0]["num_trials"] = 5
    results = EvaluationResults(
        run_id="run-1",
        records=[
            grader_record("T-1", 1, "C-1", 0.9),
            grader_record("T-1", 2, "C-1", 0.1),
            grader_record("T-1", 3, "C-1", "skipped"),
            grader_record("T-1", 4, "C-1", "errored"),
        ],
    )
    report = Report.model_validate(build_report(plan, results))
    cell = report.resultTable.rows[0].results["C-1"]
    assert (cell.pass_, cell.fail, cell.skip, cell.error, cell.evaluated) == (
        1,
        1,
        1,
        1,
        2,
    )
    assert cell.confidence_interval == wilson_interval(1, 1)


def test_saved_report_excludes_ungraded_trials_from_intervals(tmp_path: Path) -> None:
    records = grader_records()
    write_experiment(tmp_path, records)
    paths = save_report(EvaluationResults(run_id="run-1", records=records), tmp_path)
    assert paths is not None
    _, json_path = paths
    saved = json.loads(json_path.read_text(encoding="utf-8"))
    report = Report.model_validate(saved)
    first, second = report.resultTable.rows
    interval = first.results["C-1"].confidence_interval
    assert interval is not None
    assert interval == wilson_interval(2, 0)
    assert saved["resultTable"]["rows"][0]["results"]["C-1"]["confidence_interval"] == {
        "method": "wilson",
        "confidence_level": 0.95,
        "lower": interval.lower,
        "upper": 1.0,
    }
    assert first.results["C-2"].confidence_interval == wilson_interval(0, 1)
    assert "C-2" not in second.results
    assert first.results["C-3"].skip == 1
    assert first.results["C-3"].confidence_interval is None
    assert second.results["C-3"].error == 1
    assert second.results["C-3"].confidence_interval is None
    assert all(
        "confidence_interval" not in cell
        for row in saved["resultTable"]["rows"]
        for trial in row["trials"]
        for cell in trial["results"].values()
    )
    assert all("confidence_interval" not in cell for cell in saved["criteria"].values())
    assert saved["schema_version"] == 1
