"""Tests for the ``metis engine evaluate`` command."""

from __future__ import annotations

import asyncio
import contextlib
import os
import shlex
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from metis.core.reporting import EvaluationResults
from metis.core.traces import GradingInput, Observation, SessionTraces, Trace
from metis.core.trials import GraderRef, TrialConfig, TrialOutcome, TrialRecord
from metis.engine import cli
from metis.engine.cli import EvaluationOutcome, app
from metis.engine.extractor.langfuse import UnsupportedTraceError

runner = CliRunner()

MINIMAL_EXPERIMENT = 'schema_version: 1\nid: test-exp\nrunner_factory_ref: tests.unit.engine.test_runner_ref.StubRunnerFactory\npersonas:\n- id: alice\n  description: test persona\n  name: alice\nscenarios:\n- id: task-1\n  description: test scenario\n  name: task-1\ntarget:\n  name: Test target\n  users: Test users\n  description: Test target\ntasks:\n- id: TC-001\n  scenario_ref: task-1\n  persona_ref: alice\n  fixtures: []\n  num_trials: 1\n  behaviour_refs:\n  - EB-1\nfeatures:\n- id: F-1\n  name: Responses\n  description: Responses\n  behaviours:\n  - id: EB-1\n    name: Respond\n    description: Respond correctly\n    measured: true\n    criteria:\n    - id: AC-1-1\n      name: Check 1\n      description: "The response meets the requirement."\n      grader_fqn: tests.unit.engine.graders_for_tests.FixedScoreGrader\n      grader_args: {}\n'


def _write_snapshot(experiment_dir: Path, content: str = MINIMAL_EXPERIMENT) -> Path:
    inputs_dir = experiment_dir / "inputs"
    inputs_dir.mkdir(parents=True)
    (inputs_dir / "specification.yaml").write_text(content)
    return experiment_dir


def _write_record(
    experiment_dir: Path,
    *,
    run_name: str = "task-1-alice-1",
    session_id: str = "session-1",
) -> Path:
    record = TrialRecord(
        config=TrialConfig(
            persona="alice",
            scenario="task-1",
            task_id="TC-001",
            grader_refs=[
                GraderRef(
                    criterion_id="AC-1-1",
                    fqn="tests.unit.engine.graders_for_tests.FixedScoreGrader",
                    args={},
                )
            ],
        ),
        outcome=TrialOutcome(
            stop_reason="goal_achieved",
            simulated_turns_completed=1,
            duration_seconds=1.0,
        ),
        target_session_id=session_id,
    )
    record_path = experiment_dir / "outputs" / "trials" / run_name / "record.json"
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(record.model_dump_json())
    return record_path


def _session(session_id: str = "session-1", traces: int = 1) -> GradingInput:
    return GradingInput(
        traces=tuple(
            Trace(
                id=f"{session_id}-t{i}",
                session_id=session_id,
                observations=(
                    Observation(id=f"o{i}", trace_id=f"{session_id}-t{i}", output="ok"),
                ),
            )
            for i in range(traces)
        )
    )


def _write_experiment_dir(
    root: Path,
    *,
    name: str = "test-exp-20260101-010101",
    content: str = MINIMAL_EXPERIMENT,
) -> Path:
    """Write a simulation output directory with its frozen input snapshot."""
    experiment_dir = root / "experiments" / "execute" / name
    experiment_dir.mkdir(parents=True)
    _write_snapshot(experiment_dir, content)
    return experiment_dir


def _compact(value: str) -> str:
    return "".join(value.split())


def test_evaluate_scores_the_named_experiment_directory(
    monkeypatch, tmp_path: Path
) -> None:
    target = _write_experiment_dir(tmp_path, name="test-exp-20260101-010101")
    # A second output exists for the same experiment id. The command must use the
    # path it is given, and must not choose one by timestamp.
    _write_experiment_dir(tmp_path, name="test-exp-20260102-010101")

    calls: list[Path] = []

    def fake_evaluation(
        path: Path,
        *,
        langfuse_timeout: int,
        verbose: int,
        quiet: bool,
        concurrency: int,
    ) -> EvaluationOutcome:
        calls.append(path)
        assert langfuse_timeout == 120
        assert verbose == 1
        assert not quiet
        assert concurrency == 3
        return EvaluationOutcome(1, 1, 0, None)

    monkeypatch.setattr(cli, "_run_evaluation", fake_evaluation)
    result = runner.invoke(
        app,
        [
            "evaluate",
            "--experiment-dir",
            str(target),
            "--langfuse-timeout",
            "120",
            "-c",
            "3",
            "-v",
        ],
    )

    assert result.exit_code == 0
    assert calls == [target.resolve()]
    assert f"Selectedexperiment:{_compact(str(target.resolve()))}" in _compact(
        result.output
    )


def test_evaluate_rejects_a_path_that_does_not_exist(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["evaluate", "--experiment-dir", str(tmp_path / "missing")]
    )

    assert result.exit_code == 1
    assert "doesnotexist" in _compact(result.output)


def test_evaluate_rejects_a_path_that_is_not_a_directory(tmp_path: Path) -> None:
    not_a_directory = tmp_path / "record.json"
    not_a_directory.write_text("{}")

    result = runner.invoke(app, ["evaluate", "--experiment-dir", str(not_a_directory)])

    assert result.exit_code == 1
    assert "doesnotexist" in _compact(result.output)


def test_evaluate_rejects_a_directory_without_an_input_snapshot(tmp_path: Path) -> None:
    unrelated_dir = tmp_path / "not-an-experiment"
    unrelated_dir.mkdir()

    result = runner.invoke(app, ["evaluate", "--experiment-dir", str(unrelated_dir)])

    assert result.exit_code == 1
    assert "isnotasimulationoutputdirectory" in _compact(result.output)
    assert "metisenginesimulate" in _compact(result.output)


def test_evaluate_fails_when_the_input_snapshot_has_no_specification_file(
    tmp_path: Path,
) -> None:
    experiment_dir = tmp_path / "experiments" / "execute" / "test-exp-20260101-010101"
    (experiment_dir / "inputs").mkdir(parents=True)

    result = runner.invoke(app, ["evaluate", "--experiment-dir", str(experiment_dir)])

    assert result.exit_code != 0
    assert _compact(str(experiment_dir.resolve())) in _compact(result.output)
    assert "specification.yaml" in result.output


def test_evaluate_fails_for_a_malformed_trial_record(tmp_path: Path) -> None:
    experiment_dir = _write_experiment_dir(tmp_path)
    malformed_record = experiment_dir / "outputs" / "trials" / "run-1" / "record.json"
    malformed_record.parent.mkdir(parents=True)
    malformed_record.write_text("{}")

    result = runner.invoke(app, ["evaluate", "--experiment-dir", str(experiment_dir)])

    assert result.exit_code != 0
    assert "trial record" in result.output
    assert (
        "EVALUATION FAILED — failed to load trial record"
        in (experiment_dir / "logs" / "evaluate.log").read_text()
    )


def test_evaluate_with_no_run_records_is_a_noop(tmp_path: Path) -> None:
    experiment_dir = _write_experiment_dir(tmp_path)

    result = runner.invoke(app, ["evaluate", "--experiment-dir", str(experiment_dir)])

    assert result.exit_code == 0
    assert "nothing to evaluate" in result.output
    assert (
        "EVALUATION COMPLETED — 0 records"
        in (experiment_dir / "logs" / "evaluate.log").read_text()
    )


def _patch_evaluation(monkeypatch, *, traces: int = 1) -> list[dict[str, Any]]:
    """Fake Langfuse: every session has ``traces`` traces. Returns the fetch calls made."""
    calls: list[dict[str, Any]] = []

    async def fetch(session_id: str, _langfuse: object, **kwargs: Any) -> GradingInput:
        calls.append({"session_id": session_id, **kwargs})
        return _session(session_id, traces)

    monkeypatch.setattr("metis.engine.extractor.get_langfuse_client", lambda: object())
    monkeypatch.setattr("metis.engine.extractor.fetch_session", fetch)
    return calls


def test_evaluation_writes_results_file_and_prints_report_command(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_record(output)
    _patch_evaluation(monkeypatch)

    first = runner.invoke(app, ["evaluate", "--experiment-dir", str(output)])
    second = runner.invoke(app, ["evaluate", "--experiment-dir", str(output)])

    assert first.exit_code == 0
    assert second.exit_code == 0
    results_file = output.resolve() / "outputs" / "reports" / "results.json"
    results = EvaluationResults.load_file(results_file)
    assert results.run_id == "report"
    assert results.schema_version == 1
    (record,) = results.records
    assert (record.session_id, record.task_id, record.criterion_id) == (
        "session-1",
        "TC-001",
        "AC-1-1",
    )
    assert record.grader_args == {"threshold": 0.5, "score": 1.0}
    assert [(r.outcome, r.score) for r in record.results] == [("passed", 1.0)]
    # Engine no longer builds the report; insights does.
    assert not (output / "outputs" / "reports" / "report.json").exists()
    assert not (output / "outputs" / "reports" / "report.html").exists()
    command = shlex.join(
        ["metis", "insights", "report", "--results-file", str(results_file)]
    )
    assert _compact(f"Report: {command}") in _compact(second.output)
    evaluation_log = (output / "logs" / "evaluate.log").read_text()
    assert evaluation_log.count("EVALUATION STARTED") == 1
    assert "RESULTS WRITTEN" in evaluation_log


def test_report_command_is_shell_quoted_for_paths_with_spaces(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path, name="test exp 20260101-010101")
    _write_record(output)
    _patch_evaluation(monkeypatch)

    result = runner.invoke(app, ["evaluate", "--experiment-dir", str(output)])

    assert result.exit_code == 0
    results_file = output.resolve() / "outputs" / "reports" / "results.json"
    quoted = shlex.join(["--results-file", str(results_file)])
    assert "'" in quoted
    assert _compact(quoted) in _compact(result.output)


def test_evaluation_with_no_successful_records_writes_no_results(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_record(output)
    _patch_evaluation(monkeypatch, traces=0)

    result = runner.invoke(app, ["evaluate", "--experiment-dir", str(output)])

    assert result.exit_code == 0
    assert "No traces found in Langfuse" in result.output
    assert not (output / "outputs" / "reports" / "results.json").exists()
    assert "metisinsightsreport" not in _compact(result.output)


def test_reevaluation_with_no_successes_removes_stale_results(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_record(output)
    _patch_evaluation(monkeypatch)
    runner.invoke(app, ["evaluate", "--experiment-dir", str(output)])
    assert (output / "outputs" / "reports" / "results.json").exists()
    _patch_evaluation(monkeypatch, traces=0)

    result = runner.invoke(app, ["evaluate", "--experiment-dir", str(output)])

    assert result.exit_code == 0
    # A results file from an earlier evaluation must not outlive one that scored
    # nothing, or `metis insights report` would re-stamp stale scores as current.
    assert not (output / "outputs" / "reports" / "results.json").exists()


def test_report_command_keeps_square_brackets_in_paths(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path, name="test [draft] 20260101-010101")
    _write_record(output)
    _patch_evaluation(monkeypatch)

    result = runner.invoke(app, ["evaluate", "--experiment-dir", str(output)])

    assert result.exit_code == 0
    results_file = output.resolve() / "outputs" / "reports" / "results.json"
    command = shlex.join(
        ["metis", "insights", "report", "--results-file", str(results_file)]
    )
    assert _compact(f"Report: {command}") in _compact(result.output)


def test_evaluation_progress_advances_for_success_and_soft_failure(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    output = _write_snapshot(tmp_path / "experiment")
    _write_record(output, run_name="run-1", session_id="session-1")
    _write_record(output, run_name="run-2", session_id="session-2")

    events: list[tuple[str, Any]] = []

    class FakeProgress:
        def __enter__(self):
            events.append(("enter", None))
            return self

        def __exit__(self, *_args: object) -> None:
            events.append(("exit", None))

        def add_task(self, description: str, *, total: int) -> int:
            events.append(("add", (description, total)))
            return 1

        def update(self, _task_id: int, **kwargs: object) -> None:
            events.append(("update", kwargs))

    monkeypatch.setattr(cli.sys.stderr, "isatty", lambda: True)
    monkeypatch.setattr(cli, "_create_evaluation_progress", FakeProgress)
    monkeypatch.setattr("metis.engine.extractor.get_langfuse_client", lambda: object())

    async def fetch(session_id: str, *_args: object, **_kwargs: object) -> GradingInput:
        if session_id == "session-2":
            raise RuntimeError("trace unavailable")
        return _session(session_id)

    monkeypatch.setattr("metis.engine.extractor.fetch_session", fetch)

    outcome = cli._run_evaluation(
        output,
        langfuse_timeout=90,
        verbose=0,
        quiet=False,
    )

    updates = [payload for event, payload in events if event == "update"]
    descriptions = [
        update["description"] for update in updates if "description" in update
    ]
    advances = [update.get("advance", 0) for update in updates]

    assert outcome.successful_records == 1
    assert outcome.failed_records == 1
    assert "alice x task-1 — extracting" in descriptions
    assert "alice x task-1 — evaluating" in descriptions
    assert "alice x task-1 — failed" in descriptions
    assert sum(advances) == 2
    assert events[0][0] == "enter"
    assert events[-1][0] == "exit"
    assert (
        "WARNING: RECORD 2/2 alice x task-1 — Evaluation failed: trace unavailable"
        in capsys.readouterr().out
    )
    evaluation_log = (output / "logs" / "evaluate.log").read_text()
    assert "alice x task-1 — EXTRACTING" in evaluation_log
    assert "alice x task-1 — EVALUATING" in evaluation_log
    assert "alice x task-1 — DONE" in evaluation_log
    assert "alice x task-1 — FAILED — trace unavailable" in evaluation_log
    assert (
        '"fqn": "tests.unit.engine.graders_for_tests.FixedScoreGrader"'
        in evaluation_log
    )
    assert '"criterion_id": "AC-1-1"' in evaluation_log
    assert '"outcome": "passed"' in evaluation_log
    assert '"score": 1.0' in evaluation_log
    assert '"reason": "1 trace(s)"' in evaluation_log
    assert "GRADER RESULTS — record=alice x task-1 count=1" in evaluation_log

    cli._update_evaluation_progress(
        None,
        None,
        record_number=1,
        total_records=2,
        label="alice x task-1",
        phase="extracting",
    )
    assert "Evaluation 1/2: alice x task-1 — extracting" in capsys.readouterr().out


def test_an_unsupported_trace_fails_its_session_and_the_rest_are_graded(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """No special handling in evaluate; the per-session catch already covers it."""
    output = _write_experiment_dir(tmp_path)
    _write_record(output, run_name="run-1", session_id="sess-old")
    _write_record(output, run_name="run-2", session_id="sess-new")
    reason = (
        "Session `sess-old` can't be graded: trace `t1` was recorded before this "
        "Langfuse server's v4 upgrade (synthetic root `t-t1`). "
        "Re-run the trial to grade it."
    )
    fetched: list[str] = []

    async def fetch(session_id: str, *_args: object, **_kwargs: object) -> GradingInput:
        fetched.append(session_id)
        if session_id == "sess-old":
            raise UnsupportedTraceError(reason)
        return _session(session_id)

    monkeypatch.setattr("metis.engine.extractor.get_langfuse_client", lambda: object())
    monkeypatch.setattr("metis.engine.extractor.fetch_session", fetch)

    result = runner.invoke(app, ["evaluate", "--experiment-dir", str(output)])

    assert result.exit_code == 0
    assert sorted(fetched) == ["sess-new", "sess-old"]
    results = EvaluationResults.load_file(
        output / "outputs" / "reports" / "results.json"
    )
    assert {record.session_id for record in results.records} == {"sess-new"}
    assert reason in _compact(result.output) or _compact(reason) in _compact(
        result.output
    )
    evaluation_log = (output / "logs" / "evaluate.log").read_text()
    assert f"FAILED — {reason}" in evaluation_log


# ── grading through the new contract ────────────────────────────────────────

GRADERS = "tests.unit.engine.graders_for_tests"


def _spec_with(fqn: str, grader_args: str = "{}", *, defaults: str = "") -> str:
    """MINIMAL_EXPERIMENT with its one criterion pointed at ``fqn``."""
    spec = MINIMAL_EXPERIMENT.replace(
        f"grader_fqn: {GRADERS}.FixedScoreGrader\n      grader_args: {{}}\n",
        f"grader_fqn: {fqn}\n      grader_args: {grader_args}\n",
    )
    assert spec != MINIMAL_EXPERIMENT or fqn.endswith("FixedScoreGrader")
    return defaults + spec


def _write_judge_record(experiment_dir: Path, fqn: str) -> None:
    record = TrialRecord(
        config=TrialConfig(
            task_id="TC-001",
            persona="alice",
            scenario="task-1",
            grader_refs=[GraderRef(criterion_id="AC-1-1", fqn=fqn, args={})],
        ),
        outcome=TrialOutcome(
            stop_reason="goal_achieved",
            simulated_turns_completed=1,
            duration_seconds=1.0,
        ),
        target_session_id="session-1",
    )
    path = experiment_dir / "outputs" / "trials" / "run-1" / "record.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.model_dump_json())


def test_a_failing_score_is_recorded_as_failed(monkeypatch, tmp_path: Path) -> None:
    output = _write_experiment_dir(
        tmp_path, content=_spec_with(f"{GRADERS}.FixedScoreGrader", "{score: 0.2}")
    )
    _write_record(output)
    _patch_evaluation(monkeypatch)

    result = runner.invoke(app, ["evaluate", "--experiment-dir", str(output)])

    assert result.exit_code == 0, result.output
    (record,) = EvaluationResults.load_file(
        output / "outputs" / "reports" / "results.json"
    ).records
    assert [(r.outcome, r.score) for r in record.results] == [("failed", 0.2)]
    assert record.grader_args == {"threshold": 0.5, "score": 0.2}


def test_criteria_keep_snapshot_settings_and_reuse_instances_across_sessions(
    monkeypatch, tmp_path: Path
) -> None:
    import yaml

    from tests.unit.engine.graders_for_tests import FixedScoreGrader

    specification = yaml.safe_load(MINIMAL_EXPERIMENT)
    behaviour = specification["features"][0]["behaviours"][0]
    behaviour["criteria"][0]["grader_args"] = {"score": 0.9}
    behaviour["criteria"].append(
        {
            "id": "AC-1-2",
            "name": "Second assessment",
            "description": "The response satisfies the second requirement.",
            "grader_fqn": f"{GRADERS}.FixedScoreGrader",
            "grader_args": {"score": 0.2, "threshold": 0.3},
        }
    )
    specification["features"][0]["behaviours"].append(
        {
            "id": "EB-DORMANT",
            "name": "Unused assessment",
            "description": "This behaviour is outside the selected task.",
            "measured": False,
            "criteria": [
                {
                    "id": "AC-DORMANT",
                    "name": "Unused criterion",
                    "description": "The session meets an unused requirement.",
                    "grader_fqn": "unavailable.module.Grader",
                }
            ],
        }
    )
    output = _write_experiment_dir(tmp_path, content=yaml.safe_dump(specification))
    for index in (1, 2):
        path = _write_record(
            output, run_name=f"run-{index}", session_id=f"session-{index}"
        )
        trial = TrialRecord.load_file(path)
        trial.config.grader_refs = [
            GraderRef(
                criterion_id=cid, fqn="unavailable.trial.Grader", args={"score": 1.0}
            )
            for cid in ("AC-1-2", "AC-1-1")
        ]
        path.write_text(trial.model_dump_json())
    _patch_evaluation(monkeypatch)
    calls = []
    grade = FixedScoreGrader.grade

    async def observe(self, grading_input, llm):
        calls.append(self)
        return await grade(self, grading_input, llm)

    monkeypatch.setattr(FixedScoreGrader, "grade", observe)
    result = runner.invoke(app, ["evaluate", "--experiment-dir", str(output)])

    assert result.exit_code == 0, result.output
    records = EvaluationResults.load_file(
        output / "outputs" / "reports" / "results.json"
    ).records
    assert [(record.session_id, record.criterion_id) for record in records] == [
        ("session-1", "AC-1-2"),
        ("session-1", "AC-1-1"),
        ("session-2", "AC-1-2"),
        ("session-2", "AC-1-1"),
    ]
    assert [record.grader_args for record in records] == [
        {"threshold": 0.3, "score": 0.2},
        {"threshold": 0.5, "score": 0.9},
    ] * 2
    assert all(record.grader_fqn == f"{GRADERS}.FixedScoreGrader" for record in records)
    assert [record.results[0].outcome for record in records] == ["failed", "passed"] * 2
    assert calls[0] is calls[2]
    assert calls[1] is calls[3]
    assert calls[0] is not calls[1]


def test_every_session_is_fetched_with_its_artifacts_and_timeout(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_record(output, run_name="run-1", session_id="session-1")
    _write_record(output, run_name="run-2", session_id="session-2")
    calls = _patch_evaluation(monkeypatch)

    runner.invoke(
        app, ["evaluate", "--experiment-dir", str(output), "--langfuse-timeout", "7"]
    )

    assert sorted(c["session_id"] for c in calls) == ["session-1", "session-2"]
    assert all(c["retry_timeout"] == 7 for c in calls)
    assert all(c["experiment_root"] == output.resolve() for c in calls)
    assert all(c["artifacts"] == [] for c in calls)
    results = EvaluationResults.load_file(
        output / "outputs" / "reports" / "results.json"
    )
    assert len(results.records) == 2


def test_code_graders_need_no_judge_credentials(monkeypatch, tmp_path: Path) -> None:
    for name in ("JUDGE_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    output = _write_experiment_dir(tmp_path)
    _write_record(output)
    _patch_evaluation(monkeypatch)

    result = runner.invoke(app, ["evaluate", "--experiment-dir", str(output)])

    assert result.exit_code == 0, result.output
    assert (output / "outputs" / "reports" / "results.json").exists()


def test_model_based_grader_without_credentials_fails_before_any_fetch(
    monkeypatch, tmp_path: Path
) -> None:
    for name in ("JUDGE_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    fqn = f"{GRADERS}.EchoJudgeGrader"
    output = _write_experiment_dir(tmp_path, content=_spec_with(fqn))
    _write_judge_record(output, fqn)
    calls = _patch_evaluation(monkeypatch)

    result = runner.invoke(app, ["evaluate", "--experiment-dir", str(output)])

    assert result.exit_code == 1
    assert "AC-1-1" in result.output
    output = _compact(result.output)
    assert "JUDGE_API_KEY or OPENAI_API_KEY" in " ".join(result.output.split())
    assert "metisengineevaluate" in output
    assert "docs/guide/models.md" in output
    assert "Settingsfileread:" in output
    assert calls == []


def test_judge_model_comes_from_the_spec_defaults(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("JUDGE_API_KEY", "test-key")
    monkeypatch.setenv("JUDGE_MODEL", "from-env")
    fqn = f"{GRADERS}.EchoJudgeGrader"
    output = _write_experiment_dir(
        tmp_path,
        content=_spec_with(fqn, defaults="defaults:\n  judge_model: from-spec\n"),
    )
    _write_judge_record(output, fqn)
    _patch_evaluation(monkeypatch)

    result = runner.invoke(app, ["evaluate", "--experiment-dir", str(output)])

    assert result.exit_code == 0, result.output
    (record,) = EvaluationResults.load_file(
        output / "outputs" / "reports" / "results.json"
    ).records
    assert record.grader_args["model"] == "from-spec"
    assert record.results[0].reason == "from-spec"


def test_a_grader_that_raises_does_not_fail_the_record(
    monkeypatch, tmp_path: Path
) -> None:
    """A grader bug is one errored result; the record still counts as evaluated."""
    output = _write_experiment_dir(tmp_path)
    _write_record(output)
    _patch_evaluation(monkeypatch)

    async def explode(*_args: object) -> object:
        raise RuntimeError("boom")

    from tests.unit.engine.graders_for_tests import FixedScoreGrader

    monkeypatch.setattr(FixedScoreGrader, "grade", explode)

    result = runner.invoke(app, ["evaluate", "--experiment-dir", str(output)])

    assert result.exit_code == 0, result.output
    (record,) = EvaluationResults.load_file(
        output / "outputs" / "reports" / "results.json"
    ).records
    assert [r.outcome for r in record.results] == ["errored"]
    assert "boom" in record.results[0].reason
    log = (output / "logs" / "evaluate.log").read_text()
    assert '"outcome": "errored"' in log


def test_record_criteria_missing_from_the_snapshot_are_reported(
    monkeypatch, tmp_path: Path
) -> None:
    """A record graded against an edited snapshot must not silently lose criteria."""
    output = _write_experiment_dir(tmp_path)
    record = TrialRecord(
        config=TrialConfig(
            task_id="TC-001",
            persona="alice",
            scenario="task-1",
            grader_refs=[
                GraderRef(criterion_id="AC-1-1", fqn=f"{GRADERS}.FixedScoreGrader"),
                GraderRef(criterion_id="AC-GONE", fqn=f"{GRADERS}.FixedScoreGrader"),
            ],
        ),
        outcome=TrialOutcome(
            stop_reason="goal_achieved",
            simulated_turns_completed=1,
            duration_seconds=1.0,
        ),
        target_session_id="session-1",
    )
    path = output / "outputs" / "trials" / "run-1" / "record.json"
    path.parent.mkdir(parents=True)
    path.write_text(record.model_dump_json())
    _patch_evaluation(monkeypatch)

    result = runner.invoke(app, ["evaluate", "--experiment-dir", str(output)])

    assert result.exit_code == 0, result.output
    assert "AC-GONE" in result.output
    assert (
        "UNKNOWN CRITERIA — AC-GONE" in (output / "logs" / "evaluate.log").read_text()
    )
    (graded,) = EvaluationResults.load_file(
        output / "outputs" / "reports" / "results.json"
    ).records
    assert graded.criterion_id == "AC-1-1"


def test_evaluate_saves_each_sessions_traces(monkeypatch, tmp_path: Path) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_record(output)
    _patch_evaluation(monkeypatch, traces=2)

    result = runner.invoke(app, ["evaluate", "--experiment-dir", str(output)])

    assert result.exit_code == 0, result.output
    saved = SessionTraces.load_file(output / "outputs" / "traces" / "session-1.json")
    assert saved.session_id == "session-1"
    assert [trace.id for trace in saved.to_traces()] == [
        "session-1-t0",
        "session-1-t1",
    ]


def test_evaluate_clears_traces_from_an_earlier_run(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_record(output)
    stale = output / "outputs" / "traces" / "stale-session.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("{}")
    _patch_evaluation(monkeypatch)

    result = runner.invoke(app, ["evaluate", "--experiment-dir", str(output)])

    assert result.exit_code == 0, result.output
    assert not stale.exists()
    assert (output / "outputs" / "traces" / "session-1.json").exists()


def test_session_without_traces_gets_no_file(monkeypatch, tmp_path: Path) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_record(output)
    _patch_evaluation(monkeypatch, traces=0)

    result = runner.invoke(app, ["evaluate", "--experiment-dir", str(output)])

    assert result.exit_code == 0, result.output
    assert not list((output / "outputs" / "traces").glob("*.json"))


def test_failed_trace_write_warns_and_still_grades(monkeypatch, tmp_path: Path) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_record(output)
    _patch_evaluation(monkeypatch)

    def refuse(self: SessionTraces, path: Path) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(SessionTraces, "save", refuse)

    result = runner.invoke(app, ["evaluate", "--experiment-dir", str(output)])

    assert result.exit_code == 0, result.output
    assert (output / "outputs" / "reports" / "results.json").exists()
    assert "TRACES NOT SAVED" in (output / "logs" / "evaluate.log").read_text()


def test_unserialisable_payload_does_not_fail_the_record(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_record(output)
    bad = Observation.model_validate(
        {"id": "o1", "traceId": "t1", "output": "lone surrogate \ud800 here"}
    )
    session = GradingInput(traces=(Trace.from_observations("t1", "session-1", [bad]),))
    monkeypatch.setattr("metis.engine.extractor.get_langfuse_client", lambda: object())

    async def fetch(*_args: object, **_kwargs: object) -> GradingInput:
        return session

    monkeypatch.setattr("metis.engine.extractor.fetch_session", fetch)

    result = runner.invoke(app, ["evaluate", "--experiment-dir", str(output)])

    assert result.exit_code == 0, result.output
    (graded,) = EvaluationResults.load_file(
        output / "outputs" / "reports" / "results.json"
    ).records
    assert graded.criterion_id == "AC-1-1"
    assert "TRACES NOT SAVED" in (output / "logs" / "evaluate.log").read_text()


# --- _evaluate_one: the per-record unit that the evaluation loop calls ---------------------


def _evaluation_context(tmp_path: Path, fetch: Any) -> tuple[Any, Path]:
    """The shared state ``_evaluate_one`` needs, built from a real specification snapshot."""
    from metis.engine.evaluation import build_grader
    from metis.engine.logging import EvaluationLogger
    from metis.library.grader import LLMSettings

    experiment_dir = _write_experiment_dir(tmp_path)
    specification = cli._load_evaluation_specification(experiment_dir)
    criteria_by_id = {c.id: c for b in specification.behaviours() for c in b.criteria}
    graders = {
        cid: build_grader(c, default_judge_model="unused", env={})
        for cid, c in criteria_by_id.items()
    }

    class FakeLangfuse:
        pass

    context = cli._EvaluationContext(
        experiment_dir=experiment_dir,
        criteria_by_id=criteria_by_id,
        graders=graders,
        llm=LLMSettings(client=cli._NoJudgeClient()),  # type: ignore[arg-type]
        langfuse=FakeLangfuse(),  # type: ignore[arg-type]
        langfuse_timeout=0,
        evaluation_log=EvaluationLogger(experiment_dir / "logs"),
        total_records=1,
        concurrency=1,
        semaphore=asyncio.Semaphore(1),
        running=cli._RunningCount(),
    )
    return context, experiment_dir


def _trial_record(experiment_dir: Path, *, session_id: str | None) -> TrialRecord:
    path = _write_record(experiment_dir, session_id=session_id or "unused")
    record = TrialRecord.model_validate_json(path.read_text())
    return record.model_copy(update={"target_session_id": session_id})


@pytest.mark.asyncio
async def test_evaluate_one_returns_the_graded_records(
    monkeypatch, tmp_path: Path
) -> None:
    async def fetch(session_id: str, *_args: object, **_kwargs: object) -> GradingInput:
        return _session(session_id)

    monkeypatch.setattr("metis.engine.extractor.fetch_session", fetch)
    context, experiment_dir = _evaluation_context(tmp_path, fetch)
    record = _trial_record(experiment_dir, session_id="session-1")
    phases: list[str] = []

    result = await cli._evaluate_one(
        record, number=1, context=context, phase=lambda name, **_: phases.append(name)
    )

    assert result.failure_reason is None
    assert [r.criterion_id for r in result.records] == ["AC-1-1"]
    assert phases == ["extracting", "evaluating", "done"]


@pytest.mark.asyncio
async def test_evaluate_one_returns_a_failure_instead_of_raising(
    monkeypatch, tmp_path: Path
) -> None:
    async def fetch(*_args: object, **_kwargs: object) -> GradingInput:
        raise RuntimeError("trace unavailable")

    monkeypatch.setattr("metis.engine.extractor.fetch_session", fetch)
    context, experiment_dir = _evaluation_context(tmp_path, fetch)
    record = _trial_record(experiment_dir, session_id="session-1")
    phases: list[str] = []

    result = await cli._evaluate_one(
        record, number=1, context=context, phase=lambda name, **_: phases.append(name)
    )

    assert result.failure_reason == "trace unavailable"
    assert result.records == []
    assert phases[-1] == "failed"


@pytest.mark.asyncio
async def test_evaluate_one_fails_a_record_without_a_session_id(
    monkeypatch, tmp_path: Path
) -> None:
    async def fetch(*_args: object, **_kwargs: object) -> GradingInput:
        raise AssertionError("a record with no session id must not be fetched")

    monkeypatch.setattr("metis.engine.extractor.fetch_session", fetch)
    context, experiment_dir = _evaluation_context(tmp_path, fetch)
    record = _trial_record(experiment_dir, session_id=None)

    result = await cli._evaluate_one(
        record, number=1, context=context, phase=lambda name, **_: None
    )

    assert result.failure_reason == "No target_session_id"
    assert result.records == []


# --- concurrent evaluation: --concurrency N sessions in flight at once --------------------


def _write_records(output: Path, count: int) -> None:
    """``count`` trial records, one session each, in a fixed order (records sort by mtime)."""
    for number in range(1, count + 1):
        path = _write_record(
            output, run_name=f"run-{number:02d}", session_id=f"session-{number}"
        )
        os.utime(path, (1_000_000 + number, 1_000_000 + number))


class _Probe:
    """Counts how many fake sessions are inside a block at the same time."""

    def __init__(self) -> None:
        self.current = 0
        self.peak = 0

    @contextlib.asynccontextmanager
    async def inside(self):
        self.current += 1
        self.peak = max(self.peak, self.current)
        try:
            yield
        finally:
            self.current -= 1


def _patch_slow_grading(monkeypatch, probe: _Probe, seconds: float = 0.05) -> None:
    """Make the real ``grade_session`` take a moment, and count the sessions inside it."""
    from metis.engine import evaluation

    real_grade_session = evaluation.grade_session

    async def grade_session(*args: Any, **kwargs: Any):
        async with probe.inside():
            await asyncio.sleep(seconds)
            return await real_grade_session(*args, **kwargs)

    monkeypatch.setattr("metis.engine.evaluation.grade_session", grade_session)


def _evaluate_directly(output: Path, concurrency: int) -> EvaluationOutcome:
    return cli._run_evaluation(
        output,
        langfuse_timeout=0,
        verbose=0,
        quiet=False,
        concurrency=concurrency,
    )


def _graded_sessions(output: Path) -> list[str]:
    results = EvaluationResults.load_file(
        output / "outputs" / "reports" / "results.json"
    )
    return [record.session_id for record in results.records]


def test_sessions_in_flight_never_exceed_the_concurrency(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 5)
    _patch_evaluation(monkeypatch)
    probe = _Probe()
    _patch_slow_grading(monkeypatch, probe)

    outcome = _evaluate_directly(output, concurrency=2)

    assert outcome.successful_records == 5
    assert probe.peak == 2


def test_concurrency_one_grades_one_session_at_a_time(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 3)
    _patch_evaluation(monkeypatch)
    probe = _Probe()
    _patch_slow_grading(monkeypatch, probe)

    _evaluate_directly(output, concurrency=1)

    assert probe.peak == 1
    assert _graded_sessions(output) == ["session-1", "session-2", "session-3"]


def test_waiting_fetches_hold_no_thread(monkeypatch, tmp_path: Path) -> None:
    """Every fetch waits for all the others to arrive, so one is stuck unless all eight run."""
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 8)
    arrived: list[str] = []
    all_here = asyncio.Event()

    async def fetch(session_id: str, *_args: object, **_kwargs: object):
        arrived.append(session_id)
        if len(arrived) == 8:
            all_here.set()
        await asyncio.wait_for(all_here.wait(), timeout=0.5)
        return _session(session_id)

    monkeypatch.setattr("metis.engine.extractor.get_langfuse_client", lambda: object())
    monkeypatch.setattr("metis.engine.extractor.fetch_session", fetch)

    outcome = _evaluate_directly(output, concurrency=8)

    assert (outcome.successful_records, outcome.failed_records) == (8, 0)


def test_results_follow_record_order_whatever_order_sessions_finish(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 3)
    delays = {"session-1": 0.15, "session-2": 0.08, "session-3": 0.0}
    finished: list[str] = []

    async def fetch(session_id: str, *_args: object, **_kwargs: object):
        await asyncio.sleep(delays[session_id])
        finished.append(session_id)
        return _session(session_id)

    monkeypatch.setattr("metis.engine.extractor.get_langfuse_client", lambda: object())
    monkeypatch.setattr("metis.engine.extractor.fetch_session", fetch)

    _evaluate_directly(output, concurrency=3)

    assert finished == ["session-3", "session-2", "session-1"]
    assert _graded_sessions(output) == ["session-1", "session-2", "session-3"]


def test_one_failing_session_does_not_change_the_others(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 3)

    async def fetch(session_id: str, *_args: object, **_kwargs: object):
        if session_id == "session-2":
            raise RuntimeError("trace unavailable")
        return _session(session_id)

    monkeypatch.setattr("metis.engine.extractor.get_langfuse_client", lambda: object())
    monkeypatch.setattr("metis.engine.extractor.fetch_session", fetch)

    outcome = _evaluate_directly(output, concurrency=3)

    assert (outcome.successful_records, outcome.failed_records) == (2, 1)
    assert _graded_sessions(output) == ["session-1", "session-3"]


@pytest.mark.asyncio
async def test_records_that_cannot_be_graded_leave_the_running_count_at_zero(
    monkeypatch, tmp_path: Path
) -> None:
    async def fetch(*_args: object, **_kwargs: object) -> GradingInput:
        raise AssertionError("neither record may be fetched")

    monkeypatch.setattr("metis.engine.extractor.fetch_session", fetch)
    context, experiment_dir = _evaluation_context(tmp_path, fetch)
    no_session = _trial_record(experiment_dir, session_id=None)
    no_criteria = _trial_record(experiment_dir, session_id="session-1")
    no_criteria = no_criteria.model_copy(
        update={"config": no_criteria.config.model_copy(update={"grader_refs": []})}
    )

    for number, record in enumerate([no_session, no_criteria], start=1):
        result = await cli._evaluate_one(
            record, number=number, context=context, phase=lambda name, **_: None
        )
        assert result.failure_reason is not None
        assert context.running.value == 0


# --- output when sessions overlap: banner, record labels, progress text --------------------


class _RecordingProgress:
    """A stand-in for the Rich bar that keeps every description it is given."""

    descriptions: list[str]

    def __init__(self) -> None:
        self.descriptions = []

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def add_task(self, description: str, *, total: int) -> int:
        return 1

    def update(self, _task_id: int, **kwargs: Any) -> None:
        if "description" in kwargs:
            self.descriptions.append(kwargs["description"])


def _use_recording_progress(monkeypatch) -> _RecordingProgress:
    bar = _RecordingProgress()
    monkeypatch.setattr(cli.sys.stderr, "isatty", lambda: True)
    monkeypatch.setattr(cli, "_create_evaluation_progress", lambda: bar)
    return bar


def test_session_banner_is_printed_with_concurrency_one(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 2)
    _patch_evaluation(monkeypatch)

    _evaluate_directly(output, concurrency=1)

    out = capsys.readouterr().out
    assert "SESSION 1/2: alice x task-1" in out
    assert "SESSION 2/2: alice x task-1" in out


def test_session_banner_is_not_printed_with_overlapping_sessions(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 2)
    _patch_evaluation(monkeypatch)

    _evaluate_directly(output, concurrency=2)

    assert "SESSION" not in capsys.readouterr().out


def test_failed_record_warning_names_its_record(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 2)

    async def fetch(session_id: str, *_args: object, **_kwargs: object):
        if session_id == "session-2":
            raise RuntimeError("trace unavailable")
        return _session(session_id)

    monkeypatch.setattr("metis.engine.extractor.get_langfuse_client", lambda: object())
    monkeypatch.setattr("metis.engine.extractor.fetch_session", fetch)

    _evaluate_directly(output, concurrency=2)

    assert _compact(
        "WARNING: RECORD 2/2 alice x task-1 — Evaluation failed: trace unavailable"
    ) in _compact(capsys.readouterr().out)


def test_unknown_criteria_warning_names_its_record(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    output = _write_experiment_dir(tmp_path)
    path = _write_record(output)
    record = TrialRecord.model_validate_json(path.read_text())
    extra = GraderRef(criterion_id="AC-9-9", fqn="x.Y", args={})
    config = record.config.model_copy(
        update={"grader_refs": [*record.config.grader_refs, extra]}
    )
    path.write_text(record.model_copy(update={"config": config}).model_dump_json())
    _patch_evaluation(monkeypatch)

    _evaluate_directly(output, concurrency=2)

    assert _compact(
        "WARNING: RECORD 1/1 alice x task-1 — criteria AC-9-9 are not in the "
        "specification snapshot and were not graded"
    ) in _compact(capsys.readouterr().out)


def test_progress_bar_counts_running_sessions_when_they_overlap(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 3)
    bar = _use_recording_progress(monkeypatch)
    _patch_evaluation(monkeypatch)
    _patch_slow_grading(monkeypatch, _Probe())

    _evaluate_directly(output, concurrency=2)

    assert "Evaluation — 2 running" in bar.descriptions
    # Three records and two slots: the third waits and is never counted as running.
    assert not any("3 running" in d for d in bar.descriptions)
    assert not any(" x " in d for d in bar.descriptions)
    assert bar.descriptions[-1] == "Evaluation complete"


def test_progress_bar_keeps_the_phase_wording_with_concurrency_one(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 2)
    bar = _use_recording_progress(monkeypatch)
    _patch_evaluation(monkeypatch)

    _evaluate_directly(output, concurrency=1)

    assert "alice x task-1 — extracting" in bar.descriptions
    assert not any("running" in d for d in bar.descriptions)


def test_plain_progress_lines_are_unchanged_when_sessions_overlap(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 2)
    _patch_evaluation(monkeypatch)

    _evaluate_directly(output, concurrency=2)

    out = capsys.readouterr().out
    assert "Evaluation 1/2: alice x task-1 — extracting" in out
    assert "running" not in out


# --- interrupt: Ctrl-C cancels every session and discards partial grades -------------------


@pytest.mark.asyncio
async def test_cancellation_stops_every_session_then_closes_the_judge_client(
    monkeypatch, tmp_path: Path
) -> None:
    from metis.core.trials import TrialRecord as Record
    from metis.engine.logging import EvaluationLogger
    from metis.library.grader import LLMSettings

    output = _write_experiment_dir(
        tmp_path,
        content=MINIMAL_EXPERIMENT.replace("FixedScoreGrader", "EchoJudgeGrader"),
    )
    _write_records(output, 3)
    stale = output / "outputs" / "reports" / "results.json"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("{}")
    events: list[str] = []
    in_flight = asyncio.Event()

    class FakeJudgeClient:
        async def close(self) -> None:
            events.append("judge client closed")

    async def fetch(session_id: str, *_args: object, **_kwargs: object):
        events.append(f"start {session_id}")
        if sum(e.startswith("start") for e in events) == 2:
            in_flight.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            await asyncio.sleep(0.02)  # a session takes a moment to stop
            events.append(f"stopped {session_id}")
            raise
        return _session(session_id)

    monkeypatch.setenv("JUDGE_API_KEY", "test-key")
    monkeypatch.setattr("metis.engine.extractor.get_langfuse_client", lambda: object())
    monkeypatch.setattr("metis.engine.extractor.fetch_session", fetch)
    monkeypatch.setattr(
        "metis.engine.evaluation.build_llm_settings",
        lambda _gateway: LLMSettings(client=FakeJudgeClient()),  # type: ignore[arg-type]
    )
    log = EvaluationLogger(output / "logs")
    specification = cli._load_evaluation_specification(output)
    records = [Record.load_file(p) for p in cli._trial_record_files(output)]

    task = asyncio.create_task(
        cli._evaluate_records(
            output,
            specification,
            records,
            evaluation_log=log,
            langfuse_timeout=0,
            concurrency=2,
        )
    )
    await asyncio.wait_for(in_flight.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Two sessions held slots; the third was still waiting and never started.
    assert sorted(e for e in events if e.startswith("start")) == [
        "start session-1",
        "start session-2",
    ]
    assert events[-1] == "judge client closed"
    assert sorted(e for e in events if e.startswith("stopped")) == [
        "stopped session-1",
        "stopped session-2",
    ]
    assert not stale.exists()
    assert "EVALUATION INTERRUPTED" in log.path.read_text()
    assert "EVALUATION COMPLETED" not in log.path.read_text()


@pytest.mark.asyncio
async def test_cancelling_a_session_returns_the_running_count_to_zero(
    monkeypatch, tmp_path: Path
) -> None:
    started = asyncio.Event()

    async def fetch(*_args: object, **_kwargs: object) -> GradingInput:
        started.set()
        await asyncio.sleep(30)
        raise AssertionError("unreachable")

    monkeypatch.setattr("metis.engine.extractor.fetch_session", fetch)
    context, experiment_dir = _evaluation_context(tmp_path, fetch)
    record = _trial_record(experiment_dir, session_id="session-1")

    task = asyncio.create_task(
        cli._evaluate_one(
            record, number=1, context=context, phase=lambda name, **_: None
        )
    )
    await asyncio.wait_for(started.wait(), timeout=2)
    assert context.running.value == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert context.running.value == 0


@pytest.mark.parametrize("value", ["0", "-1"])
def test_evaluate_rejects_a_concurrency_below_one(
    monkeypatch, tmp_path: Path, value: str
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 1)
    _patch_evaluation(monkeypatch)

    result = runner.invoke(
        app, ["evaluate", "--experiment-dir", str(output), "--concurrency", value]
    )

    assert result.exit_code == 2
    assert isinstance(result.exception, SystemExit)
    assert not (output / "logs" / "evaluate.log").exists()  # no work started
