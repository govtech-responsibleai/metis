from importlib.metadata import PackageNotFoundError, version

import typer

from metis.engine.cli import app as engine_app
from metis.insights.cli import app as insights_app
from metis.wizard.bootstrap import cli_app as wizard_app

try:
    __version__ = version("metis")
except PackageNotFoundError:
    __version__ = "0.0.0.dev0"


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"metis {__version__}")
        raise typer.Exit()


app = typer.Typer(
    name="metis",
    help="METIS — Measurement and Evaluation of Trustworthy Intelligent Systems.",
)


@app.callback(invoke_without_command=True)
def main(
    version: bool = typer.Option(
        False, "--version", "-V", callback=version_callback, is_eager=True
    ),
) -> None:
    pass


@app.command()
def doctor() -> None:
    """Check the local environment: keys are set, the services accept them, the install is sound."""
    from metis.core.model_settings import ModelSettingsError, load_env
    from metis.engine.doctor import report, run_checks

    try:
        load_env()
    except ModelSettingsError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    if not report(run_checks()):
        raise typer.Exit(1)


app.add_typer(engine_app, name="engine")
app.add_typer(wizard_app, name="wizard")
app.add_typer(insights_app, name="insights")


if __name__ == "__main__":
    app()
