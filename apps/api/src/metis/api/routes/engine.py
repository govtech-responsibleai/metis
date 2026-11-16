"""The engine routes: start, resume, evaluate, stop, and follow an experiment.

The routes call the ``metis.engine.run`` library functions in the API's own process, on a
thread of their own, through ``EngineRuns``. They do not use the store. They read and write
the experiment folders only, as the engine CLI does. Each route works in the project folder
of the request (``request_project_dir``), so with login on a user account reaches only its
own experiments. Every check of a start runs in the
request, before the thread starts. A run that fails later, on its thread, ends its events
log with a ``failed`` line, and the status route reports it.
"""

from __future__ import annotations

import io
import shutil
from pathlib import Path, PurePath
from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from rich.console import Console

from metis.api.engine_runs import EngineRuns, read_events
from metis.api.errors import RouteError
from metis.api.experiment_dirs import find_experiment_dir, request_project_dir
from metis.api.routes.wizard import ServiceError
from metis.core import execution_layout
from metis.core.phase_events import PhaseEvent
from metis.engine.extractor import TraceWaitSettings
from metis.engine.run import (
    EvaluationInputError,
    ExperimentExistsError,
    InvalidInputsError,
    evaluation_is_complete,
    resolve_experiment_dir,
)

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable

    from metis.api.engine_runs import Run
    from metis.api.settings import EngineSettings
    from metis.core.phase_events import Phase

router = APIRouter(prefix="/api/v1/engine", tags=["engine"])


class SimulateRequest(BaseModel):
    """Start a simulation of an input folder, as ``metis engine simulate --input-dir``."""

    model_config = ConfigDict(extra="forbid")

    input_dir: str = Field(
        description=(
            "The input folder, relative to the project folder. "
            "For example experiments/design/<target id>/outputs."
        )
    )
    concurrency: int | None = Field(
        default=None, ge=1, description="Trials at the same time. Default: a setting."
    )


class ResumeSimulationRequest(BaseModel):
    """Run again the trials of an experiment that did not end."""

    model_config = ConfigDict(extra="forbid")

    concurrency: int | None = Field(
        default=None, ge=1, description="Trials at the same time. Default: a setting."
    )


class EvaluateRequest(BaseModel):
    """Grade the trials of an experiment."""

    model_config = ConfigDict(extra="forbid")

    concurrency: int | None = Field(
        default=None, ge=1, description="Sessions at the same time. Default: a setting."
    )
    langfuse_timeout: int | None = Field(
        default=None,
        ge=1,
        description=(
            "The longest wait in seconds for the traces of a session, as "
            "--langfuse-timeout. Default: a setting, 180 unless the server changes it."
        ),
    )


class EngineRunAccepted(BaseModel):
    """The experiment of a run that started or that was asked to stop."""

    experiment_id: str


EngineRunStatus = Literal[
    "running",
    "stopping",
    "completed",
    "failed",
    "interrupted",
    "unfinished",
    "not_started",
]


class EngineStatus(BaseModel):
    """The current state of an experiment, from the live run or from its events log."""

    experiment_id: str
    phase: Literal["simulating", "evaluating"] | None = Field(
        description="The phase of the live run, else of the last phase line."
    )
    status: EngineRunStatus = Field(
        description=(
            "running or stopping while a run is alive. Else the status of the last phase "
            "line: completed, failed, or interrupted. unfinished when that line is "
            "started, because the run ended with no last line. not_started when the "
            "events log has no phase line."
        )
    )
    total: int | None = Field(
        description="Trials in the phase, from its started line. null until it is written."
    )
    done: int | None = Field(
        description="Trials that an earlier run finished, from the same started line."
    )
    reason: str | None = Field(description="The reason of a failed line, else null.")
    last_seq: int = Field(
        description="The highest seq in logs/events.jsonl, 0 when there is none."
    )


_RESPONSES: dict[int | str, dict[str, object]] = {
    404: {"model": ServiceError},
    409: {"model": ServiceError},
    422: {"model": ServiceError},
    503: {"model": ServiceError},
}


def _runs(request: Request) -> EngineRuns:
    return request.app.state.engine_runs


def _settings(request: Request) -> EngineSettings:
    return request.app.state.engine_settings


def _silent_console() -> Console:
    """A console whose text is kept in memory, for the checks of a request."""
    return Console(file=io.StringIO(), color_system=None, width=10_000, soft_wrap=True)


def _console_text(console: Console) -> str:
    file = console.file
    assert isinstance(file, io.StringIO)
    text = file.getvalue().strip()
    return text.removeprefix("Error: ")


def _limit(field: str, value: int | None, default: int, maximum: int) -> int:
    """The value of a request field, or its default. More than ``maximum`` is refused."""
    if value is None:
        return default
    if value > maximum:
        raise RouteError(
            422,
            "validation_error",
            "1 validation error in the request\n"
            f"body -> {field}: Input should be less than or equal to {maximum}",
        )
    return value


def _input_dir(project_dir: Path, text: str) -> Path:
    """The input folder that ``text`` names, inside the project folder.

    :raises RouteError: 422 ``input_dir_outside_project`` when ``text`` is absolute, or
        the folder, with its symbolic links resolved, is outside the project folder.
    """
    if "\x00" in text or PurePath(text).is_absolute() or Path(text).is_absolute():
        raise RouteError(
            422,
            "input_dir_outside_project",
            f"The input folder {text!r} must be a path relative to the project folder.",
        )
    resolved = (project_dir / text).resolve()
    if not resolved.is_relative_to(project_dir):
        raise RouteError(
            422,
            "input_dir_outside_project",
            f"The input folder {text!r} is outside the project folder.",
        )
    return resolved


def _check_specification_id(input_dir: Path) -> None:
    """Refuse a Specification id that is not one folder name, before any folder is made.

    The experiment folder is ``experiments/execute/<specification id>-<time>/``, so an id with
    a path separator or ``..`` would name a folder outside the experiments of the request,
    for example in the project folder of another user account. A file that does not load is
    left to ``prepare_experiment``, which gives its own error.

    :raises RouteError: 422 ``invalid_inputs``.
    """
    from metis.engine.simulation.types import Specification

    try:
        specification_id = Specification.load_file(input_dir / "specification.yaml").id
    except Exception:
        return
    if specification_id in ("", ".", "..") or any(
        char in specification_id for char in "/\\\x00"
    ):
        raise RouteError(
            422,
            "invalid_inputs",
            f"The Specification id {specification_id!r} must be one folder name, with no "
            "'/', '\\', or '..'.",
        )


def _inside_executions(project_dir: Path, experiment_dir: Path) -> Path:
    """The experiment folder, once it is a folder of ``experiments/execute/`` of the request.

    ``_check_specification_id`` and ``prepare_experiment`` each read ``specification.yaml``,
    so a file that changes between the two reads can put the folder in another place. Such a
    folder is removed. ``prepare_experiment`` always makes a new folder, so the removal
    deletes only what that call made.

    :raises RouteError: 422 ``invalid_inputs`` when it is in another place.
    """
    executions = (project_dir / execution_layout.EXECUTIONS).resolve()
    if experiment_dir.resolve().parent != executions:
        shutil.rmtree(experiment_dir, ignore_errors=True)
        raise RouteError(
            422,
            "invalid_inputs",
            f"The experiment folder {experiment_dir.name!r} is not in "
            f"{execution_layout.EXECUTIONS}/ of the project folder.",
        )
    return experiment_dir


def _resolved_experiment(experiment_dir: Path) -> Path:
    """The experiment folder, once it is an experiment folder of this layout.

    :raises RouteError: 422 ``invalid_experiment``, with the engine text.
    """
    console = _silent_console()
    try:
        return resolve_experiment_dir(experiment_dir, console=console)
    except EvaluationInputError as exc:
        raise RouteError(
            422, "invalid_experiment", _console_text(console) or str(exc)
        ) from None


def _trace_wait(langfuse_timeout: int) -> TraceWaitSettings:
    """The trace wait of an evaluation.

    :raises RouteError: 422 ``invalid_langfuse_timeout`` when the engine refuses it.
    """
    try:
        return TraceWaitSettings.from_env(langfuse_timeout)
    except ValueError as exc:
        raise RouteError(422, "invalid_langfuse_timeout", str(exc)) from None


@router.post(
    "/simulate",
    status_code=202,
    summary="Start a simulation of an input folder",
    response_model=EngineRunAccepted,
    responses=_RESPONSES,
)
def start_simulation(body: SimulateRequest, request: Request) -> EngineRunAccepted:
    """Create an experiment folder from the input folder and run every trial in it.

    The request checks the inputs as `metis engine simulate --input-dir` does, then creates
    `experiments/execute/<specification id>-<YYYYmmdd-HHMMSS>/`. The trials run after the
    response.
    """
    settings = _settings(request)
    concurrency = _limit(
        "concurrency", body.concurrency, settings.concurrency, settings.max_concurrency
    )
    project_dir = request_project_dir(request)
    input_dir = _input_dir(project_dir, body.input_dir)
    runs = _runs(request)

    def prepare() -> Path:
        _check_specification_id(input_dir)
        try:
            experiment_dir = runs.functions.prepare_experiment(
                input_dir, project_dir=project_dir, console=_silent_console()
            )
        except ExperimentExistsError as exc:
            raise RouteError(409, "experiment_exists", str(exc)) from None
        except InvalidInputsError as exc:
            raise RouteError(422, "invalid_inputs", str(exc)) from None
        return _inside_executions(project_dir, experiment_dir)

    def work(experiment_dir: Path, stop: threading.Event, console: Console) -> None:
        runs.functions.simulate(
            experiment_dir, concurrency=concurrency, stop=stop, console=console
        )

    experiment_id = runs.start(
        project_dir=project_dir,
        experiment_id=None,
        phase="simulating",
        prepare=prepare,
        work=work,
    )
    return EngineRunAccepted(experiment_id=experiment_id)


def _start_existing(
    request: Request,
    experiment_id: str,
    *,
    phase: Phase,
    work: Callable[[Path, threading.Event, Console], object],
    check: Callable[[Path], None] | None = None,
) -> EngineRunAccepted:
    """Start ``work`` on an experiment folder, after the checks of the request.

    The order of the checks is: the folder, the live run, the layout of the folder, then
    ``check``.
    """
    project_dir = request_project_dir(request)
    experiment_dir = find_experiment_dir(project_dir, experiment_id)
    runs = _runs(request)

    def prepare() -> Path:
        resolved = _resolved_experiment(experiment_dir)
        if check is not None:
            check(resolved)
        return resolved

    runs.start(
        project_dir=project_dir,
        experiment_id=experiment_id,
        phase=phase,
        prepare=prepare,
        work=work,
    )
    return EngineRunAccepted(experiment_id=experiment_id)


@router.post(
    "/simulate/{experiment_id}/resume",
    status_code=202,
    summary="Run again the trials of an experiment that did not end",
    response_model=EngineRunAccepted,
    responses=_RESPONSES,
)
def resume_simulation(
    experiment_id: str,
    request: Request,
    body: ResumeSimulationRequest | None = None,
) -> EngineRunAccepted:
    """Run again each trial whose record is missing, cannot be read, or was interrupted.

    When it runs any trial again, the run deletes the evaluation outputs of the experiment,
    so the report routes return results_missing until the next evaluate.
    """
    body = body or ResumeSimulationRequest()
    settings = _settings(request)
    concurrency = _limit(
        "concurrency", body.concurrency, settings.concurrency, settings.max_concurrency
    )
    runs = _runs(request)

    def work(experiment_dir: Path, stop: threading.Event, console: Console) -> None:
        runs.functions.resume_simulation(
            experiment_dir, concurrency=concurrency, stop=stop, console=console
        )

    return _start_existing(request, experiment_id, phase="simulating", work=work)


def _start_evaluation(
    request: Request, experiment_id: str, body: EvaluateRequest, *, resume: bool
) -> EngineRunAccepted:
    settings = _settings(request)
    concurrency = _limit(
        "concurrency", body.concurrency, settings.concurrency, settings.max_concurrency
    )
    langfuse_timeout = _limit(
        "langfuse_timeout",
        body.langfuse_timeout,
        settings.langfuse_timeout,
        settings.max_langfuse_timeout,
    )
    runs = _runs(request)
    # Set in ``check``, so a bad timeout is reported after the folder, run, and layout errors.
    trace_wait: TraceWaitSettings | None = None

    def check(experiment_dir: Path) -> None:
        nonlocal trace_wait
        trace_wait = _trace_wait(langfuse_timeout)
        if resume and evaluation_is_complete(experiment_dir):
            raise RouteError(
                409,
                "evaluation_complete",
                f"The evaluation of {experiment_id!r} is complete, so it has nothing to "
                "resume. Start an evaluate to grade every trial again.",
            )

    def work(experiment_dir: Path, stop: threading.Event, console: Console) -> None:
        assert trace_wait is not None  # check runs before the thread starts
        function = (
            runs.functions.resume_evaluation if resume else runs.functions.evaluate
        )
        function(
            experiment_dir,
            trace_wait=trace_wait,
            concurrency=concurrency,
            stop=stop,
            console=console,
        )

    return _start_existing(
        request, experiment_id, phase="evaluating", work=work, check=check
    )


@router.post(
    "/evaluate/{experiment_id}",
    status_code=202,
    summary="Grade every trial of an experiment",
    response_model=EngineRunAccepted,
    responses=_RESPONSES,
)
def start_evaluation(
    experiment_id: str, request: Request, body: EvaluateRequest | None = None
) -> EngineRunAccepted:
    """Delete the earlier evaluation of the experiment, then grade every trial."""
    return _start_evaluation(
        request, experiment_id, body or EvaluateRequest(), resume=False
    )


@router.post(
    "/evaluate/{experiment_id}/resume",
    status_code=202,
    summary="Grade the trials of an experiment that have no evaluation",
    response_model=EngineRunAccepted,
    responses=_RESPONSES,
)
def resume_evaluation(
    experiment_id: str, request: Request, body: EvaluateRequest | None = None
) -> EngineRunAccepted:
    """Grade only the trials with no evaluation file. A complete evaluation gives 409
    evaluation_complete."""
    return _start_evaluation(
        request, experiment_id, body or EvaluateRequest(), resume=True
    )


@router.post(
    "/{experiment_id}/stop",
    status_code=202,
    summary="Stop the run of an experiment",
    response_model=EngineRunAccepted,
    responses=_RESPONSES,
)
def stop_run(experiment_id: str, request: Request) -> EngineRunAccepted:
    """Set the stop flag of the run, and return at once.

    A simulation ends each trial at its next turn, and an evaluation cancels its sessions
    within a fraction of a second. The events log then ends with interrupted.
    """
    project_dir = request_project_dir(request)
    find_experiment_dir(project_dir, experiment_id)
    _runs(request).stop(project_dir, experiment_id)
    return EngineRunAccepted(experiment_id=experiment_id)


@router.get(
    "/{experiment_id}",
    summary="Get the status of an experiment",
    response_model=EngineStatus,
    responses={404: {"model": ServiceError}},
)
def experiment_status(experiment_id: str, request: Request) -> EngineStatus:
    """Return the phase, the status, and the counts of the experiment."""
    project_dir = request_project_dir(request)
    experiment_dir = find_experiment_dir(project_dir, experiment_id)
    run = _runs(request).current(project_dir, experiment_id)
    return _status(experiment_id, experiment_dir, run)


def _status(experiment_id: str, experiment_dir: Path, run: Run | None) -> EngineStatus:
    events = [event for event, _ in read_events(experiment_dir)]
    last_seq = max((event.seq for event in events), default=0)
    # A skipped line says that a phase did not run, so the line before it gives the state.
    phase_lines = [e for e in events if e.trial is None and e.status != "skipped"]
    if run is not None:
        started = next(
            (
                e
                for e in reversed(phase_lines)
                if e.seq > run.start_seq
                and e.phase == run.phase
                and e.status == "started"
            ),
            None,
        )
        return EngineStatus(
            experiment_id=experiment_id,
            phase=run.phase,
            status="stopping" if run.stop.is_set() else "running",
            total=started.total if started else None,
            done=started.done if started else None,
            reason=None,
            last_seq=last_seq,
        )
    if not phase_lines:
        return EngineStatus(
            experiment_id=experiment_id,
            phase=None,
            status="not_started",
            total=None,
            done=None,
            reason=None,
            last_seq=last_seq,
        )
    newest = phase_lines[-1]
    started = next(
        (
            e
            for e in reversed(phase_lines)
            if e.phase == newest.phase and e.status == "started"
        ),
        None,
    )
    status: EngineRunStatus
    if newest.status == "started":
        status = "unfinished"
    elif newest.status in ("completed", "failed", "interrupted"):
        status = newest.status
    else:  # pragma: no cover - no other status is valid on a phase line
        status = "unfinished"
    return EngineStatus(
        experiment_id=experiment_id,
        phase=newest.phase,
        status=status,
        total=started.total if started else None,
        done=started.done if started else None,
        reason=newest.reason if newest.status == "failed" else None,
        last_seq=last_seq,
    )


@router.get(
    "/{experiment_id}/events",
    summary="Get the events of an experiment after a seq",
    response_model=list[PhaseEvent],
    response_class=JSONResponse,
    responses={404: {"model": ServiceError}, 422: {"model": ServiceError}},
)
def experiment_events(
    experiment_id: str,
    request: Request,
    after: int = Query(
        default=0, ge=0, description="Return the events whose seq is more than this."
    ),
) -> JSONResponse:
    """Return the lines of logs/events.jsonl whose seq is more than `after`, in file order.

    Each element is an event in the format of phase-event.schema.json, with no field that
    has no value. A last line that the engine still writes, and a line that does not parse,
    are skipped. An experiment with no events file returns [].
    """
    experiment_dir = find_experiment_dir(request_project_dir(request), experiment_id)
    events = [
        _event_json(event)
        for event, _ in read_events(experiment_dir)
        if event.seq > after
    ]
    return JSONResponse(events)


_COMMON_FIELDS = ("seq", "at", "phase", "trial", "status")
"""The fields of every line, ``trial`` as ``null`` on a phase line."""


def _event_json(event: PhaseEvent) -> dict[str, object]:
    """The JSON of ``event`` in the format of phase-event.schema.json.

    It is built from the parsed event, so a field that the schema does not know is left out,
    and a field with no value is left out unless every line has it.
    """
    fields = event.model_dump(mode="json")
    return {
        name: value
        for name, value in fields.items()
        if name in _COMMON_FIELDS or value is not None
    }


__all__ = ["router"]
