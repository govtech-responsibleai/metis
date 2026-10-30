"""Command-line interface for shared METIS evaluations."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
)
from rich.table import Table

from metis.core.console import console
from metis.testbed.calculation import main as score_folder
from metis.testbed.contracts import EvaluationProgress, EvaluationRequest
from metis.testbed.embeddings import main as embed_folder
from metis.testbed.evaluation import (
    LEVELS,
    MetisWizardTarget,
    OneShotInteraction,
    compare_versions,
    detect_target_version,
    run_evaluation,
)
from metis.wizard import InterviewerUnavailable
from metis.wizard.adapters.llm.gateway import GatewayInterviewer

if TYPE_CHECKING:
    from metis.testbed.contracts import EvaluationRecord

TESTBED_ROOT = Path(__file__).resolve().parents[3]
REPOSITORY_ROOT = TESTBED_ROOT.parents[1]
DEFAULT_CONFIG = TESTBED_ROOT / "wizard/cases/config.yaml"
DEFAULT_RESULTS = TESTBED_ROOT / "results"

app = typer.Typer(help="Run and compare shared METIS evaluations.")
app.command("embed")(embed_folder)
app.command("score")(score_folder)


def _score(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "—"


def _print_behaviour_nn(record: EvaluationRecord) -> None:
    table = Table(title="Behaviour overlap · mean NN similarity (experimental)")
    for heading in ("Test Case", "Text", "Ref count", "Gen count", "Ref NN", "Gen NN"):
        table.add_column(heading)
    for result in record.cases:
        for version, summary in result.behaviour_nn.items():
            table.add_row(
                result.case_id,
                "Behaviour" if version == "behaviour" else "With context",
                str(summary.reference_count),
                str(summary.generated_count),
                _score(summary.reference_mean_nn),
                _score(summary.generated_mean_nn),
            )
        if not result.behaviour_nn:
            table.add_row(result.case_id, "—", "—", "—", "—", "—")
    console.print(table)
    console.print(
        "Lower NN means less overlap. Compare counts. This is not a coverage score or a pass/fail gate."
    )
    console.print(
        "With context includes the feature, behaviour, and criteria. Fewer than two behaviours gives no NN score."
    )


@app.command()
def wizard(
    target_version: Annotated[
        str | None,
        typer.Option(
            "--target-version",
            help="Version name saved with this Wizard Target result.",
        ),
    ] = None,
    config: Annotated[
        Path,
        typer.Option(exists=True, dir_okay=False, help="Evaluation configuration."),
    ] = DEFAULT_CONFIG,
    results: Annotated[
        Path,
        typer.Option(file_okay=False, help="Directory for immutable results."),
    ] = DEFAULT_RESULTS,
) -> None:
    """Evaluate the Wizard with every Test Case in config.yaml."""
    try:
        version = target_version or detect_target_version(REPOSITORY_ROOT)
        interviewer = GatewayInterviewer()
    except (InterviewerUnavailable, ValueError) as exc:
        console.print(f"[red]Cannot start Wizard evaluation:[/red] {exc}")
        raise typer.Exit(code=2) from exc
    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Starting Wizard evaluation", total=None)

        def show_progress(update: EvaluationProgress) -> None:
            progress.update(
                task,
                completed=update.completed,
                total=update.total,
                description=f"[bold]{update.case_id}[/bold] · {update.phase}",
            )

        record, output = run_evaluation(
            EvaluationRequest(
                config_path=config,
                results_root=results,
                target_version=version,
            ),
            target=MetisWizardTarget(interviewer),
            interaction=OneShotInteraction(),
            on_progress=show_progress,
        )
    table = Table(title=f"Wizard evaluation · {record.target_version}")
    table.add_column("Test Case")
    for name in LEVELS:
        table.add_column(name.title(), justify="right")
    table.add_column("Status")
    table.add_column("Interview")
    for result in record.cases:
        values = (
            [_score(getattr(result.scores, name).similarity) for name in LEVELS]
            if result.scores is not None
            else ["—"] * len(LEVELS)
        )
        table.add_row(
            result.case_id,
            *values,
            str(result.status),
            result.lifecycle_outcome or "not started",
        )
    table.add_section()
    table.add_row(
        "Case average",
        *[_score(getattr(record.aggregate, name).case_average) for name in LEVELS],
        "",
    )
    table.add_row(
        "Item weighted",
        *[_score(getattr(record.aggregate, name).item_weighted) for name in LEVELS],
        "",
    )
    console.print(table)
    _print_behaviour_nn(record)
    for result in record.cases:
        if result.error:
            reason = (
                result.error if len(result.error) <= 240 else result.error[:237] + "..."
            )
            console.print(f"{result.case_id}: {reason}", markup=False)
    console.print(f"Saved: {output}")
    if any(result.status.value != "scored" for result in record.cases):
        raise typer.Exit(code=1)


@app.command()
def compare(
    older_version: Annotated[str, typer.Argument(help="Older Target version.")],
    newer_version: Annotated[str, typer.Argument(help="Newer Target version.")],
    target: Annotated[str, typer.Option(help="Saved Target name.")] = "metis-wizard",
    results: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False, help="Saved result directory."),
    ] = DEFAULT_RESULTS,
) -> None:
    """Compare the latest saved result for two Target versions."""
    try:
        comparison = compare_versions(
            results,
            target=target,
            older_version=older_version,
            newer_version=newer_version,
        )
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]Cannot compare saved results:[/red] {exc}")
        raise typer.Exit(code=2) from exc
    table = Table(title=f"{comparison.target} · {older_version} → {newer_version}")
    table.add_column("Test Case")
    for name in LEVELS:
        table.add_column(name.title(), justify="right")
    for case_id, changes in comparison.case_changes.items():
        table.add_row(
            case_id,
            *[
                f"{changes[name]:+.3f}" if changes[name] is not None else "—"
                for name in LEVELS
            ],
        )
    table.add_section()
    table.add_row(
        "Case average",
        *[
            f"{comparison.changes[name]:+.3f}"
            if comparison.changes[name] is not None
            else "—"
            for name in LEVELS
        ],
    )
    console.print(table)
    console.print(f"Compared {comparison.older_id} with {comparison.newer_id}.")


if __name__ == "__main__":
    app()
