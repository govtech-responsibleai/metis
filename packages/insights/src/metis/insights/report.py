"""Terminal summary and persistence of the target evaluation report.

Produces:
1. A terminal summary table.
2. The target evaluation report, as an HTML page and as JSON data.

The report joins each grader result to its Criterion in the Specification. A reader
can see which Behaviour needs attention and which Persona or Scenario is hard to test.
Every number comes from a file the run already wrote; no model writes any of its text.
A run with no target specification writes no report.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from metis.core import execution_layout
from metis.core.logging import get_logger
from metis.insights._aggregation import OutcomeCounts, aggregate_graders, mean_of
from metis.insights._models import Report
from metis.insights._report import build_report, load_report_sources
from metis.insights._report_page import render_report_page

if TYPE_CHECKING:
    from pathlib import Path

    from metis.core.reporting import EvaluationResults

logger = get_logger(__name__)


def format_terminal_summary(results: EvaluationResults) -> str:
    """Summarize all grader runs, including records with no specification match.

    The summary has no specification, so its last row takes the unweighted mean of the
    criterion rows. Its counts are the totals of all runs.
    """
    groups = aggregate_graders(results.records)
    lines = [
        f"EVAL RUN: {results.run_id}",
        "Criterion / grader                   Pass  Fail  Skip  Error   Rate  Mean",
    ]
    total = OutcomeCounts()
    for (criterion, grader), bucket in sorted(groups.items()):
        label = f"{criterion} / {grader}"
        rate = (
            f"{bucket.pass_rate * 100:.1f}%" if bucket.pass_rate is not None else "N/A"
        )
        mean = (
            f"{bucket.average_score:.2f}" if bucket.average_score is not None else "N/A"
        )
        lines.append(
            f"{label:<36} {bucket.passed:>4}  {bucket.failed:>4}  "
            f"{bucket.skipped:>4}  {bucket.errored:>5}  {rate:>5}  {mean:>4}"
        )
        total.merge(bucket)
    total_rate = mean_of(bucket.pass_rate for bucket in groups.values())
    total_mean = mean_of(bucket.average_score for bucket in groups.values())
    rate = f"{total_rate * 100:.1f}%" if total_rate is not None else "N/A"
    mean = f"{total_mean:.2f}" if total_mean is not None else "N/A"
    lines.append(
        f"{'MEAN OF CRITERIA':<36} {total.passed:>4}  {total.failed:>4}  "
        f"{total.skipped:>4}  {total.errored:>5}  {rate:>5}  {mean:>4}"
    )
    return "\n".join(lines)


def save_report(
    results: EvaluationResults, experiment_dir: Path
) -> tuple[Path, Path] | None:
    """Write the target evaluation report into `experiment_dir/outputs/reports/`.

    The report reads `inputs/specification.yaml` and `outputs/trials/*/record.json` from the
    experiment directory. `simulate` freezes the input document there. A run with no
    specification gets no report, and that is not an error.

    :returns: The HTML path and the JSON path, or `None` when there is no specification.
    """
    sources = load_report_sources(experiment_dir)
    if sources is None:
        return None
    specification, trial_outcomes = sources

    report = build_report(
        specification,
        results,
        timestamp=datetime.now().isoformat(),
        trial_outcomes=trial_outcomes,
    )

    report_model = Report.model_validate(report)

    reports_dir = experiment_dir / execution_layout.REPORTS
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "report.json"
    html_path = reports_dir / "report.html"
    # encoding is explicit because write_text() otherwise uses the locale encoding,
    # which is cp1252 on Windows. The rendered page contains characters outside it
    # (U+2192 among them), so the write would open the file, truncate it, then raise
    # UnicodeEncodeError, leaving a 0-byte report.html behind.
    json_path.write_text(
        json.dumps(report_model.model_dump(by_alias=True), indent=1, default=str)
        + "\n",
        encoding="utf-8",
    )
    html_path.write_text(
        render_report_page(report, title=report["target"]), encoding="utf-8"
    )

    logger.info(
        "report_written",
        features=len(report["features"]),
        behaviours=len(report["behaviours"]),
        criteria=len(report["criteria"]),
        scored=sum(1 for c in report["criteria"].values() if c["rate"] is not None),
        unresolved=len(report["unresolved"]),
    )
    return html_path, json_path
