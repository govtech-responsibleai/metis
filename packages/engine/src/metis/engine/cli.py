"""Command-line interface for metis-engine."""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import signal
import sys
import threading
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import typer
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TaskID, TextColumn

from metis.core import execution_layout
from metis.core.console import console
from metis.engine import __version__
from metis.engine.logging import (
    EvaluationLogger,
    OrchestrationLogger,
    setup_engine_logging,
    teardown_engine_logging,
)
from metis.engine.tracing import tracing_key, trial_session_id
from metis.engine.tui import (
    SimulationScenarioState,
    SimulationState,
    SimulationTrialState,
    TailBuffer,
    TUIContext,
)

if TYPE_CHECKING:
    import types as _types

    from metis.core.model_settings import ModelRole
    from metis.core.reporting import GraderRecord
    from metis.core.traces import Trace
    from metis.core.trials import TrialRecord
    from metis.engine.simulation.experiment import TrialPlanItem
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


def _find_project_root() -> Path:
    """Walk up from CWD to find pyproject.toml."""
    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    return current


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
    """Validate all experiment inputs upfront before simulation.

    Fails fast on the first error with a clear message and sys.exit(1).
    """
    from pydantic import ValidationError

    from metis.engine.simulation.types import Specification

    if not input_dir.is_dir():
        console.print(
            f"Error: input directory '{input_dir}' does not exist", style="bold red"
        )
        sys.exit(1)

    experiment_path = input_dir / "specification.yaml"
    if not experiment_path.exists():
        console.print(
            f"Error: missing required file 'specification.yaml' in {input_dir}",
            style="bold red",
        )
        sys.exit(1)

    try:
        specification = Specification.load_file(experiment_path)
    except ValidationError as e:
        first = e.errors()[0]
        loc = " → ".join(str(part) for part in first["loc"]) if first["loc"] else "root"
        console.print(
            f"Error: specification.yaml validation failed: {loc} — {first['msg']}",
            style="bold red",
        )
        sys.exit(1)
    except Exception as e:
        console.print(
            f"Error: failed to parse specification.yaml: {e}", style="bold red"
        )
        sys.exit(1)

    seen_personas: set[str] = set()
    for persona in specification.personas:
        if persona.id in seen_personas:
            console.print(
                f"Error: duplicate persona id '{persona.id}' in specification.yaml",
                style="bold red",
            )
            sys.exit(1)
        seen_personas.add(persona.id)

    fixtures_dir = input_dir / "fixtures"
    for task in specification.resolved_tasks():
        for fixture in task.fixtures:
            if not (fixtures_dir / fixture).exists():
                console.print(
                    f"Error: Task '{task.task_id}' references fixture '{fixture}' which does not exist in {fixtures_dir}",
                    style="bold red",
                )
                sys.exit(1)

    # Print every bad criterion before exiting, so one run lists everything to fix.
    errors = _grader_setup_errors(specification)
    for message in errors:
        # markup=False: pydantic messages contain "[...]"; soft_wrap: keep each error on one
        # line so it can be grepped from logs.
        console.print(
            f"Error: {message}", style="bold red", markup=False, soft_wrap=True
        )
    if errors:
        sys.exit(1)


def _grader_setup_errors(specification: Specification) -> list[str]:
    """Every criterion whose grader can't be built from the spec alone, as messages.

    Each criterion is checked once, however many tasks reference it. The judge model is
    resolved exactly as the run will resolve it, so a JudgeArgs grader validates with a model
    in place. ``check_setup`` runs after its args validate. No client or credentials are
    needed: the gateway is checked separately, at the start of ``evaluate``.
    """
    from metis.engine.evaluation import GraderSetupError, build_grader

    errors: list[str] = []
    criteria_by_id = {c.id: c for b in specification.behaviours() for c in b.criteria}
    checked: set[str] = set()
    default_judge_model = specification.experiment.defaults.judge_model
    for scenario in specification.resolved_tasks():
        for ref in scenario.grader_refs:
            if ref.criterion_id in checked:
                continue
            checked.add(ref.criterion_id)
            try:
                built = build_grader(
                    criteria_by_id[ref.criterion_id],
                    default_judge_model=default_judge_model,
                    env=os.environ,
                )
            except GraderSetupError as exc:
                errors.append(str(exc))
                continue
            try:
                problems = type(built).check_setup(built.args, specification)
            except Exception as exc:  # a grader bug must not crash validation
                problems = [f"check_setup raised {type(exc).__name__}: {exc}"]
            errors.extend(f"Criterion '{ref.criterion_id}': {p}" for p in problems)
    return errors


def _format_final_summary(
    state: SimulationState, experiment_dir: str, log_dir: str
) -> str:
    """Build the static final summary printed after TUI exits."""
    total = state.total_trials
    completed = state.completed_trials
    reasons = [t.stop_reason for sc in state.scenarios for t in sc.trials]
    achieved = sum(1 for r in reasons if r == "goal_achieved")
    abandoned = sum(1 for r in reasons if r == "user_abandoned")
    timed_out = sum(1 for r in reasons if r == "timeout")
    # Remaining completed trials (e.g. system_error, max_turns) count as errors.
    errored = completed - achieved - abandoned - timed_out

    elapsed = state.elapsed_seconds
    h = int(elapsed) // 3600
    m = (int(elapsed) % 3600) // 60

    elapsed_str = f"{h}h {m:02d}m" if h > 0 else f"{m}m"

    lines = [
        f"METIS {state.experiment_id} — completed in {elapsed_str}",
        f"Simulation: {completed}/{total} trials "
        f"({achieved} goal achieved, {abandoned} abandoned, "
        f"{timed_out} timeout, {errored} error)",
        f"Logs:   {log_dir}/",
    ]
    return "\n".join(lines)


@dataclass(frozen=True)
class EvaluationOutcome:
    """Summary returned by the evaluation phase."""

    total_records: int
    successful_records: int
    failed_records: int
    results_file: Path | None


class EvaluationInputError(RuntimeError):
    """Raised when an experiment snapshot or run record is invalid."""


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
    return sorted(
        (experiment_dir / execution_layout.TRIALS).glob(
            f"*/{execution_layout.TRIAL_RECORD}"
        ),
        key=lambda path: path.stat().st_mtime,
    )


def _experiment_id(input_dir: Path) -> str | None:
    """Return the experiment id in ``input_dir``, or None if it cannot be read."""
    from metis.engine.simulation.types import Specification

    try:
        return Specification.load_file(input_dir.resolve() / "specification.yaml").id
    except Exception:
        return None


def _existing_outputs(input_dir: Path) -> list[Path]:
    experiment_id = _experiment_id(input_dir)
    if experiment_id is None:
        return []
    experiments_root = _find_project_root() / execution_layout.EXECUTIONS
    if not experiments_root.is_dir():
        return []
    pattern = re.compile(rf"^{re.escape(experiment_id)}-\d{{8}}-\d{{6}}$")
    return sorted(
        candidate.resolve()
        for candidate in experiments_root.iterdir()
        if candidate.is_dir() and pattern.fullmatch(candidate.name)
    )


def _print_resume_flag_error(input_dir: Path, command: str) -> None:
    """Report that ``--resume`` needs ``--experiment-dir``, and list candidates."""
    experiment_id = _experiment_id(input_dir)
    outputs = _existing_outputs(input_dir)

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
            _print_resume_flag_error(input_dir, command)
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
    resolved = experiment_dir.resolve()
    if not resolved.is_dir():
        console.print(
            f"Error: experiment directory '{resolved}' does not exist",
            style="bold red",
        )
        raise EvaluationInputError("invalid experiment directory")
    if not (resolved / execution_layout.INPUTS).is_dir():
        console.print(
            f"Error: '{resolved}' is not a simulation output directory "
            "(no 'inputs/' snapshot). Run 'metis engine simulate' first.",
            style="bold red",
        )
        raise EvaluationInputError("invalid experiment directory")
    if (resolved / "trials").is_dir() or (resolved / "reports").is_dir():
        console.print(
            "Error: this execution uses an earlier folder layout. "
            "Move it to outputs/trials/ and outputs/reports/ before use.",
            style="bold red",
        )
        raise EvaluationInputError("unsupported execution layout")
    return resolved


def _evaluate_command(experiment_dir: Path) -> str:
    """Build the shell-safe command for evaluating a simulation output."""
    return shlex.join(
        ["metis", "engine", "evaluate", "--experiment-dir", str(experiment_dir)]
    )


def _resume_command(experiment_dir: Path, command: str) -> str:
    """Build the shell-safe command for resuming a simulation output."""
    return shlex.join(
        [
            "metis",
            "engine",
            command,
            "--resume",
            "--experiment-dir",
            str(experiment_dir),
        ]
    )


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
    console.print(f"{'=' * 60}")


def _classify_resume_trials(
    experiment_dir: Path,
    trial_plan: list[TrialPlanItem],
) -> tuple[list[TrialPlanItem], dict[tuple[str, str, int], TrialRecord]]:
    """Return redo items and valid existing records keyed by plan identity."""
    from metis.core.trials import TrialRecord
    from metis.engine.simulation.experiment import trial_folder_name

    redo: list[TrialPlanItem] = []
    completed: dict[tuple[str, str, int], TrialRecord] = {}
    for item in trial_plan:
        scenario, persona, trial_index = item
        record_path = (
            experiment_dir
            / execution_layout.TRIALS
            / trial_folder_name(scenario, persona, trial_index)
            / execution_layout.TRIAL_RECORD
        )
        try:
            record = TrialRecord.load_file(record_path)
        except Exception:
            redo.append(item)
            continue
        key = (scenario.task_id or scenario.id, persona.id, trial_index)
        if record.outcome.stop_reason == "system_error":
            redo.append(item)
        else:
            completed[key] = record
    return redo, completed


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
) -> Path:
    """Run simulation and return its experiment directory."""
    target = _resolve_simulation_target(
        input_dir, experiment_dir, resume=resume, command=command
    )
    env_file = _load_env()
    tracing_key()
    use_tui = not no_tui and sys.stderr.isatty()
    log_level = _resolve_log_level(verbose, quiet)

    # Configure logging before importing harness modules. They create
    # module-level loggers that cache the processor chain.
    _configure_process_logging(log_level, use_tui=use_tui)

    from metis.engine.simulation.experiment import (
        execute_experiment,
        expand_trial_plan,
    )
    from metis.engine.simulation.types import Specification

    project_root = _find_project_root()

    if resume:
        experiment_dir = target
        specification = Specification.load_file(
            experiment_dir / execution_layout.SPECIFICATION
        )
        _check_simulation_settings(command, specification, env_file)
        fixtures_dir = experiment_dir / execution_layout.FIXTURES
    else:
        _validate_inputs(target)
        specification = Specification.load_file(target / "specification.yaml")
        _check_simulation_settings(command, specification, env_file)
        suffix = datetime.now().strftime("%Y%m%d-%H%M%S")
        experiment_dir = (
            project_root / execution_layout.EXECUTIONS / f"{specification.id}-{suffix}"
        )
        experiment_dir.mkdir(parents=True)
        shutil.copytree(target, experiment_dir / execution_layout.INPUTS)
        fixtures_dir = experiment_dir / execution_layout.FIXTURES

    personas_by_id = {persona.id: persona for persona in specification.personas}
    trial_plan = expand_trial_plan(specification, personas_by_id)
    if resume:
        redo_plan, completed_records = _classify_resume_trials(
            experiment_dir, trial_plan
        )
        console.print(
            f"Resume plan: {experiment_dir} — {len(redo_plan)} trials to redo, "
            f"{len(completed_records)} already complete"
        )
        if not redo_plan:
            console.print("nothing to resume")
            return experiment_dir
    else:
        redo_plan = trial_plan
        completed_records = {}

    from metis.engine.simulation.binding import TargetBindingError
    from metis.engine.simulation.runner_resolver import resolve_runner_factory

    factory_cls = resolve_runner_factory(specification.runner_factory_ref)

    # a factory that needs the specification asks for it; any other is built bare
    from_specification = getattr(factory_cls, "from_specification", None)
    try:
        runner_factory = (
            from_specification(specification, experiment_dir / execution_layout.INPUTS)
            if from_specification is not None
            else factory_cls()
        )
    except TargetBindingError as exc:
        # the message holds text the user wrote, so it must not be read as markup
        console.print(f"Error: {exc}", style="bold red", markup=False)
        raise typer.Exit(code=1) from None

    trial_max_retries, trial_retry_delay_seconds = runner_factory.retry_defaults

    console.print(f"\n{'=' * 60}")
    console.print("  SIMULATION")
    console.print(f"{'=' * 60}")
    console.print(f"  Specification: {experiment_dir}")
    console.print(f"  Input: {fixtures_dir.parent}\n")

    resolved_log_dir = log_dir or (experiment_dir / execution_layout.LOGS)
    resolved_log_dir.mkdir(parents=True, exist_ok=True)

    scenarios_state: list[SimulationScenarioState] = []
    total_trial_count = 0
    for scenario in specification.resolved_tasks():
        trial_states: list[SimulationTrialState] = []
        for persona_ref in scenario.persona_refs:
            for trial_index in range(1, scenario.num_trials + 1):
                total_trial_count += 1
                trial_states.append(
                    SimulationTrialState(
                        scenario_id=scenario.task_id or scenario.id,
                        persona_id=persona_ref,
                        trial_index=trial_index,
                        num_trials=scenario.num_trials,
                        phase="pending",
                        current_turn=None,
                        max_turns=scenario.max_turns,
                        turn_detail="",
                        duration_seconds=None,
                        stop_reason=None,
                    )
                )
        scenarios_state.append(
            SimulationScenarioState(
                scenario_id=scenario.task_id or scenario.id,
                trials=trial_states,
                phase="pending",
            )
        )

    sim_state = SimulationState(
        experiment_id=specification.id,
        scenarios=scenarios_state,
        total_trials=total_trial_count,
    )

    for (scenario_id, persona_id, trial_index), record in completed_records.items():
        sim_state.mark_trial_completed(
            scenario_id,
            persona_id,
            trial_index=trial_index,
            stop_reason=record.outcome.stop_reason,
            duration_seconds=record.outcome.duration_seconds,
        )

    display_level = getattr(logging, log_level)
    tail_buffers = {
        f"w{i}": TailBuffer(max_lines=15, min_level=display_level)
        for i in range(concurrency)
    }
    log_router = setup_engine_logging(
        log_dir=resolved_log_dir,
        log_format=log_format,
        tail_buffers=tail_buffers,
        use_tui=use_tui,
        append=resume,
    )
    orchestration_logger = OrchestrationLogger(
        log_dir=resolved_log_dir, log_format=log_format, append=resume
    )
    if resume:
        orchestration_logger.resume_started(len(redo_plan), len(completed_records))

    tui_ctx: TUIContext | None = None
    if use_tui:
        tui_ctx = TUIContext(state=sim_state, tail_buffers=tail_buffers)

    interrupt_count = 0
    interrupt_lock = threading.Lock()
    shutdown_event = threading.Event()

    def _handle_sigint(_signum: int, _frame: _types.FrameType | None) -> None:
        nonlocal interrupt_count
        with interrupt_lock:
            interrupt_count += 1
            if interrupt_count >= 2:
                if not use_tui:
                    console.print("\nForce abort.", style="bold red")
                sys.exit(130)
            shutdown_event.set()
            if not use_tui:
                console.print(
                    "\nInterrupt received — finishing current trial. "
                    "No new trials will start. Press Ctrl+C again to force abort.",
                    style="yellow",
                )

    prev_handler = signal.signal(signal.SIGINT, _handle_sigint)
    try:
        with tui_ctx if tui_ctx else nullcontext():
            execute_experiment(
                runner_factory=runner_factory,
                specification=specification,
                personas_by_id=personas_by_id,
                output_dir=experiment_dir,
                fixtures_dir=fixtures_dir,
                concurrency=concurrency,
                trial_plan=redo_plan,
                trial_max_retries=trial_max_retries,
                trial_retry_delay_seconds=trial_retry_delay_seconds,
                state=sim_state,
                orchestration_logger=orchestration_logger,
                log_router=log_router,
                tui_ctx=tui_ctx,
                shutdown_event=shutdown_event,
            )
    finally:
        signal.signal(signal.SIGINT, prev_handler)
        teardown_engine_logging(log_router)
        orchestration_logger.close()

    console.print(
        _format_final_summary(
            sim_state,
            str(experiment_dir),
            str(resolved_log_dir),
        )
    )
    if shutdown_event.is_set():
        raise typer.Exit(code=130)
    return experiment_dir


def _load_evaluation_specification(experiment_dir: Path) -> Specification:
    """Validate and load the frozen experiment snapshot."""
    from metis.engine.simulation.types import Specification

    inputs_dir = experiment_dir / execution_layout.INPUTS
    if not inputs_dir.is_dir():
        console.print(
            f"Error: missing required file 'specification.yaml' in {inputs_dir}",
            style="bold red",
        )
        raise EvaluationInputError("missing experiment snapshot")

    try:
        _validate_inputs(inputs_dir)
    except SystemExit as exc:
        raise EvaluationInputError(
            f"invalid experiment snapshot in {inputs_dir}"
        ) from exc

    try:
        return Specification.load_file(inputs_dir / "specification.yaml")
    except Exception as exc:
        console.print(
            f"Error: failed to load experiment snapshot: {exc}", style="bold red"
        )
        raise EvaluationInputError("failed to load experiment snapshot") from exc


def _create_evaluation_progress() -> Progress:
    """Create the standard, non-full-screen evaluation progress bar."""
    return Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
    )


def _update_evaluation_progress(
    progress: Progress | None,
    task_id: TaskID | None,
    *,
    record_number: int,
    total_records: int,
    label: str,
    phase: str,
    advance: int = 0,
) -> None:
    """Update the progress bar or print one linear progress message."""
    description = f"{label} — {phase}"
    if progress and task_id is not None:
        progress.update(task_id, description=description, advance=advance)
    else:
        console.print(f"Evaluation {record_number}/{total_records}: {description}")


def _log_grader_records(
    evaluation_log: EvaluationLogger,
    records: list[GraderRecord],
    *,
    record_label: str,
) -> None:
    """Write every recorded result of one trial's grader runs to the evaluation log."""
    count = 0
    for record in records:
        for index, result in enumerate(record.results):
            evaluation_log.write(
                "GRADER RESULT — "
                + json.dumps(
                    {
                        "record": record_label,
                        "criterion_id": record.criterion_id,
                        "grader": record.grader_fqn,
                        "result": index,
                        "outcome": result.outcome,
                        "score": result.score,
                        "reason": result.reason,
                    },
                    ensure_ascii=False,
                    default=str,
                )
            )
            count += 1
    evaluation_log.write(f"GRADER RESULTS — record={record_label} count={count}")


def _save_session_traces(
    experiment_dir: Path,
    session_id: str,
    traces: tuple[Trace, ...],
    evaluation_log: EvaluationLogger,
) -> None:
    """Save one session's traces for `metis insights report`; a failed write only warns.

    The file is display data, so grading must never depend on it. A payload JSON cannot
    encode (a lone surrogate, say) raises ``ValueError``, so that is caught as well as ``OSError``.
    """
    from metis.core import SessionTraces

    path = (
        experiment_dir
        / execution_layout.TRACES
        / execution_layout.trace_file_name(session_id)
    )
    try:
        SessionTraces.from_traces(session_id, traces).save(path)
    except (OSError, ValueError) as exc:
        console.print(
            f"  WARNING: traces for session {session_id} were not saved: {exc}",
            style="yellow",
            markup=False,
        )
        evaluation_log.write(f"TRACES NOT SAVED — session={session_id} — {exc}")


def _run_evaluation(
    experiment_dir: Path,
    *,
    langfuse_timeout: int,
    verbose: int,
    quiet: bool,
) -> EvaluationOutcome:
    """Evaluate records in an existing experiment directory."""
    env_file = _load_env()
    # Registered before the target's Langfuse client, so judge calls always have their own.
    tracing_key()
    log_level = _resolve_log_level(verbose, quiet)
    _configure_process_logging(log_level)
    evaluation_log = EvaluationLogger(experiment_dir / execution_layout.LOGS)
    evaluation_log.write(f"EVALUATION STARTED — {experiment_dir}")

    import asyncio

    from metis.core.trials import TrialRecord

    specification = _load_evaluation_specification(experiment_dir)
    files = _trial_record_files(experiment_dir)
    if not files:
        evaluation_log.write("EVALUATION COMPLETED — 0 records")
        return EvaluationOutcome(0, 0, 0, None)

    try:
        records: list[TrialRecord] = [TrialRecord.load_file(path) for path in files]
    except Exception as exc:
        console.print(f"Error: failed to load trial record: {exc}", style="bold red")
        raise EvaluationInputError("failed to load trial record") from exc

    console.print(f"  Loaded {len(records)} trial record(s)")
    evaluation_log.write(f"LOADED {len(records)} trial record(s)")
    return asyncio.run(
        _evaluate_records(
            experiment_dir,
            specification,
            records,
            evaluation_log=evaluation_log,
            langfuse_timeout=langfuse_timeout,
            env_file=env_file,
        )
    )


async def _evaluate_records(
    experiment_dir: Path,
    specification: Specification,
    records: list[TrialRecord],
    *,
    evaluation_log: EvaluationLogger,
    langfuse_timeout: int,
    env_file: Path | None = None,
) -> EvaluationOutcome:
    """Grade every trial record's session and write one GraderRecord per grader per session.

    Graders are built once per criterion from the specification snapshot.
    A criterion graded in many trials shares one grader. One judge client
    is opened for the whole evaluation, and only when some criterion's grader needs one.
    """
    import asyncio
    import time

    from metis.core.reporting import EvaluationResults
    from metis.engine import extractor
    from metis.engine.evaluation import (
        JudgeGateway,
        SessionFacts,
        build_grader,
        build_llm_settings,
        grade_session,
    )
    from metis.library.grader import Grader, JudgeArgs, LLMSettings

    default_judge_model = specification.experiment.defaults.judge_model
    criteria_by_id = {c.id: c for b in specification.behaviours() for c in b.criteria}
    graders: dict[str, Grader[Any]] = {}
    for scenario in specification.resolved_tasks():
        for ref in scenario.grader_refs:
            if ref.criterion_id not in graders:
                graders[ref.criterion_id] = build_grader(
                    criteria_by_id[ref.criterion_id],
                    default_judge_model=default_judge_model,
                    env=os.environ,
                )

    gateway = JudgeGateway.from_env(os.environ)
    needs_llm = sorted(
        cid for cid, g in graders.items() if isinstance(g.args, JudgeArgs)
    )
    if needs_llm and gateway is None:
        from metis.core.model_settings import (
            ModelRole,
            format_missing_settings,
            missing_settings,
        )

        console.print(
            "Error: criteria "
            + ", ".join(needs_llm)
            + " use a model-based grader.\n"
            + format_missing_settings(
                "metis engine evaluate",
                missing_settings([ModelRole.JUDGE], os.environ),
                env_file,
            ),
            style="bold red",
            markup=False,
        )
        raise EvaluationInputError("no judge API key for model-based graders")
    if needs_llm:
        # The graders hold their resolved model, so this names exactly what will run.
        judge_models = sorted(
            {g.args.model for g in graders.values() if isinstance(g.args, JudgeArgs)}
        )
        console.print(f"Models: Judge {', '.join(judge_models)}", markup=False)
    llm = (
        build_llm_settings(gateway)
        if gateway is not None and needs_llm
        else LLMSettings(client=_NoJudgeClient())  # type: ignore[arg-type]
    )

    # Traces saved by an earlier evaluation must not outlive it, or the report would show a
    # conversation that differs from the grades beside it.
    shutil.rmtree(experiment_dir / execution_layout.TRACES, ignore_errors=True)
    langfuse = extractor.get_langfuse_client()
    all_records: list[GraderRecord] = []
    successful = 0
    failed = 0
    started = time.monotonic()
    interactive_progress = sys.stderr.isatty()
    progress = _create_evaluation_progress() if interactive_progress else None

    try:
        with progress if progress else nullcontext():
            task_id = (
                progress.add_task("Evaluation", total=len(records))
                if progress
                else None
            )
            for index, record in enumerate(records):
                label = f"{record.config.persona} x {record.config.scenario}"
                failure_reason: str | None = None
                warning: str | None = None

                def phase(
                    name: str,
                    *,
                    advance: int = 0,
                    _number: int = index + 1,
                    _label: str = label,
                ) -> None:
                    _update_evaluation_progress(
                        progress,
                        task_id,
                        record_number=_number,
                        total_records=len(records),
                        label=_label,
                        phase=name,
                        advance=advance,
                    )

                evaluation_log.write(
                    f"RECORD {index + 1}/{len(records)} {label} — EXTRACTING"
                )
                phase("extracting")
                console.print(f"\n\n{'#' * 60}")
                console.print(f"  SESSION {index + 1}/{len(records)}: {label}")
                console.print(f"{'#' * 60}")

                session_id = record.target_session_id
                criteria = [
                    criteria_by_id[ref.criterion_id]
                    for ref in record.config.grader_refs
                    if ref.criterion_id in graders
                ]
                unknown = sorted(
                    ref.criterion_id
                    for ref in record.config.grader_refs
                    if ref.criterion_id not in graders
                )
                if unknown:
                    # The record was written against a spec whose criteria differ from the
                    # snapshot (e.g. inputs/specification.yaml was edited). Say so rather
                    # than silently grading fewer criteria than the trial ran for.
                    console.print(
                        f"  WARNING: criteria {', '.join(unknown)} are not in the "
                        "specification snapshot and were not graded",
                        style="yellow",
                        markup=False,
                    )
                    evaluation_log.write(
                        f"RECORD {index + 1}/{len(records)} {label} — "
                        f"UNKNOWN CRITERIA — {', '.join(unknown)}"
                    )
                try:
                    if not session_id:
                        failure_reason = "No target_session_id"
                    elif not criteria:
                        failure_reason = "No grader_refs in run config"
                    else:
                        grading_input = await asyncio.to_thread(
                            extractor.fetch_session,
                            session_id,
                            langfuse,
                            experiment_root=experiment_dir,
                            artifacts=record.artifacts,
                            retry_timeout=langfuse_timeout,
                        )
                        if not grading_input.traces:
                            failure_reason = "No traces found in Langfuse"
                        else:
                            _save_session_traces(
                                experiment_dir,
                                session_id,
                                grading_input.traces,
                                evaluation_log,
                            )
                            evaluation_log.write(
                                f"RECORD {index + 1}/{len(records)} {label} — EVALUATING"
                            )
                            for criterion in criteria:
                                evaluation_log.write(
                                    "GRADER CONFIG — "
                                    + json.dumps(
                                        {
                                            "record": label,
                                            "criterion_id": criterion.id,
                                            "fqn": criterion.grader_fqn,
                                            "args": graders[
                                                criterion.id
                                            ].args.model_dump(mode="json"),
                                        },
                                        ensure_ascii=False,
                                        sort_keys=True,
                                    )
                                )
                            phase("evaluating")
                            session_records = await grade_session(
                                criteria,
                                graders,
                                grading_input,
                                llm,
                                SessionFacts(
                                    session_id=session_id,
                                    scenario_id=record.config.scenario,
                                    task_id=record.config.task_id,
                                    trial_index=record.config.trial_index,
                                    trace_session_id=trial_session_id(
                                        experiment_dir.resolve().name, record.config
                                    ),
                                ),
                            )
                            all_records.extend(session_records)
                            _log_grader_records(
                                evaluation_log, session_records, record_label=label
                            )
                except Exception as exc:
                    failure_reason = str(exc)
                    warning = f"Evaluation failed: {exc}"

                if failure_reason is None:
                    successful += 1
                    evaluation_log.write(
                        f"RECORD {index + 1}/{len(records)} {label} — DONE"
                    )
                    phase("done", advance=1)
                else:
                    failed += 1
                    console.print(
                        f"  WARNING: {warning or failure_reason}",
                        style="yellow",
                        markup=False,
                    )
                    evaluation_log.write(
                        f"RECORD {index + 1}/{len(records)} {label} — FAILED — {failure_reason}"
                    )
                    phase("failed", advance=1)

            if progress and task_id is not None:
                progress.update(task_id, description="Evaluation complete")
    finally:
        if gateway is not None and needs_llm:
            await llm.client.close()

    # An evaluation that scores nothing must not leave the previous evaluation's
    # results behind for `metis insights report` to pick up as current.
    results_path = experiment_dir / execution_layout.RESULTS
    results_path.unlink(missing_ok=True)
    results_file: Path | None = None
    if all_records:
        elapsed = round(time.monotonic() - started, 1)
        EvaluationResults(
            run_id="report",
            records=all_records,
            timings={"evaluation_seconds": elapsed},
            latency_seconds=elapsed or None,
        ).save(results_path)
        results_file = results_path
        evaluation_log.write(f"RESULTS WRITTEN — {results_file}")

    outcome = EvaluationOutcome(
        total_records=len(records),
        successful_records=successful,
        failed_records=failed,
        results_file=results_file,
    )
    evaluation_log.write(
        "EVALUATION COMPLETED — "
        f"{outcome.successful_records}/{outcome.total_records} records succeeded, "
        f"{outcome.failed_records} failed"
    )
    return outcome


class _NoJudgeClient:
    """Stands in for the judge client when no criterion's grader makes grader LLM calls.

    Code-based graders never touch ``llm.client``, so building a real client would demand
    credentials the run doesn't need. Any attribute access fails loudly, which turns a grader
    that wrongly calls the client without extending ``JudgeArgs`` into an errored result.
    """

    def __getattr__(self, name: str) -> object:
        raise RuntimeError(
            "this grader made a grader LLM call, but its args do not extend JudgeArgs, "
            "so no judge client was configured"
        )


def _run_evaluation_command(
    experiment_dir: Path,
    *,
    langfuse_timeout: int,
    verbose: int,
    quiet: bool,
) -> EvaluationOutcome:
    """Run evaluation and convert expected input errors to a CLI exit."""
    try:
        return _run_evaluation(
            experiment_dir,
            langfuse_timeout=langfuse_timeout,
            verbose=verbose,
            quiet=quiet,
        )
    except EvaluationInputError as exc:
        EvaluationLogger(experiment_dir / execution_layout.LOGS, reset=False).write(
            f"EVALUATION FAILED — {exc}"
        )
        raise typer.Exit(code=1) from None
    except Exception as exc:
        EvaluationLogger(experiment_dir / execution_layout.LOGS, reset=False).write(
            f"EVALUATION FAILED — {exc}"
        )
        console.print(f"Error: evaluation failed: {exc}", style="bold red")
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
        1, "--concurrency", "-c", help="Max parallel simulation workers"
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        help="Continue the output named by --experiment-dir instead of starting a run",
    ),
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
    )
    if not _trial_record_files(output_dir):
        console.print("No trial records found.", style="bold red")
        raise typer.Exit(code=1)
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
        90, "--langfuse-timeout", help="Seconds to wait for Langfuse traces"
    ),
    verbose: int = typer.Option(
        0, "--verbose", "-v", count=True, help="Increase logging verbosity"
    ),
    quiet: bool = typer.Option(
        False, "--quiet", help="Suppress output below ERROR level"
    ),
) -> None:
    """Evaluate one simulation output directory."""
    try:
        resolved_experiment_dir = _resolve_experiment_dir(experiment_dir)
    except EvaluationInputError:
        raise typer.Exit(code=1) from None
    console.print(f"Selected experiment: {resolved_experiment_dir}")
    outcome = _run_evaluation_command(
        resolved_experiment_dir,
        langfuse_timeout=langfuse_timeout,
        verbose=verbose,
        quiet=quiet,
    )
    if outcome.total_records == 0:
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
        90, "--langfuse-timeout", help="Seconds to wait for Langfuse traces"
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
        1, "--concurrency", "-c", help="Max parallel simulation workers"
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        help="Continue the output named by --experiment-dir instead of starting a run",
    ),
) -> None:
    """Run simulation followed by evaluation."""
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
    )
    if not _trial_record_files(output_dir):
        console.print("No trial records found.", style="bold red")
        raise typer.Exit(code=1)

    try:
        outcome = _run_evaluation_command(
            output_dir,
            langfuse_timeout=langfuse_timeout,
            verbose=verbose,
            quiet=quiet,
        )
    except Exception:
        _print_handoff(output_dir, command="run")
        raise

    if outcome.failed_records:
        _print_handoff(output_dir, command="run")
    _print_evaluation_summary(output_dir, outcome, pipeline=True)
