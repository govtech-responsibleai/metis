"""The complete terminal corridor through the real Typer app, with no network."""

from datetime import datetime
from pathlib import Path

import httpx
import pytest
import yaml
from typer.testing import CliRunner

from metis.wizard import compile_specification
from metis.wizard.adapters.cli import commands
from metis.wizard.bootstrap import create_cli_app
from metis.wizard.contracts import InterviewState, Specification
from tests.fixtures.wizard.connections import (
    OPENAPI_DOCUMENT,
    PLANTED_SECRET,
    browser_binding,
    mock_client_factory,
)
from tests.fixtures.wizard.scripted import ScriptedInterviewer, ScriptedMatcher


@pytest.mark.parametrize("explicit", [False, True])
def test_init_happy_path_writes_specification_and_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    explicit: bool,
    export_clock,
) -> None:
    # This test is about the terminal corridor, not matching, so it uses the scripted
    # matcher's runnable grader.
    monkeypatch.setattr(commands, "_matcher", lambda _interviewer: ScriptedMatcher())
    monkeypatch.chdir(tmp_path)
    root = (
        tmp_path / "chosen folder"
        if explicit
        else tmp_path / "experiments/design/20261016-223045-interview"
    )
    arguments = ["--out-dir", str(root)] if explicit else []
    app = create_cli_app(ScriptedInterviewer)
    # Two model questions, then Continue on each of the five reviews.
    answers = [
        "engineer",
        "",
        "low",
        "answer",
        "answer",
        "continue",
        "continue",
        "continue",
        "continue",
        "continue",
    ]

    result = CliRunner().invoke(
        app,
        ["init", "A research assistant", *arguments],
        input="\n".join(answers) + "\n",
    )

    assert result.exit_code == 0, result.output
    assert (root / "outputs/review.md").is_file()
    specification_path = root / "outputs/specification.yaml"
    assert specification_path.is_file()
    # The specification the engine's verdict report reads is valid YAML that loads back.
    assert Specification.load(specification_path).trial_count() > 0
    assert "Wrote" in result.output

    state = InterviewState.model_validate_json(
        (root / "inputs/interview_state.json").read_text()
    )
    assert (
        specification_path.read_text()
        == compile_specification(state.specification).specification_yaml
    )
    assert (root / "outputs/fixtures").is_dir()
    collision = CliRunner().invoke(app, ["init", "A research assistant", *arguments])
    assert collision.exit_code == 1
    assert "complete" in collision.output
    if not explicit:
        export_clock(datetime(2026, 10, 16, 22, 30, 46))
        another = CliRunner().invoke(
            app, ["init", "A research assistant"], input="\n".join(answers) + "\n"
        )
        assert another.exit_code == 0, another.output
        assert (
            tmp_path
            / "experiments/design/20261016-223046-interview/outputs/specification.yaml"
        ).is_file()
        assert (
            specification_path.read_text()
            == compile_specification(state.specification).specification_yaml
        )
    export_clock(datetime(2026, 10, 17, 8, 15, 30))
    resumed = CliRunner().invoke(app, ["resume", "--out-dir", str(root)])
    assert resumed.exit_code == 0, resumed.output
    assert "complete" in resumed.output
    restarted = CliRunner().invoke(
        app,
        ["init", "A research assistant", "--out-dir", str(root), "--restart"],
        input="\n".join(answers) + "\n",
    )
    assert restarted.exit_code == 0, restarted.output
    assert Specification.load(specification_path).trial_count() > 0


# Two model questions, then Continue on each of the five reviews.
_INTERVIEW_ANSWERS = [
    "answer",
    "answer",
    "continue",
    "continue",
    "continue",
    "continue",
    "continue",
]
_PERSPECTIVE_ANSWERS = ["engineer"]
_CAPABILITY_ANSWERS = ["", "low"]


@pytest.fixture
def scripted_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """The real Typer app on the scripted interviewer, with the check on a mock transport."""
    from metis.wizard.application import connection as connection_module

    monkeypatch.setattr(commands, "_matcher", lambda _interviewer: ScriptedMatcher())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_URL", "https://app.example")
    monkeypatch.setenv("APP_KEY", PLANTED_SECRET)
    factory = mock_client_factory(lambda _: httpx.Response(200, json=OPENAPI_DOCUMENT))
    monkeypatch.setattr(connection_module, "_default_client", factory)
    return create_cli_app(ScriptedInterviewer)


def test_init_in_run_mode_writes_a_checked_binding_and_no_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scripted_cli,
    export_clock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # the answers come on piped input; the CLI asks them as it does in a terminal
    monkeypatch.setattr(commands, "_terminal", lambda: True)
    root = tmp_path / "run"
    # fill in the fields; HTTP; the target name; the OpenAPI URL; the credential variable;
    # no secret header; one forbidden call; the default submissions; verify TLS; no notes.
    connection_answers = [
        "1",
        "1",
        "Policy assistant",
        "${APP_URL}/openapi.json",
        "APP_KEY",
        "",
        "DELETE /**",
        "",
        "",
        "",
    ]
    answers = [
        *_PERSPECTIVE_ANSWERS,
        *connection_answers,
        "c",
        *_CAPABILITY_ANSWERS,
        *_INTERVIEW_ANSWERS,
    ]

    result = CliRunner().invoke(
        scripted_cli,
        ["init", "A research assistant", "--out-dir", str(root), "--mode", "run"],
        input="\n".join(answers) + "\n",
    )

    assert result.exit_code == 0, result.output
    assert "✓ server: the API server answers" in result.output
    specification = yaml.safe_load((root / "outputs/specification.yaml").read_text())
    assert specification["runner_factory_ref"] == (
        "metis.engine.simulation.runners.http.HttpRunnerFactory"
    )
    assert specification["target_binding"] == "target-binding.yaml"
    binding = (root / "outputs/target-binding.yaml").read_text()
    assert yaml.safe_load(binding)["auth"] == {"secret_env": "APP_KEY"}
    assert "# Required: APP_URL, APP_KEY" in binding
    assert "checked against the target" in (root / "outputs/review.md").read_text()
    state = InterviewState.model_validate_json(
        (root / "inputs/interview_state.json").read_text()
    )
    assert state.context.connection is not None
    # the secret sweep: the value is in the environment, and nowhere in what the CLI wrote
    for path in root.rglob("*"):
        if path.is_file():
            assert PLANTED_SECRET not in path.read_text(), path
    assert PLANTED_SECRET not in result.output
    assert PLANTED_SECRET not in caplog.text


def test_an_invalid_binding_is_fixed_before_the_interview_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scripted_cli, export_clock
) -> None:
    # the answers come on piped input; the CLI asks them as it does in a terminal
    monkeypatch.setattr(commands, "_terminal", lambda: True)
    root = tmp_path / "fix"
    # fill in the fields: HTTP with no target name, which is not valid; then the same fields
    # with a name.
    invalid = ["1", "1", "", "${APP_URL}/openapi.json", "", "", "", "", "", ""]
    fixed = ["1", "Policy assistant", "", "", "", "", "", "", ""]
    answers = [
        *_PERSPECTIVE_ANSWERS,
        *invalid,
        *fixed,
        "c",
        *_CAPABILITY_ANSWERS,
        *_INTERVIEW_ANSWERS,
    ]

    result = CliRunner().invoke(
        scripted_cli,
        ["init", "A research assistant", "--out-dir", str(root), "--mode", "run"],
        input="\n".join(answers) + "\n",
    )

    assert result.exit_code == 0, result.output
    assert "identity.name" in result.output
    assert "Fix the values" in result.output
    binding = yaml.safe_load((root / "outputs/target-binding.yaml").read_text())
    assert binding["identity"]["name"] == "Policy assistant"


def test_connect_adds_a_binding_to_a_spec_only_export(
    tmp_path: Path, scripted_cli, export_clock
) -> None:
    root = tmp_path / "spec"
    answers = [*_PERSPECTIVE_ANSWERS, *_CAPABILITY_ANSWERS, *_INTERVIEW_ANSWERS]
    built = CliRunner().invoke(
        scripted_cli,
        ["init", "A research assistant", "--out-dir", str(root), "--mode", "spec"],
        input="\n".join(answers) + "\n",
    )
    assert built.exit_code == 0, built.output
    assert not (root / "outputs/target-binding.yaml").exists()

    binding_file = tmp_path / "binding.yaml"
    binding_file.write_text(yaml.safe_dump(browser_binding()), encoding="utf-8")
    connected = CliRunner().invoke(
        scripted_cli,
        ["connect", "--out-dir", str(root), "--binding", str(binding_file)],
    )

    assert connected.exit_code == 0, connected.output
    specification = yaml.safe_load((root / "outputs/specification.yaml").read_text())
    assert specification["runner_factory_ref"] == (
        "metis.engine.simulation.runners.browser.BrowserRunnerFactory"
    )
    assert (root / "outputs/target-binding.yaml").is_file()


def test_resume_requires_an_explicit_experiment_root() -> None:
    result = CliRunner().invoke(create_cli_app(ScriptedInterviewer), ["resume"])
    assert result.exit_code == 2
    assert "--out-dir" in result.output
