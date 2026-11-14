"""Grade the trials of an experiment folder that ``simulate`` made."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, TypeVar

from rich.progress import BarColumn, MofNCompleteColumn, Progress, TaskID, TextColumn

from metis.core import execution_layout
from metis.core.phase_events import PhaseEventLog
from metis.engine.logging import EvaluationLogger
from metis.engine.runs._common import (
    clear_evaluation_outputs,
    end_phase_on_error,
    resume_command,
    trial_record_files,
)
from metis.engine.runs._inputs import validate_inputs
from metis.engine.runs.errors import (
    EvaluationInputError,
    InvalidInputsError,
    RunStopped,
)
from metis.engine.tracing import trial_session_id

if TYPE_CHECKING:
    import threading
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from langfuse import Langfuse
    from rich.console import Console

    from metis.core.profile import Criterion
    from metis.core.reporting import GraderRecord
    from metis.core.traces import Trace
    from metis.core.trials import TrialRecord
    from metis.engine.evaluation.trial_files import TrialEvaluation
    from metis.engine.extractor import TraceWait, TraceWaitSettings
    from metis.engine.simulation.types import Specification
    from metis.library.grader import Grader, LLMSettings

_T = TypeVar("_T")

_STOP_CHECK_SECONDS = 0.2
"""How often an evaluation checks its stop flag."""


@dataclass(frozen=True)
class EvaluationOutcome:
    """Summary returned by the evaluation phase.

    ``results_file`` is set for every evaluation that ran, even one in which every trial
    failed. It is ``None`` only when there was nothing to evaluate.
    """

    total_records: int
    successful_records: int
    failed_records: int
    results_file: Path | None


def evaluate(
    experiment_dir: Path,
    *,
    trace_wait: TraceWaitSettings,
    concurrency: int,
    stop: threading.Event,
    console: Console,
    show_progress: bool = False,
    command: Literal["evaluate", "run"] = "evaluate",
) -> EvaluationOutcome:
    """Grade every trial of an experiment folder, and write ``results.json``.

    It deletes the outputs of an earlier evaluation first, so every trial is graded again.
    It writes the ``evaluating`` lines of ``logs/events.jsonl``: ``started``, then
    ``completed``, ``failed`` or ``interrupted``. When ``stop`` is set, it cancels the
    sessions in flight within a fraction of a second, also while a session waits for its
    traces. It keeps the trials that it graded and writes no ``results.json``.

    ``show_progress`` draws a progress bar on ``console``, for a terminal. ``command``
    names the CLI command that the "to continue" text names.

    The caller sets up the process first: it loads ``.env``, calls
    ``metis.engine.tracing.tracing_key()``, and sets up process logging. Only one run at a
    time is safe in one process.

    :raises RunStopped: When ``stop`` was set.
    :raises EvaluationInputError: When the experiment folder, its snapshot, or a trial
        record is not valid, or a model-based grader has no judge key.
    :raises Exception: Any other error, after it is printed and logged.
    """
    return _evaluate(
        experiment_dir,
        resume=False,
        trace_wait=trace_wait,
        concurrency=concurrency,
        stop=stop,
        console=console,
        show_progress=show_progress,
        command=command,
    )


def resume_evaluation(
    experiment_dir: Path,
    *,
    trace_wait: TraceWaitSettings,
    concurrency: int,
    stop: threading.Event,
    console: Console,
    show_progress: bool = False,
    command: Literal["evaluate", "run"] = "evaluate",
) -> EvaluationOutcome:
    """Grade only the trials that have no evaluation file, as ``evaluate`` does otherwise.

    It keeps the evaluation file of every trial that an earlier evaluation graded, whether
    it succeeded or failed. When ``results.json`` can be read, the evaluation is complete:
    it prints ``nothing to resume`` and changes no file. Under ``command="run"`` it still
    writes the ``evaluating`` ``started`` and ``completed`` lines.

    The caller sets up the process first, and only one run at a time is safe in one
    process, as for ``evaluate``.
    """
    return _evaluate(
        experiment_dir,
        resume=True,
        trace_wait=trace_wait,
        concurrency=concurrency,
        stop=stop,
        console=console,
        show_progress=show_progress,
        command=command,
    )


def _evaluate(
    experiment_dir: Path,
    *,
    resume: bool,
    trace_wait: TraceWaitSettings,
    concurrency: int,
    stop: threading.Event,
    console: Console,
    show_progress: bool,
    command: Literal["evaluate", "run"],
) -> EvaluationOutcome:
    """Grade between the phase lines ``started`` and the line that ends the phase.

    A resume's ``started`` line counts the trials already evaluated as done.
    """
    from metis.engine.evaluation.trial_files import load_trial_evaluations

    trials = [path.parent.name for path in trial_record_files(experiment_dir)]
    results_path = experiment_dir / execution_layout.RESULTS
    if resume and evaluation_is_complete(experiment_dir):
        console.print("nothing to resume")
        saved = load_trial_evaluations(experiment_dir, trials)
        if command == "run":
            # the run's simulating lines are already logged, so close its evaluating phase
            events = PhaseEventLog.for_experiment_dir(experiment_dir)
            events.emit("evaluating", "started", total=len(trials), done=len(saved))
            events.emit("evaluating", "completed")
        return _evaluation_outcome(list(saved.values()), results_path)
    events = PhaseEventLog.for_experiment_dir(experiment_dir)
    done = len(load_trial_evaluations(experiment_dir, trials)) if resume else 0
    events.emit("evaluating", "started", total=len(trials), done=done)
    try:
        outcome = _grade(
            experiment_dir,
            events,
            resume=resume,
            trace_wait=trace_wait,
            concurrency=concurrency,
            stop=stop,
            console=console,
            show_progress=show_progress,
            command=command,
        )
    except (EvaluationInputError, RunStopped) as exc:
        if isinstance(exc, EvaluationInputError):
            _log_failure(experiment_dir, exc)
        end_phase_on_error(events, "evaluating", exc)
        raise
    except Exception as exc:
        _log_failure(experiment_dir, exc)
        console.print(f"Error: evaluation failed: {exc}", style="bold red")
        end_phase_on_error(events, "evaluating", exc)
        raise
    except BaseException as exc:
        end_phase_on_error(events, "evaluating", exc)
        raise
    events.emit("evaluating", "completed")
    return outcome


def _log_failure(experiment_dir: Path, exc: Exception) -> None:
    EvaluationLogger(experiment_dir / execution_layout.LOGS, reset=False).write(
        f"EVALUATION FAILED — {exc}"
    )


def _grade(
    experiment_dir: Path,
    events: PhaseEventLog,
    *,
    resume: bool,
    trace_wait: TraceWaitSettings,
    concurrency: int,
    stop: threading.Event,
    console: Console,
    show_progress: bool,
    command: Literal["evaluate", "run"],
) -> EvaluationOutcome:
    """Grade the records in ``experiment_dir``.

    A resume appends to ``evaluate.log``; a fresh evaluation starts it again.
    """
    from metis.core.model_settings import find_env_file
    from metis.core.trials import TrialRecord

    evaluation_log = EvaluationLogger(
        experiment_dir / execution_layout.LOGS, reset=not resume
    )
    evaluation_log.write(
        f"EVALUATION STARTED — {experiment_dir} (concurrency {concurrency})"
    )
    specification = _load_evaluation_specification(experiment_dir, console=console)
    files = trial_record_files(experiment_dir)
    if not files:
        evaluation_log.write("EVALUATION COMPLETED — 0 records")
        return EvaluationOutcome(0, 0, 0, None)

    try:
        trial_records = [
            (path.parent.name, TrialRecord.load_file(path)) for path in files
        ]
    except Exception as exc:
        console.print(f"Error: failed to load trial record: {exc}", style="bold red")
        raise EvaluationInputError("failed to load trial record") from exc

    console.print(f"  Loaded {len(trial_records)} trial record(s)")
    evaluation_log.write(f"LOADED {len(trial_records)} trial record(s)")
    work = _evaluate_records(
        experiment_dir,
        specification,
        trial_records,
        evaluation_log=evaluation_log,
        trace_wait=trace_wait,
        concurrency=concurrency,
        env_file=find_env_file(),
        events=events,
        command=command,
        resume=resume,
        console=console,
        show_progress=show_progress,
        stop=stop,
    )
    try:
        return asyncio.run(_until_stopped(work, stop))
    except asyncio.CancelledError:
        if stop.is_set():
            raise RunStopped("stopped") from None
        raise


async def _until_stopped(work: Awaitable[_T], stop: threading.Event) -> _T:
    """Await ``work``, and cancel it once ``stop`` is set.

    ``work`` runs in this task, so a Ctrl-C, which cancels this task, reaches it as before.
    """
    task = asyncio.current_task()
    assert task is not None
    watcher = asyncio.create_task(_cancel_on_stop(task, stop))
    try:
        return await work
    finally:
        watcher.cancel()


async def _cancel_on_stop(task: asyncio.Task[Any], stop: threading.Event) -> None:
    """Cancel ``task`` once ``stop`` is set. It checks at once, then every few tenths."""
    while not stop.is_set():
        await asyncio.sleep(_STOP_CHECK_SECONDS)
    task.cancel()


def _load_evaluation_specification(
    experiment_dir: Path, *, console: Console
) -> Specification:
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
        validate_inputs(inputs_dir, console=console)
    except InvalidInputsError as exc:
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


def _create_evaluation_progress(console: Console) -> Progress:
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
    bar_description: str | None = None,
    console: Console,
) -> None:
    """Update the progress bar or print one linear progress message.

    ``bar_description`` replaces the bar's text only; the linear message keeps the phase.
    """
    description = f"{label} — {phase}"
    if progress and task_id is not None:
        progress.update(
            task_id,
            description=bar_description if bar_description is not None else description,
            advance=advance,
        )
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


def _log_trace_wait(
    evaluation_log: EvaluationLogger,
    wait: TraceWait,
    *,
    record_label: str,
    console: Console,
) -> None:
    """Write how long one trial waited for its traces, and warn about open observations."""
    evaluation_log.write(
        f"TRACE WAIT: record={record_label} status={wait.status} "
        f"checks={wait.checks} waited={wait.waited_seconds:.1f}s"
    )
    if not wait.open_observations:
        return
    names = ", ".join(f"{o.name or 'unnamed'} ({o.id})" for o in wait.open_observations)
    console.print(
        f"  WARNING: {len(wait.open_observations)} observation(s) never ended, "
        f"graded as stored: {names}",
        style="yellow",
        markup=False,
    )
    evaluation_log.write(f"OPEN OBSERVATIONS: record={record_label} ids={names}")


def _save_session_traces(
    experiment_dir: Path,
    session_id: str,
    traces: tuple[Trace, ...],
    evaluation_log: EvaluationLogger,
    *,
    console: Console,
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


class _RunningCount:
    """How many sessions hold a semaphore slot right now.

    It goes up when a session takes a slot and down in a ``finally``, with no ``await``
    between a read and its write, so one event loop cannot interleave two changes.
    """

    def __init__(self) -> None:
        self.value = 0


def _record_label(record: TrialRecord) -> str:
    """How a record is named in the log, the warnings and the progress bar."""
    return f"{record.config.persona} x {record.config.scenario}"


@dataclass(frozen=True)
class _EvaluationContext:
    """What every record of one evaluation shares. Built once, read by ``_evaluate_one``."""

    experiment_dir: Path
    criteria_by_id: dict[str, Criterion]
    graders: dict[str, Grader[Any]]
    llm: LLMSettings
    langfuse: Langfuse
    trace_wait: TraceWaitSettings
    evaluation_log: EvaluationLogger
    total_records: int
    concurrency: int
    semaphore: asyncio.Semaphore
    running: _RunningCount
    console: Console
    events: PhaseEventLog | None = None
    stop: threading.Event | None = None


@dataclass(frozen=True)
class _RecordResult:
    """One record's outcome: its grader records, or why it failed."""

    records: list[GraderRecord]
    failure_reason: str | None
    warning: str | None = None


async def _evaluate_one(
    record: TrialRecord,
    *,
    number: int,
    context: _EvaluationContext,
    phase: Callable[..., None],
    trial: str,
) -> TrialEvaluation:
    """Fetch and grade one trial record's session, once it holds one of the N slots.

    A record that is still waiting for a slot is a bare coroutine: it holds no connection
    and no traces. An error in the fetch, the trace save or the grading is caught inside
    (in ``_fetch_and_grade``) and returned as a failure, so the caller never sees it.
    The caller combines the returned values; this function changes no shared counter
    except the running count, which a ``finally`` restores.

    ``started_at`` and ``finished_at`` bound the time the trial held its slot. Once the
    slot is released, the trial's evaluation file is written. That is the file's only
    write, so the file exists only for a trial whose evaluation has ended; a cancelled
    trial writes none.

    The file save and the reporting calls (``console.print``, ``log.write`` and
    ``phase``) are not guarded. If one raises, for example because the disk is full, the
    error leaves this function, the ``TaskGroup`` cancels every other session, and
    ``_evaluate_records`` reports it. That is deliberate: a file, log or display that no
    longer works is a problem to surface, not one to hide.
    """
    from metis.engine.evaluation import trial_files

    label = _record_label(record)
    record_name = f"RECORD {number}/{context.total_records} {label}"
    log = context.evaluation_log

    async with context.semaphore:
        while context.stop is not None and context.stop.is_set():
            # The stop watcher cancels every session within one check. A session whose
            # slot comes up after a stop waits for that, so it never starts its work.
            await asyncio.sleep(_STOP_CHECK_SECONDS)
        started_at = datetime.now(UTC)
        context.running.value += 1
        try:
            if context.events:
                context.events.emit("evaluating", "started", trial=trial)
            result = await _fetch_and_grade(
                record,
                number=number,
                label=label,
                record_name=record_name,
                context=context,
                phase=phase,
            )
            finished_at = datetime.now(UTC)
        finally:
            context.running.value -= 1

    evaluation = trial_files.TrialEvaluation(
        trial=trial,
        records=result.records,
        failure_reason=result.failure_reason,
        started_at=started_at,
        finished_at=finished_at,
    )
    trial_files.save_trial_evaluation(context.experiment_dir, evaluation)

    if context.events:
        context.events.emit(
            "evaluating",
            "completed" if result.failure_reason is None else "failed",
            trial=trial,
            reason=result.failure_reason,
        )
    if result.failure_reason is None:
        log.write(f"{record_name} — DONE")
        phase("done", advance=1)
        return evaluation
    context.console.print(
        f"  WARNING: {record_name} — {result.warning or result.failure_reason}",
        style="yellow",
        markup=False,
    )
    log.write(f"{record_name} — FAILED — {result.failure_reason}")
    phase("failed", advance=1)
    return evaluation


async def _fetch_and_grade(
    record: TrialRecord,
    *,
    number: int,
    label: str,
    record_name: str,
    context: _EvaluationContext,
    phase: Callable[..., None],
) -> _RecordResult:
    """The work of one record while it holds a slot: fetch, save traces, grade."""
    from metis.engine import extractor
    from metis.engine.evaluation import SessionFacts, grade_session

    log = context.evaluation_log
    experiment_dir = context.experiment_dir
    graders = context.graders
    console = context.console

    log.write(f"{record_name} — EXTRACTING")
    phase("extracting")
    if context.concurrency == 1:
        # The banner says "a new session starts here", which is false when sessions overlap.
        console.print(f"\n\n{'#' * 60}")
        console.print(f"  SESSION {number}/{context.total_records}: {label}")
        console.print(f"{'#' * 60}")

    session_id = record.target_session_id
    criteria = [
        context.criteria_by_id[ref.criterion_id]
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
            f"  WARNING: {record_name} — criteria {', '.join(unknown)} are not in the "
            "specification snapshot and were not graded",
            style="yellow",
            markup=False,
        )
        log.write(f"{record_name} — UNKNOWN CRITERIA — {', '.join(unknown)}")
    try:
        if not session_id:
            return _RecordResult([], "No target_session_id")
        if not criteria:
            return _RecordResult([], "No grader_refs in run config")
        waits: list[TraceWait] = []
        try:
            grading_input = await extractor.fetch_session(
                session_id,
                context.langfuse,
                experiment_root=experiment_dir,
                artifacts=record.artifacts,
                settings=context.trace_wait,
                on_wait=waits.append,
            )
        finally:
            if waits:
                _log_trace_wait(log, waits[-1], record_label=label, console=console)
        _save_session_traces(
            experiment_dir, session_id, grading_input.traces, log, console=console
        )
        log.write(f"{record_name} — EVALUATING")
        for criterion in criteria:
            log.write(
                "GRADER CONFIG — "
                + json.dumps(
                    {
                        "record": label,
                        "criterion_id": criterion.id,
                        "fqn": criterion.grader_fqn,
                        "args": graders[criterion.id].args.model_dump(mode="json"),
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
            context.llm,
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
        _log_grader_records(log, session_records, record_label=label)
        return _RecordResult(session_records, None)
    except extractor.TracesNotReadyError as exc:
        return _RecordResult([], str(exc))
    except Exception as exc:
        return _RecordResult([], str(exc), warning=f"Evaluation failed: {exc}")


async def _evaluate_records(
    experiment_dir: Path,
    specification: Specification,
    trial_records: list[tuple[str, TrialRecord]],
    *,
    evaluation_log: EvaluationLogger,
    trace_wait: TraceWaitSettings,
    concurrency: int = 1,
    env_file: Path | None = None,
    events: PhaseEventLog | None = None,
    command: Literal["evaluate", "run"] = "evaluate",
    resume: bool = False,
    console: Console,
    show_progress: bool = False,
    stop: threading.Event | None = None,
) -> EvaluationOutcome:
    """Grade every trial record's session and write one GraderRecord per grader per session.

    Graders are built once per criterion from the specification snapshot.
    A criterion graded in many trials shares one grader. One judge client
    is opened for the whole evaluation, and only when some criterion's grader needs one.

    Each record comes with the name of its trial folder, and the trial files and the
    events name the trial by that folder. Once the graders are built and the judge key is checked, a fresh evaluation removes the
    previous evaluation's outputs. A resume removes only ``results.json`` and keeps
    every trial that already has an evaluation file, whether it succeeded or failed;
    only the other trials are graded. Each graded trial writes its evaluation file as
    it ends, and ``results.json`` is assembled from the files of every trial, in record
    order, as the run's last write.

    When it is cancelled, by Ctrl-C or by the stop watcher, the message says how many
    trials are saved and names the ``--resume`` form of ``command``. A session that gets
    its slot once ``stop`` is set waits to be cancelled.

    Its text goes to ``console``. ``show_progress`` draws a progress bar there in place
    of one line per step.

    With ``events``, each graded trial writes a ``started`` line and a ``completed`` or
    ``failed`` line to the event log.
    """
    import asyncio

    from metis.engine import extractor
    from metis.engine.evaluation import JudgeGateway, build_grader, build_llm_settings
    from metis.library.grader import JudgeArgs, LLMSettings

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

    from metis.engine.evaluation.trial_files import load_trial_evaluations

    trials = [trial for trial, _ in trial_records]
    results_path = experiment_dir / execution_layout.RESULTS
    if resume:
        results_path.unlink(missing_ok=True)
        attempted = load_trial_evaluations(experiment_dir, trials)
        message = (
            f"resuming: {len(attempted)} of {len(trials)} trials already evaluated"
        )
        console.print(message)
        evaluation_log.write(message)
    else:
        clear_evaluation_outputs(experiment_dir)
        attempted = {}
    langfuse = extractor.get_langfuse_client()
    evaluations: list[TrialEvaluation] = []
    progress = _create_evaluation_progress(console) if show_progress else None

    try:
        with progress if progress else nullcontext():
            task_id = (
                progress.add_task(
                    "Evaluation", total=len(trial_records), completed=len(attempted)
                )
                if progress
                else None
            )
            context = _EvaluationContext(
                experiment_dir=experiment_dir,
                criteria_by_id=criteria_by_id,
                graders=graders,
                llm=llm,
                langfuse=langfuse,
                trace_wait=trace_wait,
                evaluation_log=evaluation_log,
                total_records=len(trial_records),
                concurrency=concurrency,
                semaphore=asyncio.Semaphore(concurrency),
                running=_RunningCount(),
                console=console,
                events=events,
                stop=stop,
            )

            def phase_for(number: int, label: str) -> Callable[..., None]:
                def phase(name: str, *, advance: int = 0) -> None:
                    # One text slot cannot show several sessions' phases, so with
                    # overlapping sessions the bar says how many are running instead.
                    # The phases remain in the evaluation log.
                    _update_evaluation_progress(
                        progress,
                        task_id,
                        record_number=number,
                        total_records=len(trial_records),
                        label=label,
                        phase=name,
                        advance=advance,
                        bar_description=(
                            f"Evaluation — {context.running.value} running"
                            if concurrency > 1
                            else None
                        ),
                        console=console,
                    )

                return phase

            # Every record starts at once; the semaphore inside _evaluate_one lets N of
            # them work. The tasks stay in record order, so results do not depend on the
            # order sessions finish in.
            async with asyncio.TaskGroup() as group:
                tasks = [
                    group.create_task(
                        _evaluate_one(
                            record,
                            number=index + 1,
                            trial=trial,
                            context=context,
                            phase=phase_for(index + 1, _record_label(record)),
                        )
                    )
                    for index, (trial, record) in enumerate(trial_records)
                    if trial not in attempted
                ]
            evaluations = [task.result() for task in tasks]

            if progress and task_id is not None:
                progress.update(task_id, description="Evaluation complete")
    except ExceptionGroup as group_error:
        # An error that escaped _evaluate_one. The TaskGroup wraps it, and the wrapper's
        # text ("unhandled errors in a TaskGroup (1 sub-exception)") hides the cause, so
        # a lone error is raised as itself, with the group kept as its cause for anyone
        # reading the traceback. Several errors keep the group.
        if len(group_error.exceptions) == 1:
            raise group_error.exceptions[0] from group_error
        raise
    except asyncio.CancelledError:
        # Ctrl-C. The TaskGroup has already cancelled every session and waited for it to
        # stop. A cancellation is a BaseException, so the command's `except Exception`
        # never sees it: log it here and let it go on. No results file is written; the
        # trials that ended keep their files, so a resume grades only the rest.
        results_path.unlink(missing_ok=True)
        evaluation_log.write("EVALUATION INTERRUPTED")
        saved = len(load_trial_evaluations(experiment_dir, trials))
        console.print(
            f"\nInterrupted. {saved} of {len(trials)} trials are saved. "
            "To continue, run: "
            f"{resume_command(experiment_dir.resolve(), command)}",
            style="yellow",
            markup=False,
            soft_wrap=True,
        )
        raise
    finally:
        # Runs only after every session has stopped, so no grader call is still using it.
        if gateway is not None and needs_llm:
            await llm.client.close()

    saved = attempted | {evaluation.trial: evaluation for evaluation in evaluations}
    every_trial = [saved[trial] for trial in trials]
    results_file = _write_results(experiment_dir, every_trial)
    evaluation_log.write(f"RESULTS WRITTEN — {results_file}")
    outcome = _evaluation_outcome(every_trial, results_file)
    evaluation_log.write(
        "EVALUATION COMPLETED — "
        f"{outcome.successful_records}/{outcome.total_records} records succeeded, "
        f"{outcome.failed_records} failed"
    )
    return outcome


def _write_results(experiment_dir: Path, evaluations: list[TrialEvaluation]) -> Path:
    """Write ``results.json`` from the trial evaluations, their records in the order given.

    It is written even when no record was graded. The time is the wall-clock span in
    which any trial was being evaluated.
    """
    from metis.core.reporting import EvaluationResults
    from metis.engine.evaluation.trial_files import grading_seconds

    seconds = round(grading_seconds(evaluations), 1)
    path = experiment_dir / execution_layout.RESULTS
    EvaluationResults(
        run_id="report",
        records=[record for evaluation in evaluations for record in evaluation.records],
        timings={"evaluation_seconds": seconds},
        latency_seconds=seconds or None,
    ).save(path)
    return path


def _evaluation_outcome(
    evaluations: list[TrialEvaluation], results_file: Path | None
) -> EvaluationOutcome:
    """Count the trials whose evaluation succeeded and those that failed."""
    successful = sum(1 for e in evaluations if e.failure_reason is None)
    return EvaluationOutcome(
        total_records=len(evaluations),
        successful_records=successful,
        failed_records=len(evaluations) - successful,
        results_file=results_file,
    )


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


def evaluation_is_complete(experiment_dir: Path) -> bool:
    """Whether the evaluation in ``experiment_dir`` wrote a ``results.json`` that loads.

    ``results.json`` is an evaluation's last write, so a readable one means every trial
    was attempted. A missing or unparsable file means the evaluation did not finish.
    """
    from metis.core.reporting import EvaluationResults

    try:
        EvaluationResults.load_file(experiment_dir / execution_layout.RESULTS)
    except (OSError, ValueError):
        return False
    return True
