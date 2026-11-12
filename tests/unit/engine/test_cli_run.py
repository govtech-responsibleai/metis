"""Tests for the ``metis engine run`` command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from metis.engine import cli
from metis.engine.cli import EvaluationOutcome, app
from metis.engine.extractor import TraceWaitSettings
from metis.engine.simulation import experiment as experiment_module

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


def test_run_composes_phases_and_names_the_retry_command(
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
            "-c",
            "3",
            "-v",
        ],
    )

    assert result.exit_code == 0
    assert phases == ["simulation", "evaluation"]
    assert simulation_options["no_tui"] is True
    assert simulation_options["resume"] is False
    assert simulation_options["concurrency"] == 3
    assert evaluation_paths == [experiment_dir]
    # One -c sets how many trials are simulated at once and how many sessions are graded
    # at once.
    assert evaluation_options == {
        "trace_wait": TraceWaitSettings(timeout_seconds=120),
        "verbose": 1,
        "quiet": False,
        "concurrency": 3,
        "command": "run",
        "resume": False,
    }
    assert (
        "Grade every trial again: metis engine evaluate --experiment-dir "
        f"{experiment_dir.resolve()}"
    ) in " ".join(result.output.split())
    assert "Resume: metis engine run" not in result.output
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

    evaluation_options: dict[str, object] = {}

    def fake_evaluation(path: Path, **kwargs: object) -> EvaluationOutcome:
        evaluation_paths.append(path)
        evaluation_options.update(kwargs)
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
    assert (evaluation_options["command"], evaluation_options["resume"]) == (
        "run",
        True,
    )
    assert "PIPELINE COMPLETE" in result.output
    assert "metisinsightsreport--results-file" in "".join(result.output.split())


def test_run_stops_before_the_simulation_when_the_timeout_is_shorter_than_the_quiet_window(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LANGFUSE_METIS_QUIET_SECONDS", "30")
    input_dir = _write_source(tmp_path)
    simulations: list[object] = []

    def fake_simulation(*args: object, **_kwargs: object) -> Path:
        simulations.append(args)
        return tmp_path / "experiment"

    monkeypatch.setattr(cli, "_run_simulation", fake_simulation)

    result = runner.invoke(
        app, ["run", "--input-dir", str(input_dir), "--langfuse-timeout", "20"]
    )

    assert result.exit_code == 1
    assert "Set the timeout to 30 seconds or more." in " ".join(result.output.split())
    assert simulations == []


def test_run_zero_simulation_records_exits_one(monkeypatch, tmp_path: Path) -> None:
    input_dir = _write_source(tmp_path)
    evaluation_called = False

    def fail_if_evaluated(*_args: object, **_kwargs: object) -> EvaluationOutcome:
        nonlocal evaluation_called
        evaluation_called = True
        raise AssertionError("evaluation should not run")

    monkeypatch.setattr(cli, "find_project_root", lambda: tmp_path / "project")
    monkeypatch.setattr(cli, "_configure_process_logging", lambda *_a, **_k: None)
    monkeypatch.setattr(experiment_module, "execute_experiment", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "_run_evaluation", fail_if_evaluated)

    result = runner.invoke(app, ["run", "--input-dir", str(input_dir), "--no-tui"])

    assert result.exit_code == 1
    assert "No trial records found." in result.output
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


@pytest.mark.parametrize("value", ["0", "-1"])
def test_run_rejects_a_concurrency_below_one(
    monkeypatch, tmp_path: Path, value: str
) -> None:
    def fail_if_simulated(*_args: object, **_kwargs: object) -> Path:
        raise AssertionError("a rejected option must not start the simulation")

    monkeypatch.setattr(cli, "_run_simulation", fail_if_simulated)

    result = runner.invoke(
        app, ["run", "--input-dir", str(tmp_path), "--no-tui", "-c", value]
    )

    assert result.exit_code == 2
    assert isinstance(result.exception, SystemExit)


# --- run --resume: the evaluation half resumes too ----------------------------------------


def _resumable_run(tmp_path: Path, stop_reasons: list[str]) -> Path:
    """A run folder with one complete simulation record per trial and no results."""
    from tests.unit.engine.test_cli_evaluate import (
        MINIMAL_EXPERIMENT as EVALUATED_EXPERIMENT,
    )
    from tests.unit.engine.test_cli_evaluate import _write_experiment_dir, _write_record

    output = _write_experiment_dir(
        tmp_path,
        content=EVALUATED_EXPERIMENT.replace(
            "num_trials: 1", f"num_trials: {len(stop_reasons)}"
        ),
    )
    (output / "inputs" / "fixtures").mkdir()
    for index, stop_reason in enumerate(stop_reasons, start=1):
        path = _write_record(
            output, run_name=f"TC-001-alice-{index}", session_id=f"session-{index}"
        )
        data = json.loads(path.read_text())
        data["outcome"]["stop_reason"] = stop_reason
        path.write_text(json.dumps(data))
    return output


def _simulate_with_fake_experiment(monkeypatch, tmp_path: Path) -> list[str]:
    """Run the real simulation half; the fake experiment rewrites each redone trial's
    record as complete. Returns the trial folders it simulated."""
    from metis.core.trials import TrialRecord

    simulated: list[str] = []

    def fake_execute_experiment(*_args: object, **kwargs: object) -> None:
        output_dir: Path = kwargs["output_dir"]  # type: ignore[assignment]
        for _scenario, _persona, trial_index in kwargs["trial_plan"]:  # type: ignore[union-attr]
            folder = f"TC-001-alice-{trial_index}"
            simulated.append(folder)
            path = output_dir / "outputs" / "trials" / folder / "record.json"
            record = TrialRecord.load_file(path)
            record.outcome.stop_reason = "goal_achieved"
            path.write_text(record.model_dump_json())

    monkeypatch.setattr(cli, "_find_project_root", lambda: tmp_path / "project")
    monkeypatch.setattr(cli, "_configure_process_logging", lambda *_a, **_k: None)
    monkeypatch.setattr(
        experiment_module, "execute_experiment", fake_execute_experiment
    )
    return simulated


def test_run_resume_after_an_interrupt_in_grading_grades_only_the_rest(
    monkeypatch, tmp_path: Path
) -> None:
    from tests.unit.engine.test_cli_evaluate import _patch_evaluation
    from tests.unit.engine.test_cli_evaluate_resume import write_trial_file

    output = _resumable_run(tmp_path, ["goal_achieved", "goal_achieved"])
    write_trial_file(output, "TC-001-alice-1", session_id="session-1")
    simulated = _simulate_with_fake_experiment(monkeypatch, tmp_path)
    calls = _patch_evaluation(monkeypatch)

    result = runner.invoke(
        app, ["run", "--resume", "--experiment-dir", str(output), "--no-tui"]
    )

    assert result.exit_code == 0, result.output
    assert simulated == []
    assert [call["session_id"] for call in calls] == ["session-2"]
    assert "PIPELINE COMPLETE — 2 run(s), 0 failed" in result.output


def test_run_resume_that_resimulates_a_trial_grades_every_trial(
    monkeypatch, tmp_path: Path
) -> None:
    from tests.unit.engine.test_cli_evaluate import _patch_evaluation
    from tests.unit.engine.test_cli_evaluate_resume import write_trial_file

    output = _resumable_run(tmp_path, ["goal_achieved", "system_error"])
    write_trial_file(output, "TC-001-alice-1", session_id="session-1")
    write_trial_file(output, "TC-001-alice-2", session_id="session-2")
    simulated = _simulate_with_fake_experiment(monkeypatch, tmp_path)
    calls = _patch_evaluation(monkeypatch)

    result = runner.invoke(
        app, ["run", "--resume", "--experiment-dir", str(output), "--no-tui"]
    )

    assert result.exit_code == 0, result.output
    assert simulated == ["TC-001-alice-2"]
    assert sorted(call["session_id"] for call in calls) == ["session-1", "session-2"]


def test_run_resume_with_nothing_left_to_evaluate_logs_the_evaluating_phase(
    monkeypatch, tmp_path: Path
) -> None:
    from tests.unit.engine.test_cli_evaluate import _patch_evaluation

    output = _resumable_run(tmp_path, ["goal_achieved", "goal_achieved"])
    simulated = _simulate_with_fake_experiment(monkeypatch, tmp_path)
    _patch_evaluation(monkeypatch)
    done = runner.invoke(app, ["evaluate", "--experiment-dir", str(output)])
    assert done.exit_code == 0, done.output
    kept = [*(output / "outputs").rglob("*"), output / "logs" / "evaluate.log"]
    kept = {path: path.read_bytes() for path in kept if path.is_file()}

    result = runner.invoke(
        app, ["run", "--resume", "--experiment-dir", str(output), "--no-tui"]
    )

    assert result.exit_code == 0, result.output
    assert simulated == []
    lines = [
        json.loads(line)
        for line in (output / "logs" / "events.jsonl").read_text().splitlines()
    ]
    assert [(line["phase"], line["status"]) for line in lines[-2:]] == [
        ("evaluating", "started"),
        ("evaluating", "completed"),
    ]
    assert (lines[-2]["total"], lines[-2]["done"]) == (2, 2)
    assert {path: path.read_bytes() for path in kept} == kept
