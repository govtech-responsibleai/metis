"""Tests for the ``metis engine evaluate`` command."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

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
    ) -> EvaluationOutcome:
        calls.append(path)
        assert langfuse_timeout == 120
        assert verbose == 1
        assert not quiet
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

    def fetch(session_id: str, _langfuse: object, **kwargs: Any) -> GradingInput:
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

    def fetch(session_id: str, *_args: object, **_kwargs: object) -> GradingInput:
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
    assert "WARNING: Evaluation failed: trace unavailable" in capsys.readouterr().out
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

    def fetch(session_id: str, *_args: object, **_kwargs: object) -> GradingInput:
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
    monkeypatch.setattr(
        "metis.engine.extractor.fetch_session", lambda *args, **kwargs: session
    )

    result = runner.invoke(app, ["evaluate", "--experiment-dir", str(output)])

    assert result.exit_code == 0, result.output
    (graded,) = EvaluationResults.load_file(
        output / "outputs" / "reports" / "results.json"
    ).records
    assert graded.criterion_id == "AC-1-1"
    assert "TRACES NOT SAVED" in (output / "logs" / "evaluate.log").read_text()
