"""The wizard's commands.

Thin on purpose. The interview state is client-held, so the CLI keeps it in a JSON file and is
just another door over `handle_interview`: send a concrete lifecycle request, render the pending
screen, and send the answer back. `init` starts from the user's description, given as an argument
or typed at the opening question, and ARC capability evidence; `resume` reloads the saved state
and answers its pending screen. The corridor both run is the same loop.
"""

from __future__ import annotations

import inspect
import shlex
import sys
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

import typer
import yaml

from metis.core.console import console
from metis.wizard import (
    InterviewerUnavailable,
    InterviewFailure,
    InterviewRequest,
    InterviewStartRequest,
    InterviewState,
    InterviewStep,
    InterviewTurnRequest,
    Perspective,
    TargetConnection,
    __version__,
    compile_specification,
    core_version,
    derive_stage,
    handle_interview,
    set_connection,
)
from metis.wizard.application import export_layout
from metis.wizard.application.trials import format_trials

if TYPE_CHECKING:
    from collections.abc import Callable

    from rich.console import Console
    from rich.live import Live

    from metis.wizard import Specification
    from metis.wizard.adapters.cli.keys import KeyPrompter
    from metis.wizard.application.interviewer import Interviewer


app = typer.Typer(help="Generate METIS evaluation configurations.")


class Mode(StrEnum):
    """`spec` writes a Specification only. `run` also connects the target."""

    SPEC = "spec"
    RUN = "run"


_interviewer_factory: Callable[..., Interviewer] | None = None


def configure(*, interviewer_factory: Callable[..., Interviewer]) -> None:
    """Inject the provider used by commands.

    The CLI adapter deliberately does not import a concrete gateway. The composition root
    supplies one for production, while tests can supply a scripted interviewer here.
    """
    global _interviewer_factory
    _interviewer_factory = interviewer_factory


def _new_interviewer(interview_id: str | None = None) -> Interviewer:
    if _interviewer_factory is None:
        raise RuntimeError(
            "The wizard CLI is not composed. Use metis.wizard.bootstrap.cli_app."
        )
    factory = _interviewer_factory
    try:
        parameters = inspect.signature(factory).parameters
    except (TypeError, ValueError):
        return factory()

    id_parameter = parameters.get("interview_id")
    accepts_keywords = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )
    if accepts_keywords or id_parameter is not None:
        if (
            id_parameter is not None
            and id_parameter.kind is inspect.Parameter.POSITIONAL_ONLY
        ):
            return factory(interview_id)
        return factory(interview_id=interview_id)
    return factory()


def _matcher(interviewer: Interviewer) -> object:
    """The grader matcher, on the same gateway as the Interview.

    Every Criterion needs a Grader before the specification can be exported.
    """
    from metis.wizard.application.matching import GraderMatcher

    return GraderMatcher(selector=interviewer)  # type: ignore[arg-type]


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"metis-wizard {__version__} (core {core_version})")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-V", callback=version_callback, is_eager=True
    ),
) -> None:
    """Turn a description of your target into a runnable evaluation."""


# ── the corridor ─────────────────────────────────────────────────────────────


def _busy_message(state: InterviewState | None) -> str:
    """The package-owned status for the stage an operation is about to work on."""
    from metis.wizard.application import config

    if state is None:
        return config.status_for(InterviewStep.CLARIFY)
    if state.pending is not None and state.pending.stage is not None:
        return config.status_for(state.pending.stage)
    return config.status_for(derive_stage(state))


def _drive(
    request: InterviewRequest,
    *,
    interviewer: Interviewer,
    matcher: object,
    out_dir: Path,
    console: Console,
) -> InterviewState:
    """Run Interview operations until DONE, persisting returned state after each success.

    A model call happens inside `handle_interview`, before any screen exists — so the spinner wraps
    the whole operation, using the package-authored status for the stage. The header is redrawn only
    when the step position changes, so a run of clarify questions does not repeat the panel.
    """
    from metis.wizard.adapters.cli.render import render

    prompter = _key_prompter()
    last_step: int | None = None
    while True:
        state = None if isinstance(request, InterviewStartRequest) else request.state
        with _working(console, _busy_message(state)):
            result = handle_interview(
                request,
                interviewer=interviewer,
                matcher=matcher,
            )
        if isinstance(result, InterviewFailure):
            # A retryable failure — usually the model was unreachable — leaves the state
            # unchanged, so resending the same request is safe. The door acts on the flag the
            # contract exposes; a non-retryable failure always stops here.
            if result.retryable and _retry_confirmed(result):
                continue
            _fail(result)

        state = result.state
        _save(state, out_dir)
        if result.outcome == "done":
            return state

        pending = state.pending
        if pending is None:
            raise RuntimeError(
                "An awaiting Interview result must include a pending request."
            )
        response = render(
            pending, show_header=pending.step != last_step, prompter=prompter
        )
        last_step = pending.step
        request = InterviewTurnRequest(
            state=state, request_id=pending.request_id or "", response=response
        )


def _working(console: Console, message: str) -> Live:
    """A dim spinner line with one blank line above it, so it reads as its own phase.

    Both lines go away when the call ends, so the next screen starts with its own spacing. A
    console that is not a terminal draws nothing, as `Console.status` does.
    """
    from rich.console import Group
    from rich.live import Live
    from rich.spinner import Spinner
    from rich.text import Text

    spinner = Spinner("dots", Text(message, style="dim"), style="dim")
    return Live(
        Group(Text(""), spinner),
        console=console,
        transient=True,
        refresh_per_second=12.5,
    )


def _retry_confirmed(failure: InterviewFailure) -> bool:
    """After a retryable failure, ask whether to run the same operation again.

    The failure changed nothing, so the same request is safe to resend. Only a terminal can
    answer, so a non-interactive run does not retry and falls through to the normal error report.
    """
    if not sys.stdin.isatty():
        return False
    return typer.confirm(f"{failure.message} Try again?", default=True)


def _confirm(prompt: str) -> bool:
    prompter = _key_prompter()
    if prompter is None:
        return typer.confirm(prompt, default=False)
    return prompter.confirm(prompt, False) is True


def _fail(failure: InterviewFailure) -> NoReturn:
    """Report an Interview failure and stop. Any structured gaps are listed under the message."""
    typer.echo(f"Error: {failure.message}", err=True)
    for gap in failure.missing:
        typer.echo(f"  - {gap.message}", err=True)
    raise typer.Exit(1)


def _write_outputs(
    state: InterviewState, out_dir: Path, *, connection_skipped: bool = False
) -> None:
    """Save the final state, review, and binding, then publish the completed Specification."""
    from metis.wizard.application.compile import render_review
    from metis.wizard.application.connection import (
        binding_yaml,
        connected_specification,
    )
    from metis.wizard.application.readiness import selected_specification
    from metis.wizard.application.turn import experiment_id

    connection = state.context.connection
    # Export only the Test Cases that the user kept selected.
    specification = connected_specification(
        selected_specification(state.specification, state.excluded_tasks), connection
    )
    compiled = compile_specification(specification)
    review = render_review(
        specification,
        experiment_id(specification),
        connection=connection,
        connection_skipped=connection_skipped,
    )

    _save(state, out_dir)
    from metis.wizard.adapters.cli.documents import publish_task_fixtures

    missing_fixtures = publish_task_fixtures(
        [task.fixtures for task in specification.tasks],
        out_dir / export_layout.DOCUMENTS,
        out_dir / export_layout.FIXTURES,
    )
    specification_path = out_dir / export_layout.SPECIFICATION
    review_path = out_dir / export_layout.REVIEW
    review_path.write_text(review, encoding="utf-8")
    binding_path = out_dir / export_layout.TARGET_BINDING
    if connection is not None:
        binding_path.write_text(binding_yaml(connection), encoding="utf-8")
    else:
        binding_path.unlink(missing_ok=True)
    # Publish the completion marker only after every other file is saved.
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=specification_path.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
        try:
            temporary.write(compiled.specification_yaml)
            temporary.close()
            temporary_path.replace(specification_path)
        finally:
            temporary_path.unlink(missing_ok=True)

    typer.echo(f"\nWrote {specification_path}")
    typer.echo(f"Wrote {review_path}")
    for name in missing_fixtures:
        typer.echo(
            f"Add {name} to {out_dir / export_layout.FIXTURES} before you run. "
            "A Test Case uses this file."
        )
    if connection is not None:
        typer.echo(f"Wrote {binding_path}")
    typer.echo(
        f"Run with: metis engine run --input-dir {shlex.quote(str(out_dir / export_layout.OUTPUTS))}"
    )
    typer.echo("\nModel settings for the run (see docs/guide/models.md):")
    for line in _run_settings(specification):
        typer.echo(line)
    typer.echo(
        "To change a model, set USER_AGENT_MODEL or JUDGE_MODEL in .env, "
        "or edit specification.yaml."
    )
    typer.echo(f"\n{format_trials(specification.trial_count())} when you run this.")


# ── state persistence (client-held) ────────────────────────────────────────────


def _state_path(out_dir: Path) -> Path:
    return out_dir / export_layout.INTERVIEW_STATE


def _save(state: InterviewState, out_dir: Path) -> None:
    """Persist the client-held state so an interrupted interview can resume from it."""
    _state_path(out_dir).parent.mkdir(parents=True, exist_ok=True)
    (out_dir / export_layout.SPECIFICATION).unlink(missing_ok=True)
    _state_path(out_dir).write_text(state.model_dump_json(), encoding="utf-8")


def _load(out_dir: Path) -> InterviewState:
    return InterviewState.model_validate_json(
        _state_path(out_dir).read_text(encoding="utf-8")
    )


def _load_env() -> Path | None:
    """Read the one project `.env` (`metis.core.model_settings.load_env`).

    Exported values win: a `.env` fills gaps. Returns the file that was read, so a command can
    say where its settings came from. Exits when `METIS_ENV_FILE` names a missing file.
    """
    from metis.core.model_settings import ModelSettingsError, load_env

    try:
        return load_env()
    except ModelSettingsError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc


def _run_settings(specification: Specification) -> list[str]:
    """One line for each role that the run needs, with its model and status.

    The wizard writes a Specification without the simulator and judge keys. This list says
    which settings `metis engine run` needs. It shows variable names, never values.
    """
    import os

    from metis.core.model_settings import ROLES, ModelRole, resolve_role

    defaults = specification.experiment.defaults
    user_agent = resolve_role(
        ModelRole.USER_AGENT, os.environ, defaults.user_agent_model
    )
    run_roles = [user_agent]
    if specification.experiment.target_binding is not None:
        # As in the engine, the runner agent defaults to the user agent model of the run.
        run_roles.append(
            resolve_role(
                ModelRole.RUNNER_AGENT,
                os.environ,
                defaults.runner_agent_model,
                default=user_agent.model,
            )
        )
    run_roles.append(resolve_role(ModelRole.JUDGE, os.environ, defaults.judge_model))
    lines = []
    for settings in run_roles:
        role = settings.role
        status = (
            "configured"
            if settings.configured
            else f"not configured: set {' or '.join(ROLES[role].key_vars)}"
        )
        lines.append(
            f"  {ROLES[role].label}: {settings.model} from {settings.source} ({status})"
        )
    return lines


# ── commands ───────────────────────────────────────────────────────────────


@app.command()
def init(
    description: str | None = typer.Argument(
        None,
        help="A raw description of the target or agent to evaluate. "
        "Without it, the wizard asks for one.",
    ),
    out_dir: Path | None = typer.Option(
        None,
        "--out-dir",
        help="Experiment root. Default: experiments/design/YYYYMMDD-HHMMSS-interview/.",
    ),
    restart: bool = typer.Option(
        False,
        "--restart",
        help="Discard an interview already in progress and start over.",
    ),
    documents: list[Path] | None = typer.Option(
        None,
        "--document",
        "-d",
        exists=True,
        dir_okay=False,
        readable=True,
        help="A file for the Interview to read. Repeat the option to add more files.",
    ),
    mode: Mode | None = typer.Option(
        None,
        "--mode",
        help="spec: write a Specification only. run: also connect the target. "
        "A terminal asks when this is not given; otherwise the mode is spec.",
    ),
    binding: Path | None = typer.Option(
        None,
        "--binding",
        help="A target binding YAML file to check and use. Implies --mode run.",
    ),
) -> None:
    """Start a new interview."""
    # Refuse before anything else — the filesystem check costs no model call and needs no
    # credentials, so an accidental re-run of `init` reports the collision rather than
    # overwriting an interview in progress. `--restart` is the one way past this.
    if out_dir is None:
        out_dir = Path("experiments/design") / export_layout.experiment_name(
            "interview"
        )
    state_path = _state_path(out_dir)
    if (out_dir / export_layout.SPECIFICATION).is_file() and not restart:
        typer.echo(
            "Error: this export is complete. Use --restart to start a new Interview.",
            err=True,
        )
        raise typer.Exit(1)
    if state_path.is_file() and not restart:
        typer.echo(
            f"Error: an interview is already in progress at {state_path}.\n\n"
            f"  metis wizard resume --out-dir {shlex.quote(str(out_dir))}\n"
            f"  metis wizard init --out-dir {shlex.quote(str(out_dir))} --restart",
            err=True,
        )
        raise typer.Exit(1)
    _require_description_without_terminal(description)
    _require_binding_without_terminal(mode, binding)

    # Read the documents before the credential check, so a bad file costs no model call.
    from metis.wizard.adapters.cli.documents import (
        copy_opening_documents,
        read_opening_documents,
    )

    document_paths = documents or []
    opening_documents = read_opening_documents(
        document_paths,
        # File names are plain text, so Rich must not read brackets in them as markup.
        out=lambda line: console.print(line, markup=False, highlight=False),
        confirm=_confirm if sys.stdin.isatty() else None,
    )

    env_file = _load_env()
    if env_file is not None:
        typer.echo(f"Read settings from {env_file}")

    try:
        # Checked before anything else happens, so a missing key costs nothing and is
        # reported as the environment problem it is.
        interviewer = _new_interviewer()
    except InterviewerUnavailable as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    from metis.wizard.adapters.cli.opening import (
        read_capability_evidence,
        read_description,
        welcome,
    )

    console.print(welcome())
    if description is None:
        description = read_description(out=console.print)

    # The Perspective and the mode come next, so a user who wants to run evals sees how to
    # connect the target before the Interview questions.
    opening = _read_opening(mode, binding, perspective=True)

    known_capability_ids, capability_confidence = read_capability_evidence(
        out=console.print, prompter=_key_prompter()
    )
    # Keep the original bytes, so `resume` can put an opening file in the fixture folder.
    copy_opening_documents(
        document_paths,
        out_dir / export_layout.DOCUMENTS,
        out_dir / export_layout.FIXTURES,
    )
    typer.echo(
        f"Resume with: metis wizard resume --out-dir {shlex.quote(str(out_dir))}"
    )
    state = _drive(
        InterviewStartRequest(
            description=description,
            perspective=opening.perspective,
            known_capability_ids=known_capability_ids,
            capability_confidence=capability_confidence,
            documents=opening_documents,
            connection=opening.connection,
        ),
        interviewer=interviewer,
        matcher=_matcher(interviewer),
        out_dir=out_dir,
        console=console,
    )
    _write_outputs(state, out_dir, connection_skipped=opening.connection_skipped)


def _terminal() -> bool:
    """Whether a user can answer the questions that `init` asks."""
    return sys.stdin.isatty()


def _key_prompter() -> KeyPrompter | None:
    """The key input for this run, or `None` for typed text.

    A run reads keys only when stdin and stdout are a terminal. Redirected input, a pipe, or a
    test runner keeps the typed text input.
    """
    from metis.wizard.adapters.cli.keys import KeyPrompter, key_input_available

    return KeyPrompter() if key_input_available() else None


def _require_description_without_terminal(description: str | None) -> None:
    """Stop early when there is no description and no terminal to ask for it."""
    if description is None and not _terminal():
        typer.echo(
            "Error: no description given, and there is no terminal to ask for it. Pass the "
            'description of the target as an argument: metis wizard init "<description>".',
            err=True,
        )
        raise typer.Exit(1)


def _require_binding_without_terminal(mode: Mode | None, binding: Path | None) -> None:
    """Stop run mode early when there is no terminal to ask for the binding values."""
    if mode is Mode.RUN and binding is None and not _terminal():
        typer.echo(
            "Error: run mode needs a target binding, and there is no terminal to ask for "
            "it. Pass --binding PATH.",
            err=True,
        )
        raise typer.Exit(1)


@dataclass(frozen=True)
class _Opening:
    """The answers before the Interview. `connection_skipped` is run mode with no binding."""

    perspective: Perspective
    connection: TargetConnection | None
    connection_skipped: bool


def _read_opening(
    mode: Mode | None, binding: Path | None, *, perspective: bool
) -> _Opening:
    """Read the Perspective, when `perspective` asks for it, then the target connection.

    With no `--mode`, a terminal asks for the mode; with no terminal, the mode is spec-only.
    The questions are steps. In key mode, Esc on the mode asks the Perspective again, Esc on
    the binding source asks the mode again, and Esc on the transport asks the binding source
    again. Each question keeps the answer already given.
    """
    from metis.wizard.adapters.cli.connection import (
        load_binding_file,
        read_binding_source,
        read_mode,
        read_target_connection,
    )
    from metis.wizard.adapters.cli.keys import BACK, Step, walk
    from metis.wizard.adapters.cli.opening import read_perspective

    terminal = _terminal()
    prompter = _key_prompter()
    out = console.print
    if mode is None and binding is not None:
        mode = Mode.RUN
    if mode is None and not terminal:
        mode = Mode.SPEC
    _require_binding_without_terminal(mode, binding)

    answers: dict[str, Any] = {
        "perspective": Perspective.END_USER,
        "mode": mode,
        "binding": binding,
    }
    draft: dict[str, Any] = {}

    def ask_perspective(answers: dict[str, Any], back: bool) -> Any:
        return read_perspective(
            out=out, prompter=prompter, default=answers["perspective"], back=back
        )

    def ask_mode(answers: dict[str, Any], back: bool) -> Any:
        default = answers["mode"] or Mode.SPEC
        value = read_mode(out=out, prompter=prompter, default=default.value, back=back)
        return value if value is BACK else Mode(value)

    def ask_source(answers: dict[str, Any], back: bool) -> Any:
        return read_binding_source(
            out=out, prompter=prompter, back=back, default=answers["binding"]
        )

    def ask_connection(answers: dict[str, Any], back: bool) -> Any:
        values = None
        if answers["binding"] is not None:
            values = _load_binding(load_binding_file, answers["binding"])
        return read_target_connection(
            out=out,
            prompter=prompter,
            values=values,
            # a binding file with no terminal is checked once; nothing is asked
            interactive=terminal,
            back=back and values is None,
            draft=draft,
        )

    def is_run(answers: dict[str, Any]) -> bool:
        return answers["mode"] is Mode.RUN

    walk(
        [
            Step("perspective", ask_perspective, lambda _answers: perspective),
            Step("mode", ask_mode, lambda _answers: mode is None),
            Step("binding", ask_source, lambda a: is_run(a) and binding is None),
            Step("connection", ask_connection, is_run),
        ],
        answers,
    )
    if not is_run(answers):
        return _Opening(answers["perspective"], None, False)
    connection = answers["connection"]
    return _Opening(answers["perspective"], connection, connection is None)


def _load_binding(
    load: Callable[[Path], dict[str, Any]], binding: Path
) -> dict[str, Any]:
    try:
        return load(binding)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        # name the file only: the YAML error can quote a line of the file
        typer.echo(
            f"Error: cannot read the target binding {binding} ({type(exc).__name__}).",
            err=True,
        )
        raise typer.Exit(1) from None


@app.command()
def resume(
    out_dir: Path = typer.Option(
        ...,
        "--out-dir",
        help="The experiment root holding inputs/interview_state.json.",
    ),
) -> None:
    """Pick up an interview where it left off."""
    from metis.wizard.adapters.cli.render import render

    if (out_dir / export_layout.SPECIFICATION).is_file():
        typer.echo("This export is complete.")
        return
    path = _state_path(out_dir)
    if not path.is_file():
        typer.echo(f"Error: no interview to resume at {path}.", err=True)
        raise typer.Exit(1)

    state = _load(out_dir)
    if state.pending is None:
        _write_outputs(state, out_dir)
        return

    env_file = _load_env()
    if env_file is not None:
        typer.echo(f"Read settings from {env_file}")

    try:
        interviewer = _new_interviewer()
    except InterviewerUnavailable as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"Resuming at the {state.pending.stage} step.")

    # The saved state already holds the screen the interview stopped on; answer that first, then
    # hand the resulting Interview request to the same corridor `init` runs.
    request = state.pending
    response = render(request, show_header=True, prompter=_key_prompter())
    interview_request = InterviewTurnRequest(
        state=state,
        request_id=request.request_id or "",
        response=response,
    )

    state = _drive(
        interview_request,
        interviewer=interviewer,
        matcher=_matcher(interviewer),
        out_dir=out_dir,
        console=console,
    )
    _write_outputs(state, out_dir)


@app.command()
def connect(
    out_dir: Path = typer.Option(
        ...,
        "--out-dir",
        help="The experiment root holding inputs/interview_state.json.",
    ),
    binding: Path | None = typer.Option(
        None,
        "--binding",
        help="A target binding YAML file to check and use. Without it, the CLI asks.",
    ),
) -> None:
    """Add or replace the target connection of an Interview.

    A completed export is written again with the binding. An Interview in progress keeps the
    connection, and `resume` writes the binding when the Interview is complete.
    """
    path = _state_path(out_dir)
    if not path.is_file():
        typer.echo(f"Error: no interview at {path}.", err=True)
        raise typer.Exit(1)
    complete = (out_dir / export_layout.SPECIFICATION).is_file()
    state = _load(out_dir)

    env_file = _load_env()
    if env_file is not None:
        typer.echo(f"Read variables from {env_file}")
    connection = _read_opening(Mode.RUN, binding, perspective=False).connection
    if connection is None:
        typer.echo("Error: no valid target binding. Nothing was changed.", err=True)
        raise typer.Exit(1)

    state = set_connection(state, connection)
    if complete:
        _write_outputs(state, out_dir)
    else:
        _save(state, out_dir)
        typer.echo(
            "Saved the connection. Resume with: "
            f"metis wizard resume --out-dir {shlex.quote(str(out_dir))}"
        )
