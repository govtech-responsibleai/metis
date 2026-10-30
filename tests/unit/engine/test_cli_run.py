"""Tests for the ``metis engine run`` command."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from metis.engine import cli
from metis.engine.cli import EvaluationOutcome, app

runner = CliRunner()

MINIMAL_EXPERIMENT = 'schema_version: 1\nid: test-exp\nrunner_factory_ref: tests.unit.engine.test_runner_ref.StubRunnerFactory\npersonas:\n- id: alice\n  description: test persona\n  name: alice\nscenarios:\n- id: task-1\n  description: test scenario\n  name: task-1\ntarget:\n  name: Test target\n  users: Test users\n  description: Test target\ntasks:\n- id: TC-001\n  scenario_ref: task-1\n  persona_ref: alice\n  fixtures: []\n  num_trials: 1\n  behaviour_refs:\n  - EB-1\nfeatures:\n- id: F-1\n  name: Responses\n  description: Responses\n  behaviours:\n  - id: EB-1\n    name: Respond\n    description: Respond correctly\n    measured: true\n    criteria:\n    - id: AC-1-1\n      name: Check 1\n      description: "Given a request, when the agent responds, then the requirement is met."\n      grader_fqn: tests.unit.engine.graders_for_tests.FixedScoreGrader\n      grader_args: {}\n'


def _write_source(tmp_path: Path) -> Path:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "specification.yaml").write_text(MINIMAL_EXPERIMENT)
    return input_dir


def _write_record_marker(experiment_dir: Path) -> Path:
    record_path = (
        experiment_dir / "outputs" / "trials" / "task-1-alice-1" / "record.json"
    )
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text("{}")
    return experiment_dir


def test_run_composes_phases_and_prints_recovery_command(
    monkeypatch, tmp_path: Path
) -> None:
    input_dir = _write_source(tmp_path)
    experiment_dir = _write_record_marker(tmp_path / "experiment")
    phases: list[str] = []
    simulation_options: dict[str, object] = {}
    evaluation_paths: list[Path] = []
    evaluation_options: dict[str, object] = {}

    def fake_simulation(*_args: object, **kwargs: object) -> Path:
        phases.append("simulation")
        simulation_options.update(kwargs)
        return experiment_dir

    def fake_evaluation(path: Path, **kwargs: object) -> EvaluationOutcome:
        phases.append("evaluation")
        evaluation_paths.append(path)
        evaluation_options.update(kwargs)
        return EvaluationOutcome(1, 0, 1, None)

    monkeypatch.setattr(cli, "_run_simulation", fake_simulation)
    monkeypatch.setattr(cli, "_run_evaluation", fake_evaluation)

    result = runner.invoke(
        app,
        [
            "run",
            "--input-dir",
            str(input_dir),
            "--no-tui",
            "--langfuse-timeout",
            "120",
            "-v",
        ],
    )

    assert result.exit_code == 0
    assert phases == ["simulation", "evaluation"]
    assert simulation_options["no_tui"] is True
    assert simulation_options["resume"] is False
    assert evaluation_paths == [experiment_dir]
    assert evaluation_options == {
        "langfuse_timeout": 120,
        "verbose": 1,
        "quiet": False,
    }
    assert (
        f"Evaluate: metis engine evaluate --experiment-dir {experiment_dir.resolve()}"
        in result.output
    )
    assert (
        f"Resume: metis engine run --resume --experiment-dir {experiment_dir.resolve()}"
        in result.output
    )
    assert "PIPELINE COMPLETE" in result.output
    assert "metisinsightsreport" not in "".join(result.output.split())


def test_run_resume_evaluates_the_resumed_directory(
    monkeypatch, tmp_path: Path
) -> None:
    experiment_dir = _write_record_marker(tmp_path / "experiment")
    simulation_options: dict[str, object] = {}
    evaluation_paths: list[Path] = []

    def fake_simulation(*_args: object, **kwargs: object) -> Path:
        simulation_options.update(kwargs)
        return experiment_dir

    def fake_evaluation(path: Path, **_kwargs: object) -> EvaluationOutcome:
        evaluation_paths.append(path)
        return EvaluationOutcome(
            1, 1, 0, experiment_dir / "outputs" / "reports" / "results.json"
        )

    monkeypatch.setattr(cli, "_run_simulation", fake_simulation)
    monkeypatch.setattr(cli, "_run_evaluation", fake_evaluation)

    result = runner.invoke(
        app,
        ["run", "--resume", "--experiment-dir", str(experiment_dir), "--no-tui"],
    )

    assert result.exit_code == 0
    assert simulation_options["resume"] is True
    assert evaluation_paths == [experiment_dir]
    assert "PIPELINE COMPLETE" in result.output
    assert "metisinsightsreport--results-file" in "".join(result.output.split())


def test_run_zero_simulation_records_exits_one(monkeypatch, tmp_path: Path) -> None:
    input_dir = _write_source(tmp_path)
    experiment_dir = tmp_path / "experiment"
    experiment_dir.mkdir()
    evaluation_called = False

    def fail_if_evaluated(*_args: object, **_kwargs: object) -> EvaluationOutcome:
        nonlocal evaluation_called
        evaluation_called = True
        raise AssertionError("evaluation should not run")

    monkeypatch.setattr(cli, "_run_simulation", lambda *_a, **_k: experiment_dir)
    monkeypatch.setattr(cli, "_run_evaluation", fail_if_evaluated)

    result = runner.invoke(app, ["run", "--input-dir", str(input_dir)])

    assert result.exit_code == 1
    assert not evaluation_called


def test_run_infrastructure_failure_prints_recovery_command(
    monkeypatch, tmp_path: Path
) -> None:
    input_dir = _write_source(tmp_path)
    experiment_dir = _write_record_marker(tmp_path / "experiment")
    monkeypatch.setattr(cli, "_run_simulation", lambda *_a, **_k: experiment_dir)

    def fail_evaluation(*_args: object, **_kwargs: object) -> EvaluationOutcome:
        raise RuntimeError("Langfuse unavailable")

    monkeypatch.setattr(cli, "_run_evaluation", fail_evaluation)

    result = runner.invoke(app, ["run", "--input-dir", str(input_dir)])

    assert result.exit_code != 0
    assert (
        f"Evaluate: metis engine evaluate --experiment-dir {experiment_dir.resolve()}"
        in result.output
    )
