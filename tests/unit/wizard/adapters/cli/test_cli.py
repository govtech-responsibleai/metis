"""What the commands wire up.

Every other test drives the Interview through `handle_interview`, so none of them noticed whether the
CLI door wired a matcher onto its turns. That gap is exactly the kind a unit test cannot see: each
part worked, and the assembly was wrong. These tests assert the assembly the CLI door builds.
"""

import io

import pytest
import typer

from metis.wizard.adapters.cli import commands as cli
from metis.wizard.application import config
from metis.wizard.application.compile import compile_experiment
from metis.wizard.application.matching import CRITERION_JUDGE_FQN, GraderMatcher
from metis.wizard.contracts import ChoiceRequest, InterviewState, Option, OptionId
from metis.wizard.contracts.output import GraderChoice, GraderChoices
from metis.wizard.domain.permissions import InterviewStep
from tests.fixtures.wizard.context import interview_context
from tests.fixtures.wizard.specifications import research_assistant


class StubInterviewer:
    """Stands in for the gateway. It suggests no library grader for any Criterion."""

    def select_graders(self, _prompt, _offered, criterion_ids) -> GraderChoices:
        return GraderChoices(
            choices=[GraderChoice(criterion_id=id, grader=None) for id in criterion_ids]
        )


def _state_pending_at(stage: InterviewStep) -> InterviewState:
    """A client-held state whose one pending screen was stamped at a given stage."""
    request = ChoiceRequest(
        prompt="Do these look right?",
        stage=stage,
        request_id="req-1",
        options=[Option(id=OptionId(action="continue"), label="Continue")],
    )
    return InterviewState(
        specification=research_assistant(), context=interview_context(), pending=request
    )


def test_the_spinner_uses_the_package_status_copy_for_the_pending_stage() -> None:
    """The CLI door's spinner names the stage the turn is about to work on, in package copy.

    Before any state exists the turn opens at clarify; once a screen is pending, its own stage
    drives the copy. The door never authors this text — it reads the package status owner.
    """
    assert cli._busy_message(None) == config.status_for(InterviewStep.CLARIFY)
    assert cli._busy_message(
        _state_pending_at(InterviewStep.CRITERIA)
    ) == config.status_for(InterviewStep.CRITERIA)


@pytest.mark.parametrize("terminal", [True, False], ids=["terminal", "redirected"])
def test_the_working_line_is_dim_spaced_and_leaves_nothing_behind(
    terminal: bool,
) -> None:
    from rich.console import Console

    screen = io.StringIO()
    console = Console(file=screen, force_terminal=terminal, width=80)

    with cli._working(console, "Understanding your agent…"):
        pass

    drawn = screen.getvalue()
    if not terminal:
        assert drawn == ""
        return
    assert "\n\x1b[2m" in drawn  # a blank line, then the dim spinner line
    assert "\x1b[2mUnderstanding your agent…" in drawn
    # at the end, the cursor goes up over both lines and erases them
    assert drawn.endswith("\x1b[1A\x1b[2K\x1b[1A\x1b[2K")


def test_resume_reports_the_pending_request_stage(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A pending request is authoritative even when Specification evidence points elsewhere."""
    from typer.testing import CliRunner

    from metis.wizard.adapters.cli import render as render_module
    from metis.wizard.bootstrap import create_cli_app

    state = _state_pending_at(InterviewStep.CRITERIA)
    (tmp_path / "inputs").mkdir(exist_ok=True)
    (tmp_path / "inputs/interview_state.json").write_text(
        state.model_dump_json(), encoding="utf-8"
    )
    monkeypatch.setattr(cli, "_load_env", lambda: None)
    monkeypatch.setattr(cli, "_new_interviewer", StubInterviewer)

    def stop_after_heading(*_args, **_kwargs):
        raise RuntimeError("stop after resume heading")

    monkeypatch.setattr(render_module, "render", stop_after_heading)

    result = CliRunner().invoke(
        create_cli_app(), ["resume", "--out-dir", str(tmp_path)]
    )

    assert "Resuming at the criteria step." in result.output


def test_a_retryable_failure_is_resent_when_the_user_agrees(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """The CLI acts on the `retryable` flag the contract exposes.

    A retryable failure leaves the state unchanged, so the door offers the same operation
    again — the terminal equivalent of the web client's Retry button — rather than treating
    every failure as terminal.
    """
    from rich.console import Console

    from metis.wizard import (
        InterviewErrorCode,
        InterviewFailure,
        InterviewStartRequest,
        InterviewSuccess,
    )

    start = InterviewStartRequest(
        description="a helpful research assistant",
        known_capability_ids=[],
        capability_confidence="low",
    )
    done = InterviewSuccess(
        state=InterviewState(
            specification=research_assistant(),
            context=interview_context(),
            confirmed=True,
        ),
        stage=InterviewStep.DONE,
        outcome="done",
    )
    seen: list[object] = []

    def fake_handle(request, **_kwargs):
        seen.append(request)
        if len(seen) == 1:
            return InterviewFailure(
                code=InterviewErrorCode.MODEL_UNAVAILABLE,
                message="The model could not be reached; nothing was changed.",
                retryable=True,
                state=None,
            )
        return done

    monkeypatch.setattr(cli, "handle_interview", fake_handle)
    monkeypatch.setattr(cli, "_retry_confirmed", lambda _failure: True)

    result = cli._drive(
        start,
        interviewer=StubInterviewer(),
        matcher=None,
        out_dir=tmp_path,
        console=Console(),
    )

    assert seen == [start, start]  # the failed start was resent unchanged
    assert result.confirmed is True


def test_a_non_retryable_failure_stops_without_offering_a_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A terminal failure exits at once; only a retryable one is ever offered again."""
    from rich.console import Console

    from metis.wizard import (
        InterviewErrorCode,
        InterviewFailure,
        InterviewStartRequest,
    )

    offered: list[object] = []
    monkeypatch.setattr(
        cli, "_retry_confirmed", lambda failure: offered.append(failure) or True
    )
    monkeypatch.setattr(
        cli,
        "handle_interview",
        lambda request, **_kwargs: InterviewFailure(
            code=InterviewErrorCode.COMPLETION_FAILED,
            message="I couldn't finish this into a runnable evaluation on my own.",
            retryable=False,
            state=None,
        ),
    )

    with pytest.raises(typer.Exit):
        cli._drive(
            InterviewStartRequest(
                description="x", known_capability_ids=[], capability_confidence="low"
            ),
            interviewer=StubInterviewer(),
            matcher=None,
            out_dir=tmp_path,
            console=Console(),
        )

    assert offered == []  # the retryable gate short-circuits before any prompt


def test_the_cli_wires_a_matcher_on_the_same_gateway() -> None:
    """Without one, every criterion keeps grader_fqn=None and the experiment measures
    almost nothing the user chose."""
    interviewer = StubInterviewer()

    matcher = cli._matcher(interviewer)

    assert isinstance(matcher, GraderMatcher)
    assert matcher.selector is interviewer


def test_an_unmatched_specification_loses_the_users_graders() -> None:
    """The failure the wiring prevents, stated as a fact rather than a warning.

    Without a matcher every criterion keeps grader_fqn=None, and the result is a file that
    validates and loads, and measures nothing at all.
    """
    specification = research_assistant()
    for behaviour in specification.measured_behaviours():
        for criterion in behaviour.criteria:
            criterion.grader_fqn = None  # what a turn leaves behind with no matcher

    from metis.wizard.application.compile import CompilationError

    with pytest.raises(CompilationError, match="needs a Grader"):
        compile_experiment(specification, "unmatched")


def test_a_matched_specification_keeps_them(a_catalogued_grader: type) -> None:
    """The same specification, matched — every scenario carries the graders its behaviours earned."""
    from metis.wizard.application.matching import match_specification

    specification = research_assistant()
    for behaviour in specification.measured_behaviours():
        for criterion in behaviour.criteria:
            criterion.grader_fqn = None

    match_specification(specification, cli._matcher(StubInterviewer()))  # type: ignore[arg-type]
    document = compile_experiment(specification, "matched")

    # the stub suggests no grader, so every match is the criterion judge. Every scenario is
    # still measured by something, which is the difference from the unmatched case above.
    assert all(task["behaviour_refs"] for task in document["tasks"])


def test_every_criterion_ends_up_measured_by_something() -> None:
    """A criterion with no grader is a criterion nothing checks. There should be none."""
    from metis.wizard.application.matching import match_specification

    specification = research_assistant()
    for behaviour in specification.measured_behaviours():
        for criterion in behaviour.criteria:
            criterion.grader_fqn = None

    match_specification(specification, cli._matcher(StubInterviewer()))  # type: ignore[arg-type]

    for behaviour in specification.measured_behaviours():
        for criterion in behaviour.criteria:
            assert criterion.grader_fqn
            assert (
                criterion.grader_fqn == CRITERION_JUDGE_FQN
                or "Grader" in criterion.grader_fqn
            )


def test_both_commands_fail_before_any_call_without_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from typer.testing import CliRunner

    for name in ("OPENAI_API_KEY", "INTERVIEW_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    # Isolate from any real `.env` in the project, which would otherwise supply exactly the
    # credentials this test is asserting the absence of.
    monkeypatch.setattr(cli, "_load_env", lambda: None)
    runner = CliRunner()
    from metis.wizard.bootstrap import create_cli_app

    app = create_cli_app()

    (tmp_path / "inputs").mkdir(exist_ok=True)
    (tmp_path / "inputs/interview_state.json").write_text(
        _state_pending_at(InterviewStep.CRITERIA).model_dump_json()
    )
    # `init` refuses outright when an interview already exists — its own guard, checked before
    # credentials — so `--restart` is needed to reach the credential check this test is about.
    invocations = {
        "init": [
            "init",
            "A research assistant",
            "--out-dir",
            str(tmp_path),
            "--restart",
        ],
        "resume": ["resume", "--out-dir", str(tmp_path)],
    }
    for argv in invocations.values():
        result = runner.invoke(app, argv)

        assert result.exit_code == 1
        assert "INTERVIEW_API_KEY or OPENAI_API_KEY" in result.output
        assert "docs/guide/models.md" in result.output


# ── the init guard ───────────────────────────────────────────────────────────


def test_init_refuses_when_a_interview_already_exists(tmp_path) -> None:
    """A re-run of `init` reports the collision rather than overwriting an interview.

    The check reads the filesystem only and runs before the interviewer is built or the
    description is asked for, so it fires even with no credentials and no description.
    """
    from typer.testing import CliRunner

    from metis.wizard.bootstrap import create_cli_app

    original = '{"do not": "overwrite me"}'
    (tmp_path / "inputs").mkdir(exist_ok=True)
    (tmp_path / "inputs/interview_state.json").write_text(original)

    result = CliRunner().invoke(create_cli_app(), ["init", "--out-dir", str(tmp_path)])

    assert result.exit_code == 1
    assert "already in progress" in result.output
    assert str(tmp_path / "inputs/interview_state.json") in result.output
    # both ways forward are named, and neither needs a description
    assert "resume" in result.output
    assert "--restart" in result.output
    assert "<description>" not in result.output
    # and the existing interview is untouched
    assert (tmp_path / "inputs/interview_state.json").read_text() == original


def test_run_mode_without_a_terminal_or_a_binding_stops_before_any_question(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from typer.testing import CliRunner

    from metis.wizard.bootstrap import create_cli_app

    monkeypatch.setattr(cli, "_terminal", lambda: False)
    monkeypatch.setattr(cli, "_load_env", lambda: None)

    result = CliRunner().invoke(
        create_cli_app(),
        ["init", "A research assistant", "--out-dir", str(tmp_path), "--mode", "run"],
    )

    assert result.exit_code == 1
    assert "--binding" in result.output
    assert not isinstance(result.exception, EOFError)
    assert not (tmp_path / "inputs").exists()


def _fail_on_call(*_args, **_kwargs):
    raise AssertionError("init went past the missing-input check")


def test_init_without_a_description_fails_when_no_one_can_answer(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A piped run has no terminal to answer the opening question, so it stops before any check
    that needs credentials."""
    from typer.testing import CliRunner

    from metis.wizard.adapters.cli import opening
    from metis.wizard.bootstrap import create_cli_app

    monkeypatch.setattr(cli, "_terminal", lambda: False)
    monkeypatch.setattr(cli, "_load_env", lambda: None)
    monkeypatch.setattr(cli, "_new_interviewer", _fail_on_call)
    monkeypatch.setattr(opening, "read_description", _fail_on_call)

    result = CliRunner().invoke(create_cli_app(), ["init", "--out-dir", str(tmp_path)])

    assert result.exit_code == 1
    assert "no description given" in result.output
    assert "as an argument" in result.output
    assert not (tmp_path / "inputs/interview_state.json").exists()


class _Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.mark.parametrize(
    ("argument", "typed", "expected"),
    [
        (
            None,
            "\nA research assistant that cites sources.\nsecurity\n",
            "A research assistant that cites sources.",
        ),
        ("A research assistant", "security\n", "A research assistant"),
    ],
    ids=["asked", "argument"],
)
def test_init_starts_the_interview_from_the_given_or_typed_description(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
    argument: str | None,
    typed: str,
    expected: str,
) -> None:
    """Without an argument, a terminal user answers the opening question; with one, only the
    Perspective is asked."""
    from metis.wizard.adapters.cli import opening

    monkeypatch.setattr("sys.stdin", _Terminal(typed))
    monkeypatch.setattr(cli, "_load_env", lambda: None)
    monkeypatch.setattr(cli, "_new_interviewer", StubInterviewer)
    monkeypatch.setattr(
        opening, "read_capability_evidence", lambda **_kwargs: ([], "low")
    )
    started: list[object] = []

    def capture_start(request, **_kwargs):
        started.append(request)
        raise typer.Exit(0)

    monkeypatch.setattr(cli, "_drive", capture_start)

    with pytest.raises(typer.Exit):
        cli.init(
            description=argument,
            out_dir=tmp_path,
            restart=False,
            documents=None,
            mode=cli.Mode.SPEC,
            binding=None,
        )

    assert [request.description for request in started] == [expected]  # type: ignore[attr-defined]
    assert started[0].perspective.value == "security"  # type: ignore[attr-defined]
    asked = config.load_config().opening_question in capsys.readouterr().out
    assert asked is (argument is None)


# ── reading .env ───────────────────────────────────────────────────────────


def test_init_shows_the_env_file_that_it_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from typer.testing import CliRunner

    from metis.wizard.bootstrap import create_cli_app

    env_file = tmp_path / "settings.env"
    env_file.write_text("METIS_TEST_UNUSED=1\n")
    monkeypatch.setenv("METIS_ENV_FILE", str(env_file))
    for name in ("OPENAI_API_KEY", "INTERVIEW_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    result = CliRunner().invoke(
        create_cli_app(),
        ["init", "An assistant", "--out-dir", str(tmp_path / "out")],
    )

    assert result.exit_code == 1
    assert f"Read settings from {env_file}" in result.output
    assert f"Settings file read: {env_file}" in result.output


def test_the_run_summary_shows_each_model_its_source_and_its_key_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "OPENAI_API_KEY",
        "USER_AGENT_API_KEY",
        "JUDGE_API_KEY",
        "JUDGE_MODEL",
        "DEFAULT_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("JUDGE_API_KEY", "k")
    specification = research_assistant()
    specification.experiment.defaults.user_agent_model = "ua-model"

    lines = cli._run_settings(specification)

    assert lines == [
        "  User agent: ua-model from specification.yaml "
        "(not configured: set USER_AGENT_API_KEY or OPENAI_API_KEY)",
        "  Judge: gpt-6-luna from built-in default (configured)",
    ]
    # As in the engine, the runner agent follows the user agent model of the run.
    monkeypatch.delenv("RUNNER_AGENT_MODEL", raising=False)
    monkeypatch.delenv("RUNNER_AGENT_API_KEY", raising=False)
    specification.experiment.target_binding = "targets/app.yaml"
    assert cli._run_settings(specification)[1] == (
        "  Runner agent: ua-model from user agent model (not configured: set "
        "RUNNER_AGENT_API_KEY or USER_AGENT_API_KEY or OPENAI_API_KEY)"
    )


def test_export_can_resume_after_a_failed_specification_write(
    monkeypatch, tmp_path
) -> None:
    from pathlib import Path

    from typer.testing import CliRunner

    from metis.wizard.bootstrap import create_cli_app

    state = InterviewState(
        specification=research_assistant(), context=interview_context(), confirmed=True
    )
    replace = Path.replace

    def fail_publish(self, target):
        raise OSError("write failed")

    monkeypatch.setattr(Path, "replace", fail_publish)
    with pytest.raises(OSError, match="write failed"):
        cli._write_outputs(state, tmp_path)
    assert not (tmp_path / "outputs/specification.yaml").exists()
    assert cli._load(tmp_path) == state
    monkeypatch.setattr(Path, "replace", replace)
    result = CliRunner().invoke(
        create_cli_app(), ["resume", "--out-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "outputs/specification.yaml").is_file()
