"""Simulate the trials of an experiment folder."""

from __future__ import annotations

import logging
from contextlib import nullcontext
from typing import TYPE_CHECKING, Literal

from metis.core import execution_layout
from metis.core.phase_events import PhaseEventLog
from metis.engine.logging import (
    OrchestrationLogger,
    setup_engine_logging,
    teardown_engine_logging,
)
from metis.engine.runs._common import (
    clear_evaluation_outputs,
    end_phase_on_error,
    trial_record_files,
)
from metis.engine.runs.errors import RunError, RunStopped
from metis.engine.tui import (
    SimulationScenarioState,
    SimulationState,
    SimulationTrialState,
    TailBuffer,
    TUIContext,
)

if TYPE_CHECKING:
    import threading
    from pathlib import Path

    from rich.console import Console

    from metis.core.trials import TrialRecord
    from metis.engine.simulation.experiment import TrialPlanItem
    from metis.engine.simulation.types import Specification


def simulate(
    experiment_dir: Path,
    *,
    concurrency: int,
    stop: threading.Event,
    console: Console,
    use_tui: bool = False,
    log_level: str = "WARNING",
    log_format: Literal["text", "json"] = "text",
    log_dir: Path | None = None,
) -> Path:
    """Run every trial of an experiment folder that ``prepare_experiment`` made.

    It writes the ``simulating`` lines of ``logs/events.jsonl``: ``started``, then
    ``completed``, ``failed`` or ``interrupted``. When ``stop`` is set, each trial in flight
    ends at its next turn and is recorded as ``interrupted``, and no new trial starts.

    ``use_tui`` shows the full-screen dashboard on the terminal, for the CLI only.
    ``log_level`` is the lowest level that its log tail shows.

    The caller sets up the process first: it loads ``.env``, calls
    ``metis.engine.tracing.tracing_key()``, and sets up process logging. Only one run at a
    time is safe in one process.

    :raises RunStopped: When ``stop`` was set. A stop before the trials start runs none.
    :raises RunError: When the runner cannot be built, or no trial record was written.
    """
    return _simulate(
        experiment_dir,
        resume=False,
        concurrency=concurrency,
        stop=stop,
        console=console,
        use_tui=use_tui,
        log_level=log_level,
        log_format=log_format,
        log_dir=log_dir,
    )


def resume_simulation(
    experiment_dir: Path,
    *,
    concurrency: int,
    stop: threading.Event,
    console: Console,
    use_tui: bool = False,
    log_level: str = "WARNING",
    log_format: Literal["text", "json"] = "text",
    log_dir: Path | None = None,
) -> Path:
    """Run again the trials of an experiment folder that did not end, as ``simulate`` does.

    A trial runs again only when its record is missing, cannot be read, or has stop reason
    ``interrupted``. When it runs any trial, it removes the evaluation outputs first, so a
    trial is never graded from the evaluation of its old run. The logs are appended to.
    A stop before the trials start leaves the folder as it is.

    The caller sets up the process first, and only one run at a time is safe in one
    process, as for ``simulate``.

    :raises RunStopped: When ``stop`` was set while trials ran.
    :raises RunError: When the runner cannot be built, or no trial record exists.
    """
    return _simulate(
        experiment_dir,
        resume=True,
        concurrency=concurrency,
        stop=stop,
        console=console,
        use_tui=use_tui,
        log_level=log_level,
        log_format=log_format,
        log_dir=log_dir,
    )


def _simulate(
    experiment_dir: Path,
    *,
    resume: bool,
    concurrency: int,
    stop: threading.Event,
    console: Console,
    use_tui: bool,
    log_level: str,
    log_format: Literal["text", "json"],
    log_dir: Path | None,
) -> Path:
    from metis.engine.simulation.types import Specification

    specification = Specification.load_file(
        experiment_dir / execution_layout.SPECIFICATION
    )
    events = PhaseEventLog.for_experiment_dir(experiment_dir)
    try:
        _simulate_in(
            experiment_dir,
            specification,
            experiment_dir / execution_layout.FIXTURES,
            events,
            resume=resume,
            concurrency=concurrency,
            stop=stop,
            console=console,
            use_tui=use_tui,
            log_level=log_level,
            log_format=log_format,
            log_dir=log_dir,
        )
        if not trial_record_files(experiment_dir):
            console.print("No trial records found.", style="bold red")
            raise RunError("No trial records found.")
    except BaseException as exc:
        end_phase_on_error(events, "simulating", exc)
        raise
    events.emit("simulating", "completed")
    return experiment_dir


def _classify_resume_trials(
    experiment_dir: Path,
    trial_plan: list[TrialPlanItem],
) -> tuple[list[TrialPlanItem], dict[tuple[str, str, int], TrialRecord]]:
    """Return redo items and valid existing records keyed by plan identity.

    A trial is redone only when it did not end: its record is missing, unreadable,
    or not valid, or its stop reason is ``interrupted``. A trial that ended is
    complete whatever its result, so a ``system_error`` trial, which ended after its
    retry limit, is not run again. To run failed trials again, start a new run.
    """
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
        if record.outcome.stop_reason == "interrupted":
            redo.append(item)
        else:
            completed[key] = record
    return redo, completed


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


def _simulate_in(
    experiment_dir: Path,
    specification: Specification,
    fixtures_dir: Path,
    events: PhaseEventLog,
    *,
    resume: bool,
    concurrency: int,
    stop: threading.Event,
    console: Console,
    use_tui: bool,
    log_level: str,
    log_format: Literal["text", "json"],
    log_dir: Path | None,
) -> Path:
    """Simulate the trials in ``experiment_dir`` that still need a record."""
    from metis.engine.simulation.experiment import (
        execute_experiment,
        expand_trial_plan,
    )

    personas_by_id = {persona.id: persona for persona in specification.personas}
    trial_plan = expand_trial_plan(specification, personas_by_id)
    if resume:
        redo_plan, completed_records = _classify_resume_trials(
            experiment_dir, trial_plan
        )
    else:
        redo_plan = trial_plan
        completed_records = {}
    events.emit(
        "simulating", "started", total=len(trial_plan), done=len(completed_records)
    )
    if resume:
        console.print(
            f"Resume plan: {experiment_dir} — {len(redo_plan)} trials to redo, "
            f"{len(completed_records)} already complete"
        )
        if not redo_plan:
            console.print("nothing to resume")
            return experiment_dir
    if stop.is_set():
        # A stop before any trial starts changes nothing: no output is cleared and no
        # trial runs.
        raise RunStopped("stopped")

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
        raise RunError(str(exc)) from None

    trial_max_retries, trial_retry_delay_seconds = runner_factory.retry_defaults

    if resume:
        # a re-simulated trial must never be graded from the evaluation of its old run;
        # this waits for the runner factory so a setup error leaves the evaluation intact
        clear_evaluation_outputs(experiment_dir)

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
                stop=stop,
                events=events,
                console=console,
            )
    finally:
        teardown_engine_logging(log_router)
        orchestration_logger.close()

    console.print(
        _format_final_summary(
            sim_state,
            str(experiment_dir),
            str(resolved_log_dir),
        )
    )
    if stop.is_set():
        raise RunStopped("stopped")
    return experiment_dir
