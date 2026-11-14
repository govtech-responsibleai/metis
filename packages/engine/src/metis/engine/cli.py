"""Command-line interface for metis-engine."""

from __future__ import annotations

import os
import re
import shlex
import signal
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

import typer

from metis.core import execution_layout
from metis.core.console import console
from metis.core.execution_layout import find_project_root
from metis.core.phase_events import PhaseEventLog
from metis.engine import __version__
from metis.engine.runs import EvaluationInputError, EvaluationOutcome
from metis.engine.runs._evaluation import evaluation_is_complete
from metis.engine.tracing import tracing_key

if TYPE_CHECKING:
    import types as _types
    from collections.abc import Iterator

    from metis.core.model_settings import ModelRole
    from metis.engine.extractor import TraceWaitSettings
    from metis.engine.simulation.types import Specification

app = typer.Typer(help="Run METIS evaluations against traces.")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"metis-engine {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback, is_eager=True
    ),
) -> None:
    pass


ProjectDirOption = Annotated[
    Path | None,
    typer.Option(
        "--project-dir",
        help=(
            "Existing project folder that holds experiments/execute/. New runs "
            "go under it, from any working directory. Default: the working "
            "directory or the nearest folder above it that has a pyproject.toml"
        ),
        show_default=False,
    ),
]


def _project_root(project_dir: Path | None) -> Path:
    """Return the folder that holds ``experiments/execute/``.

    ``--project-dir`` names it, and it must exist. Without it, the engine
    finds it from the working directory.
    """
    if project_dir is None:
        return find_project_root()
    resolved = project_dir.expanduser().resolve()
    if not resolved.is_dir():
        console.print(
            f"Error: the project folder '{resolved}' is not an existing folder.",
            style="bold red",
            markup=False,
        )
        raise typer.Exit(code=1)
    return resolved


def _warn_if_outside_project(experiment_dir: Path, project_root: Path) -> None:
    """Tell the user that a resume stays in its own run folder."""
    if experiment_dir.is_relative_to(project_root / execution_layout.EXECUTIONS):
        return
    console.print(
        f"Warning: the run folder '{experiment_dir}' is not in the project "
        f"folder '{project_root}'. The resume continues in the run folder.",
        style="yellow",
        markup=False,
    )


def _load_env() -> Path | None:
    """Read the one project `.env` (`metis.core.model_settings.load_env`). Exported values win.

    Returns the file that was read, so a missing-settings error can name it.
    """
    from metis.core.model_settings import ModelSettingsError, load_env

    try:
        return load_env()
    except ModelSettingsError as exc:
        console.print(f"Error: {exc}", style="bold red", markup=False)
        raise typer.Exit(code=1) from None


def _trace_wait_settings(langfuse_timeout: int) -> TraceWaitSettings:
    """Read the trace wait from ``--langfuse-timeout`` and ``.env``, or stop when it is invalid."""
    from metis.engine import extractor

    _load_env()
    try:
        return extractor.TraceWaitSettings.from_env(langfuse_timeout)
    except ValueError as exc:
        console.print(f"Error: {exc}", style="bold red", markup=False)
        raise typer.Exit(code=1) from None


def _check_model_roles(
    command: str, roles: list[ModelRole], env_file: Path | None
) -> None:
    """Stop before any client exists when a role that ``command`` calls has no API key."""
    from metis.core.model_settings import ModelSettingsError, check_roles

    try:
        check_roles(f"metis engine {command}", roles, os.environ, env_file)
    except ModelSettingsError as exc:
        console.print(f"Error: {exc}", style="bold red", markup=False)
        raise typer.Exit(code=1) from None


def _simulation_roles() -> list[ModelRole]:
    """The roles a simulation calls: the user agent and the runner agent."""
    from metis.core.model_settings import ModelRole

    return [ModelRole.USER_AGENT, ModelRole.RUNNER_AGENT]


def _needs_judge(specification: Specification) -> bool:
    """True when a criterion that a Task runs uses a model-based grader."""
    from metis.engine.evaluation import GraderSetupError, build_grader
    from metis.library.grader import JudgeArgs

    criteria_by_id = {c.id: c for b in specification.behaviours() for c in b.criteria}
    for scenario in specification.resolved_tasks():
        for ref in scenario.grader_refs:
            try:
                grader = build_grader(
                    criteria_by_id[ref.criterion_id],
                    default_judge_model=specification.experiment.defaults.judge_model,
                    env=os.environ,
                )
            except GraderSetupError:
                continue
            if isinstance(grader.args, JudgeArgs):
                return True
    return False


def _validate_inputs(input_dir: Path) -> None:
    """Check every input of a new run, or print the error and exit with code 1."""
    from metis.engine.runs import InvalidInputsError, validate_inputs

    try:
        validate_inputs(input_dir, console=console)
    except InvalidInputsError:
        sys.exit(1)


def _resolve_log_level(verbose: int, quiet: bool) -> str:
    """Resolve the CLI log level."""
    if quiet:
        return "ERROR"
    if verbose >= 2:
        return "DEBUG"
    if verbose >= 1:
        return "INFO"
    return "WARNING"


def _configure_process_logging(log_level: str, *, use_tui: bool = False) -> None:
    """Configure structured logging before importing engine modules."""
    from metis.core.logging import configure_logging

    configure_logging(level="DEBUG" if use_tui else log_level)

    # Module-level loggers cache their processor chain. Disable that cache so
    # the simulation log router can be installed after these imports.
    import structlog

    structlog.configure(cache_logger_on_first_use=False)


def _trial_record_files(experiment_dir: Path) -> list[Path]:
    """Return trial records in the same order used by the old CLI."""
    from metis.engine.runs._common import trial_record_files

    return trial_record_files(experiment_dir)


def _experiment_id(input_dir: Path) -> str | None:
    """Return the experiment id in ``input_dir``, or None if it cannot be read."""
    from metis.engine.simulation.types import Specification

    try:
        return Specification.load_file(input_dir.resolve() / "specification.yaml").id
    except Exception:
        return None


def _existing_outputs(input_dir: Path, project_root: Path) -> list[Path]:
    experiment_id = _experiment_id(input_dir)
    if experiment_id is None:
        return []
    experiments_root = project_root / execution_layout.EXECUTIONS
    if not experiments_root.is_dir():
        return []
    pattern = re.compile(rf"^{re.escape(experiment_id)}-\d{{8}}-\d{{6}}$")
    return sorted(
        candidate.resolve()
        for candidate in experiments_root.iterdir()
        if candidate.is_dir() and pattern.fullmatch(candidate.name)
    )


def _print_resume_flag_error(input_dir: Path, command: str, project_root: Path) -> None:
    """Report that ``--resume`` needs ``--experiment-dir``, and list candidates."""
    experiment_id = _experiment_id(input_dir)
    outputs = _existing_outputs(input_dir, project_root)

    if not outputs:
        if experiment_id is None:
            console.print(
                "Error: --resume needs --experiment-dir, not --input-dir.",
                style="bold red",
            )
        else:
            console.print(
                f"Error: no simulation output exists for experiment "
                f"'{experiment_id}'.\n"
                f"Run 'metis engine {command} --input-dir {input_dir}' first "
                "to create one.",
                style="bold red",
            )
        return

    lines = [
        "Error: --resume needs --experiment-dir, not --input-dir.",
        "Resume continues an output directory that simulate already created.",
        "",
        f"Outputs for experiment '{experiment_id}':",
        *(f"  {output}" for output in outputs),
        "",
        "Then run:",
        f"  metis engine {command} --resume --experiment-dir <one of the above>",
    ]
    console.print("\n".join(lines), style="bold red")


def _resolve_simulation_target(
    input_dir: Path | None,
    experiment_dir: Path | None,
    *,
    resume: bool,
    command: str,
    project_root: Path,
) -> Path:
    """Decide which directory ``simulate`` or ``run`` works on.

    Returns the source directory for a new run, or the validated output
    directory for a resume. Exits with code 1 on any invalid combination of
    ``--input-dir`` and ``--experiment-dir``.
    """
    if input_dir is not None and experiment_dir is not None:
        console.print(
            "Error: pass either --input-dir or --experiment-dir, not both.",
            style="bold red",
        )
        raise typer.Exit(code=1)

    if resume:
        if input_dir is not None:
            _print_resume_flag_error(input_dir, command, project_root)
            raise typer.Exit(code=1)
        if experiment_dir is None:
            console.print("Error: --resume needs --experiment-dir.", style="bold red")
            raise typer.Exit(code=1)
        try:
            return _resolve_experiment_dir(experiment_dir)
        except EvaluationInputError:
            raise typer.Exit(code=1) from None

    if experiment_dir is not None:
        console.print(
            "Error: --experiment-dir needs --resume. Start a new run with --input-dir.",
            style="bold red",
        )
        raise typer.Exit(code=1)
    if input_dir is None:
        console.print(
            "Error: pass --input-dir to start a new run, or "
            "--resume --experiment-dir to continue one.",
            style="bold red",
        )
        raise typer.Exit(code=1)
    return input_dir.resolve()


def _resolve_experiment_dir(experiment_dir: Path) -> Path:
    """Validate an explicit simulation output directory."""
    from metis.engine.runs import resolve_experiment_dir

    return resolve_experiment_dir(experiment_dir, console=console)


def _evaluate_command(experiment_dir: Path) -> str:
    """Build the shell-safe command for evaluating a simulation output."""
    from metis.engine.runs._common import evaluate_command

    return evaluate_command(experiment_dir)


def _resume_command(experiment_dir: Path, command: str) -> str:
    """Build the shell-safe command for resuming a simulation output."""
    from metis.engine.runs._common import resume_command

    return resume_command(experiment_dir, command)


def _report_command(results_file: Path) -> str:
    """Build the shell-safe command for reporting on an evaluation's results."""
    return shlex.join(
        ["metis", "insights", "report", "--results-file", str(results_file)]
    )


def _print_handoff(experiment_dir: Path, *, command: str) -> None:
    """Print the evaluate and resume commands for a simulation output."""
    resolved = experiment_dir.resolve()
    console.print(f"Specification: {resolved}")
    console.print(
        f"Evaluate: {_evaluate_command(resolved)}",
        no_wrap=True,
        overflow="ignore",
        crop=False,
        soft_wrap=True,
    )
    console.print(
        f"Resume: {_resume_command(resolved, command)}",
        no_wrap=True,
        overflow="ignore",
        crop=False,
        soft_wrap=True,
    )


def _print_evaluation_summary(
    experiment_dir: Path, outcome: EvaluationOutcome, *, pipeline: bool
) -> None:
    """Print the final summary for standalone evaluation or the combined run."""
    label = "PIPELINE COMPLETE" if pipeline else "EVALUATION COMPLETE"
    console.print(f"\n\n{'=' * 60}")
    console.print(
        f"  {label} — {outcome.total_records} run(s), {outcome.failed_records} failed"
    )
    console.print(f"  Specification: {experiment_dir}")
    console.print(f"  Log: {experiment_dir / execution_layout.LOGS / 'evaluate.log'}")
    if outcome.results_file is not None:
        # markup=False: Rich would drop a "[...]" segment of the path.
        console.print(f"  Results: {outcome.results_file}", markup=False)
        console.print(
            f"  Report: {_report_command(outcome.results_file)}",
            markup=False,
            no_wrap=True,
            overflow="ignore",
            crop=False,
            soft_wrap=True,
        )
    if outcome.failed_records:
        console.print(
            f"  Grade every trial again: {_evaluate_command(experiment_dir.resolve())}",
            markup=False,
            no_wrap=True,
            overflow="ignore",
            crop=False,
            soft_wrap=True,
        )
    console.print(f"{'=' * 60}")


def _check_simulation_settings(
    command: str, specification: Specification, env_file: Path | None
) -> None:
    """Check the roles that ``command`` calls, before any client exists.

    ``simulate`` checks the user agent and the runner agent. ``run``
    also checks the judge when a criterion uses a model-based grader.
    """
    from metis.core.model_settings import ModelRole

    roles = _simulation_roles()
    if command == "run" and _needs_judge(specification):
        roles.append(ModelRole.JUDGE)
    _check_model_roles(command, roles, env_file)
    console.print(_models_line(specification, roles), markup=False)


def _models_line(specification: Specification, roles: list[ModelRole]) -> str:
    """The models that a run uses, and where each comes from. Shown before any model call.

    It shows the experiment-level model of each role. A Test Case or a Criterion can set its
    own model in ``specification.yaml``, so the line also counts those.
    """
    from metis.core.model_settings import ModelRole, describe_models, resolve_role
    from metis.engine.simulation.model_settings import (
        runner_agent_settings,
        user_agent_settings,
    )

    defaults = specification.experiment.defaults
    user_agent = user_agent_settings(defaults.user_agent_model)
    by_role = {
        ModelRole.USER_AGENT: user_agent,
        ModelRole.RUNNER_AGENT: runner_agent_settings(
            defaults.runner_agent_model, user_agent_model=user_agent.model
        ),
        ModelRole.JUDGE: resolve_role(
            ModelRole.JUDGE, os.environ, defaults.judge_model
        ),
    }
    line = describe_models(by_role[role] for role in roles)
    own_tasks = sum(1 for task in specification.tasks if task.user_agent_model)
    own_criteria = sum(
        1
        for behaviour in specification.behaviours()
        for criterion in behaviour.criteria
        if criterion.grader_args.get("model")
    )
    extras = []
    if own_tasks:
        extras.append(f"{own_tasks} Test Case(s) set their own user agent model")
    if own_criteria and ModelRole.JUDGE in roles:
        extras.append(f"{own_criteria} Criterion(s) set their own judge model")
    if extras:
        line += ". " + "; ".join(extras) + " in specification.yaml"
    return line


def _run_simulation(
    input_dir: Path | None,
    experiment_dir: Path | None,
    *,
    command: str,
    verbose: int,
    quiet: bool,
    no_tui: bool,
    log_format: Literal["text", "json"],
    log_dir: Path | None,
    concurrency: int,
    resume: bool = False,
    project_dir: Path | None = None,
) -> Path:
    """Run simulation and return its experiment directory."""
    project_root = _project_root(project_dir)
    target = _resolve_simulation_target(
        input_dir,
        experiment_dir,
        resume=resume,
        command=command,
        project_root=project_root,
    )
    if resume and project_dir is not None:
        _warn_if_outside_project(target, project_root)
    env_file = _load_env()
    tracing_key()
    use_tui = not no_tui and sys.stderr.isatty()
    log_level = _resolve_log_level(verbose, quiet)

    # Configure logging before importing harness modules. They create
    # module-level loggers that cache the processor chain.
    _configure_process_logging(log_level, use_tui=use_tui)

    from metis.engine.simulation.types import Specification

    if resume:
        experiment_dir = target
        specification = Specification.load_file(
            experiment_dir / execution_layout.SPECIFICATION
        )
        _check_simulation_settings(command, specification, env_file)
    else:
        from metis.engine.runs import RunError, prepare_experiment, validate_inputs

        try:
            # The inputs are checked before the model settings, so that a bad input is the
            # first error. prepare_experiment checks them again and prints nothing.
            specification = validate_inputs(target, console=console)
            _check_simulation_settings(command, specification, env_file)
            experiment_dir = prepare_experiment(
                target, project_dir=project_root, console=console
            )
        except RunError:
            raise typer.Exit(code=1) from None

    from metis.engine.runs import RunError, RunStopped, resume_simulation, simulate

    run_simulation = resume_simulation if resume else simulate
    try:
        with _stop_on_sigint(use_tui) as stop:
            try:
                run_simulation(
                    experiment_dir,
                    concurrency=concurrency,
                    stop=stop,
                    console=console,
                    use_tui=use_tui,
                    log_level=log_level,
                    log_format=log_format,
                    log_dir=log_dir,
                )
            finally:
                # The run puts back the logging it found, which logs at the run's level.
                # What this process logs after the run, such as the Langfuse flush at exit,
                # shows only warnings.
                _configure_process_logging("WARNING")
    except BaseException as exc:
        if command == "run":
            PhaseEventLog.for_experiment_dir(experiment_dir).emit(
                "evaluating", "skipped"
            )
        if isinstance(exc, RunStopped):
            raise typer.Exit(code=130) from None
        if isinstance(exc, RunError):
            raise typer.Exit(code=1) from None
        raise
    return experiment_dir


@contextmanager
def _stop_on_sigint(use_tui: bool) -> Iterator[threading.Event]:
    """Give a stop flag that the first Ctrl-C sets. The second Ctrl-C exits with 130."""
    interrupt_count = 0
    interrupt_lock = threading.Lock()
    stop = threading.Event()

    def _handle_sigint(_signum: int, _frame: _types.FrameType | None) -> None:
        nonlocal interrupt_count
        with interrupt_lock:
            interrupt_count += 1
            if interrupt_count >= 2:
                if not use_tui:
                    console.print("\nForce abort.", style="bold red")
                sys.exit(130)
            stop.set()
            if not use_tui:
                console.print(
                    "\nInterrupt received — finishing current trial. "
                    "No new trials will start. Press Ctrl+C again to force abort.",
                    style="yellow",
                )

    prev_handler = signal.signal(signal.SIGINT, _handle_sigint)
    try:
        yield stop
    finally:
        signal.signal(signal.SIGINT, prev_handler)


def _run_evaluation(
    experiment_dir: Path,
    *,
    trace_wait: TraceWaitSettings,
    verbose: int,
    quiet: bool,
    concurrency: int = 1,
    command: Literal["evaluate", "run"] = "evaluate",
    resume: bool = False,
) -> EvaluationOutcome:
    """Set up the process, then evaluate the records in ``experiment_dir``.

    Ctrl-C stops the evaluation as it always has: ``asyncio.run`` cancels it and raises
    ``KeyboardInterrupt``. The stop flag is never set here.
    """
    from metis.engine.runs import evaluate, resume_evaluation

    _load_env()
    # Registered before the target's Langfuse client, so judge calls always have their own.
    tracing_key()
    _configure_process_logging(_resolve_log_level(verbose, quiet))
    run_evaluation = resume_evaluation if resume else evaluate
    return run_evaluation(
        experiment_dir,
        trace_wait=trace_wait,
        concurrency=concurrency,
        stop=threading.Event(),
        console=console,
        show_progress=sys.stderr.isatty(),
        command=command,
    )


def _run_evaluation_command(
    experiment_dir: Path,
    *,
    trace_wait: TraceWaitSettings,
    verbose: int,
    quiet: bool,
    concurrency: int = 1,
    command: Literal["evaluate", "run"] = "evaluate",
    resume: bool = False,
) -> EvaluationOutcome:
    """Run the evaluation, and turn its errors into the exit codes of the CLI.

    The evaluation has already printed each error and written its phase line.
    """
    from metis.engine.runs import EvaluationInputError, RunStopped

    try:
        return _run_evaluation(
            experiment_dir,
            trace_wait=trace_wait,
            verbose=verbose,
            quiet=quiet,
            concurrency=concurrency,
            command=command,
            resume=resume,
        )
    except RunStopped:
        raise typer.Exit(code=130) from None
    except EvaluationInputError:
        raise typer.Exit(code=1) from None
    except Exception as exc:
        raise typer.Exit(code=1) from exc


@app.command()
def simulate(
    input_dir: Path | None = typer.Option(
        None,
        "--input-dir",
        help="Source experiment directory (specification.yaml and fixtures/) for a new run",
    ),
    experiment_dir: Path | None = typer.Option(
        None,
        "--experiment-dir",
        help="Simulation output directory to resume; needs --resume",
    ),
    verbose: int = typer.Option(
        0, "--verbose", "-v", count=True, help="Increase logging verbosity"
    ),
    quiet: bool = typer.Option(
        False, "--quiet", help="Suppress output below ERROR level"
    ),
    no_tui: bool = typer.Option(
        False, "--no-tui", help="Disable TUI even in a terminal"
    ),
    log_format: Literal["text", "json"] = typer.Option(
        "text", "--log-format", help="Log file format: text or json"
    ),
    log_dir: Path | None = typer.Option(
        None,
        "--log-dir",
        help="Override log directory (default: co-located with results)",
    ),
    concurrency: int = typer.Option(
        1, "--concurrency", "-c", min=1, help="Max concurrent trials"
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        help="Continue the output named by --experiment-dir instead of starting a run",
    ),
    project_dir: ProjectDirOption = None,
) -> None:
    """Run simulation only and prepare the evaluation handoff."""
    output_dir = _run_simulation(
        input_dir,
        experiment_dir,
        command="simulate",
        verbose=verbose,
        quiet=quiet,
        no_tui=no_tui,
        log_format=log_format,
        log_dir=log_dir,
        concurrency=concurrency,
        resume=resume,
        project_dir=project_dir,
    )
    _print_handoff(output_dir, command="simulate")


@app.command()
def evaluate(
    experiment_dir: Path = typer.Option(
        ...,
        "--experiment-dir",
        help=(
            "Output directory that simulate created, "
            "e.g. experiments/execute/my-eval-20260820-143000/"
        ),
    ),
    langfuse_timeout: int = typer.Option(
        90,
        "--langfuse-timeout",
        help="Seconds to wait for each trial's Langfuse traces to be ready",
    ),
    verbose: int = typer.Option(
        0, "--verbose", "-v", count=True, help="Increase logging verbosity"
    ),
    quiet: bool = typer.Option(
        False, "--quiet", help="Suppress output below ERROR level"
    ),
    concurrency: int = typer.Option(
        1, "--concurrency", "-c", min=1, help="Max concurrent sessions"
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        help="Continue the evaluation in --experiment-dir; skip trials already evaluated",
    ),
) -> None:
    """Evaluate one simulation output directory."""
    try:
        resolved_experiment_dir = _resolve_experiment_dir(experiment_dir)
    except EvaluationInputError:
        raise typer.Exit(code=1) from None
    console.print(f"Selected experiment: {resolved_experiment_dir}")
    # A resume of a finished evaluation says "nothing to resume", which already covers it.
    nothing_to_resume = resume and evaluation_is_complete(resolved_experiment_dir)
    trace_wait = _trace_wait_settings(langfuse_timeout)
    outcome = _run_evaluation_command(
        resolved_experiment_dir,
        trace_wait=trace_wait,
        verbose=verbose,
        quiet=quiet,
        concurrency=concurrency,
        command="evaluate",
        resume=resume,
    )
    if outcome.total_records == 0 and not nothing_to_resume:
        console.print("nothing to evaluate")
    _print_evaluation_summary(resolved_experiment_dir, outcome, pipeline=False)


@app.command()
def run(
    input_dir: Path | None = typer.Option(
        None,
        "--input-dir",
        help="Source experiment directory (specification.yaml and fixtures/) for a new run",
    ),
    experiment_dir: Path | None = typer.Option(
        None,
        "--experiment-dir",
        help="Simulation output directory to resume; needs --resume",
    ),
    langfuse_timeout: int = typer.Option(
        90,
        "--langfuse-timeout",
        help="Seconds to wait for each trial's Langfuse traces to be ready",
    ),
    verbose: int = typer.Option(
        0, "--verbose", "-v", count=True, help="Increase logging verbosity"
    ),
    quiet: bool = typer.Option(
        False, "--quiet", help="Suppress output below ERROR level"
    ),
    no_tui: bool = typer.Option(
        False, "--no-tui", help="Disable TUI even in a terminal"
    ),
    log_format: Literal["text", "json"] = typer.Option(
        "text", "--log-format", help="Log file format: text or json"
    ),
    log_dir: Path | None = typer.Option(
        None,
        "--log-dir",
        help="Override log directory (default: co-located with results)",
    ),
    concurrency: int = typer.Option(
        1,
        "--concurrency",
        "-c",
        min=1,
        help="Max concurrent trials, then max concurrent sessions when grading",
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        help="Continue the output named by --experiment-dir instead of starting a run",
    ),
    project_dir: ProjectDirOption = None,
) -> None:
    """Run simulation followed by evaluation."""
    trace_wait = _trace_wait_settings(langfuse_timeout)
    output_dir = _run_simulation(
        input_dir,
        experiment_dir,
        command="run",
        verbose=verbose,
        quiet=quiet,
        no_tui=no_tui,
        log_format=log_format,
        log_dir=log_dir,
        concurrency=concurrency,
        resume=resume,
        project_dir=project_dir,
    )

    try:
        outcome = _run_evaluation_command(
            output_dir,
            trace_wait=trace_wait,
            verbose=verbose,
            quiet=quiet,
            concurrency=concurrency,
            command="run",
            resume=resume,
        )
    except Exception:
        _print_handoff(output_dir, command="run")
        raise

    _print_evaluation_summary(output_dir, outcome, pipeline=True)
