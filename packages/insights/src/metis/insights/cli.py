"""metis insights — build reports from evaluation results.

No `from __future__ import annotations`: Typer reads the parameter annotations at
runtime, so `Path` must stay a real import.
"""

from pathlib import Path

import typer

from metis.core import execution_layout
from metis.core.console import console
from metis.core.logging import configure_logging
from metis.core.reporting import EvaluationResults
from metis.insights import __version__
from metis.insights.report import format_terminal_summary, save_report

app = typer.Typer(help="Build METIS reports from evaluation results.")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"metis-insights {__version__}")
        raise typer.Exit()


# The callback also keeps `report` a subcommand: Typer collapses a single-command
# app without one, which would break `metis insights report`.
@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback, is_eager=True
    ),
) -> None:
    pass


@app.command()
def report(
    results_file: Path = typer.Option(
        ...,
        "--results-file",
        help=(
            "results.json that `metis engine evaluate` wrote, "
            "e.g. experiments/execute/my-eval-20260820-143000/outputs/reports/results.json"
        ),
    ),
) -> None:
    """Print the grader summary and write report.json and report.html."""
    configure_logging()
    path = results_file.resolve()
    try:
        results = EvaluationResults.load_file(path)
        experiment_dir = execution_layout.experiment_root_from_results(path)
    except (OSError, ValueError) as exc:
        # markup=False: pydantic errors contain "[type=...]", which Rich would drop.
        console.print(
            f"Error: cannot read results file '{path}': {exc}",
            style="bold red",
            markup=False,
        )
        raise typer.Exit(code=1) from None

    try:
        console.print(format_terminal_summary(results), markup=False)
        paths = save_report(results, experiment_dir)
    except Exception as exc:
        console.print(
            f"Error: report not written: {type(exc).__name__}: {exc}",
            style="bold red",
            markup=False,
        )
        raise typer.Exit(code=1) from exc

    if paths is None:
        specification = experiment_dir / execution_layout.SPECIFICATION
        console.print(
            f"  Report:       not written (no readable {specification})", markup=False
        )
        return
    html_path, json_path = paths
    console.print(f"  JSON report:  {json_path}", markup=False)
    console.print(f"  HTML report:  {html_path}", markup=False)
    console.print(f"  Open with:    open {html_path}\n", markup=False)
