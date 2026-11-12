"""Terminal summary and persistence of the target evaluation report.

Produces:
1. A terminal summary table.
2. The target evaluation report, as an HTML page and as JSON data.

The report joins each grader result to its Criterion in the Specification. A reader
can see which Behaviour needs attention and which Persona or Scenario is hard to test.
Every number comes from a file the run already wrote; no model writes any of its text.
A run with no target specification writes no report.

`ensure_report` builds the same report of an experiment folder on request.
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from metis.core import execution_layout
from metis.core.logging import get_logger
from metis.core.report import Report
from metis.core.reporting import EvaluationResults
from metis.insights._aggregation import OutcomeCounts, aggregate_graders, mean_of
from metis.insights._report import build_report, load_report_sources
from metis.insights._report_page import render_report_page

if TYPE_CHECKING:
    from pathlib import Path

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


@dataclass(frozen=True)
class ReportFiles:
    """The report.json and report.html of one experiment."""

    json: Path
    html: Path


@dataclass(frozen=True)
class ResultsPending:
    """The experiment has no results.json yet, because `evaluate` has not finished. That is
    not an error."""


class ReportBuildError(Exception):
    """The experiment has a results.json, but its report cannot be built.

    The message names the file inside its experiment folder. It never holds file content.
    """


def _write_atomic(path: Path, text: str) -> None:
    """Replace ``path`` in one step, so a concurrent reader or writer never sees half a file."""
    # tempfile makes owner-only files. os.open with 0o666 follows the umask, so the report
    # gets the same permissions as any file the user writes.
    temp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    try:
        # encoding is explicit because the default is the locale encoding, which is cp1252
        # on Windows. The rendered page contains characters outside it (U+2192 among them),
        # so the write would raise UnicodeEncodeError part way through the file.
        with open(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def save_report(results: EvaluationResults, experiment_dir: Path) -> ReportFiles | None:
    """Write the target evaluation report into `experiment_dir/outputs/reports/`.

    The report reads `inputs/specification.yaml` and `outputs/trials/*/record.json` from the
    experiment directory. `simulate` freezes the input document there. A run with no
    specification gets no report, and that is not an error.

    :returns: The report files, or `None` when there is no specification.
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

    (experiment_dir / execution_layout.REPORTS).mkdir(parents=True, exist_ok=True)
    json_path = experiment_dir / execution_layout.REPORT_JSON
    html_path = experiment_dir / execution_layout.REPORT_HTML
    _write_atomic(
        json_path,
        json.dumps(report_model.model_dump(by_alias=True), indent=1, default=str)
        + "\n",
    )
    _write_atomic(html_path, render_report_page(report, title=report["target"]))

    logger.info(
        "report_written",
        features=len(report["features"]),
        behaviours=len(report["behaviours"]),
        criteria=len(report["criteria"]),
        scored=sum(1 for c in report["criteria"].values() if c["rate"] is not None),
        unresolved=len(report["unresolved"]),
    )
    return ReportFiles(json=json_path, html=html_path)


def ensure_report(experiment_dir: Path) -> ReportFiles | ResultsPending:
    """Return the report files of ``experiment_dir``, and build them when they are missing or stale.

    A report is stale when it is older than results.json. A second call with no new results
    writes nothing.

    :raises ReportBuildError: results.json or the frozen Specification cannot be read, or
        the results do not make a report, such as an experiment with an invalid threshold.
    """
    results_path = experiment_dir / execution_layout.RESULTS
    if not results_path.is_file():
        return ResultsPending()
    files = ReportFiles(
        json=experiment_dir / execution_layout.REPORT_JSON,
        html=experiment_dir / execution_layout.REPORT_HTML,
    )
    results_time = results_path.stat().st_mtime_ns
    if all(
        path.is_file() and path.stat().st_mtime_ns >= results_time
        for path in (files.json, files.html)
    ):
        return files
    try:
        results = EvaluationResults.load_file(results_path)
    except (OSError, ValueError) as exc:
        logger.warning("results_unreadable", path=str(results_path), error=str(exc))
        raise ReportBuildError(
            f"Cannot read {experiment_dir.name}/{execution_layout.RESULTS}."
        ) from None
    try:
        saved = save_report(results, experiment_dir)
    except ValueError as exc:
        logger.warning("report_unbuildable", path=str(results_path), error=str(exc))
        raise ReportBuildError(
            f"Cannot build the report from {experiment_dir.name}/{execution_layout.RESULTS}."
        ) from None
    if saved is None:
        raise ReportBuildError(
            f"Cannot read {experiment_dir.name}/{execution_layout.SPECIFICATION}."
        )
    return saved
