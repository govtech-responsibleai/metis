"""The simulation models: the trial record, the checks before a run, and the models line."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from metis.core.model_settings import ModelRole
from metis.engine import cli
from metis.engine.cli import app
from metis.engine.simulation import experiment as experiment_module
from metis.engine.simulation import model_settings as simulation_model_settings
from metis.engine.simulation.experiment import trial_models
from metis.engine.simulation.model_settings import sampling_options
from metis.engine.simulation.types import Specification
from tests.unit.engine.test_cli_evaluate import GRADERS, _spec_with
from tests.unit.engine.test_cli_simulate import MINIMAL_EXPERIMENT

runner = CliRunner()
_HTTP_REF = "metis.engine.simulation.runners.http.HttpRunnerFactory"


def test_a_task_model_reaches_the_trial_and_the_trial_records_its_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import yaml

    document = MINIMAL_EXPERIMENT.replace(
        "  num_trials: 1\n", "  num_trials: 1\n  user_agent_model: task-ua\n"
    )
    specification = Specification.model_validate(yaml.safe_load(document))
    (scenario,) = specification.resolved_tasks()
    assert scenario.user_agent_model == "task-ua"

    monkeypatch.setenv("USER_AGENT_MODEL", "env-ua")
    assert trial_models(None, None) == {
        "user_agent_model": "env-ua",
        "runner_agent_model": "env-ua",
    }
    assert trial_models("ua", None) == {
        "user_agent_model": "ua",
        "runner_agent_model": "ua",
    }


def test_persona_and_scenario_metadata_reach_the_resolved_task() -> None:
    import yaml

    document = MINIMAL_EXPERIMENT.replace(
        "  name: alice\n", "  name: alice\n  metadata:\n    age: In their fifties.\n"
    ).replace(
        "  name: task-1\n",
        "  name: task-1\n  metadata:\n    start_prompt: I need a staff guide.\n",
    )
    specification = Specification.model_validate(yaml.safe_load(document))
    (scenario,) = specification.resolved_tasks()
    assert specification.personas[0].metadata == {"age": "In their fifties."}
    assert scenario.metadata == {"start_prompt": "I need a staff guide."}


def test_user_agent_sampling_options_are_left_out_when_unset() -> None:
    assert sampling_options({"USER_AGENT_MAX_TOKENS": ""}) == {}
    assert sampling_options(
        {"USER_AGENT_MAX_TOKENS": "64", "USER_AGENT_TEMPERATURE": "0.5"}
    ) == {"max_tokens": 64, "temperature": 0.5}


def _no_clients(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Record any client that is built. A check must stop before the first one."""
    built: list[object] = []
    monkeypatch.setattr(
        simulation_model_settings, "AsyncOpenAI", lambda **kw: built.append(kw)
    )
    monkeypatch.setattr(
        experiment_module,
        "execute_experiment",
        lambda *_a, **_k: built.append("experiment"),
    )
    return built


def _input_dir(tmp_path: Path, document: str) -> Path:
    input_dir = tmp_path / "input"
    input_dir.mkdir(parents=True)
    (input_dir / "specification.yaml").write_text(document)
    return input_dir


def test_a_command_stops_before_any_client_and_names_only_its_own_roles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY")
    built = _no_clients(monkeypatch)
    monkeypatch.setattr(cli, "_find_project_root", lambda: tmp_path / "project")

    simulate = runner.invoke(
        app,
        [
            "simulate",
            "--input-dir",
            str(_input_dir(tmp_path / "s", MINIMAL_EXPERIMENT)),
        ],
    )
    output = " ".join(simulate.output.split())
    assert simulate.exit_code == 1
    assert "USER_AGENT_API_KEY or OPENAI_API_KEY" in output
    assert "JUDGE_API_KEY" not in output
    assert "docs/guide/models.md" in output

    monkeypatch.setenv("USER_AGENT_API_KEY", "ua-key")
    judged = _input_dir(tmp_path / "r", _spec_with(f"{GRADERS}.EchoJudgeGrader"))
    run = runner.invoke(app, ["run", "--input-dir", str(judged), "--no-tui"])
    output = " ".join(run.output.split())
    assert run.exit_code == 1
    assert "JUDGE_API_KEY or OPENAI_API_KEY" in output
    assert "USER_AGENT_API_KEY" not in output
    assert built == []


def test_a_run_names_each_model_and_its_source(monkeypatch: pytest.MonkeyPatch) -> None:
    import yaml

    for name in ("USER_AGENT_MODEL", "JUDGE_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEFAULT_MODEL", "team-model")
    specification = Specification.model_validate(yaml.safe_load(MINIMAL_EXPERIMENT))
    specification.experiment.defaults.judge_model = "spec-judge"
    roles = [ModelRole.USER_AGENT, ModelRole.JUDGE]

    assert cli._models_line(specification, roles) == (
        "Models: User agent team-model (DEFAULT_MODEL)"
        " · Judge spec-judge (specification.yaml)"
    )
    specification.tasks[0].user_agent_model = "task-model"
    assert cli._models_line(specification, roles).endswith(
        ". 1 Test Case(s) set their own user agent model in specification.yaml"
    )
