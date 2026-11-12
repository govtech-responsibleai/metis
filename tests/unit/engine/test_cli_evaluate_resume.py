"""Tests for ``metis engine evaluate --resume``."""

from __future__ import annotations

import asyncio
import json
import shutil
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from metis.core.grading import RecordedResult
from metis.core.reporting import EvaluationResults, GraderRecord
from metis.engine import cli
from metis.engine.cli import app
from metis.engine.evaluation.trial_files import (
    TrialEvaluation,
    grading_seconds,
    load_trial_evaluations,
    save_trial_evaluation,
    trial_evaluation_path,
)
from metis.engine.extractor import TraceWaitSettings
from metis.engine.extractor.langfuse import NO_TRACES
from tests.unit.engine.test_cli_evaluate import (
    _patch_evaluation,
    _session,
    _write_experiment_dir,
    _write_records,
)

if TYPE_CHECKING:
    from pathlib import Path

    from metis.core.traces import GradingInput

runner = CliRunner()
_T0 = datetime(2026, 11, 12, 9, 0, 0, tzinfo=UTC)


def _grader_record(session_id: str, outcome: str = "passed") -> GraderRecord:
    score = 1.0 if outcome == "passed" else None
    return GraderRecord(
        session_id=session_id,
        scenario_id="task-1",
        task_id="TC-001",
        trial_index=1,
        criterion_id="AC-1-1",
        grader_fqn="tests.unit.engine.graders_for_tests.FixedScoreGrader",
        grader_args={"threshold": 0.5, "score": 1.0},
        results=[RecordedResult(outcome=outcome, score=score, reason="ok")],  # type: ignore[arg-type]
    )


def write_trial_file(
    experiment_dir: Path,
    trial: str,
    *,
    session_id: str,
    failure_reason: str | None = None,
    outcome: str = "passed",
    started_at: datetime = _T0,
    seconds: float = 1.0,
) -> TrialEvaluation:
    """Write the evaluation file of ``trial`` by hand, as an earlier evaluation would."""
    evaluation = TrialEvaluation(
        trial=trial,
        records=[] if failure_reason else [_grader_record(session_id, outcome)],
        failure_reason=failure_reason,
        started_at=started_at,
        finished_at=started_at + timedelta(seconds=seconds),
    )
    save_trial_evaluation(experiment_dir, evaluation)
    return evaluation


def _results(output: Path) -> EvaluationResults:
    return EvaluationResults.load_file(output / "outputs" / "reports" / "results.json")


def _fetched(calls: list[dict[str, Any]]) -> list[str]:
    return [call["session_id"] for call in calls]


def _evaluate(output: Path, *, resume: bool, concurrency: int = 1):
    return cli._run_evaluation(
        output,
        trace_wait=TraceWaitSettings(timeout_seconds=90),
        verbose=0,
        quiet=False,
        concurrency=concurrency,
        resume=resume,
    )


def _resume(output: Path):
    return runner.invoke(app, ["evaluate", "--resume", "--experiment-dir", str(output)])


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _without_times(evaluation: TrialEvaluation) -> dict[str, Any]:
    return evaluation.model_dump(mode="json", exclude={"started_at", "finished_at"})


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [1, 2])
async def test_an_interrupted_run_saves_finished_trials_and_resume_grades_only_the_rest(
    monkeypatch, tmp_path: Path, capsys, concurrency: int
) -> None:
    from metis.core.trials import TrialRecord
    from metis.engine.logging import EvaluationLogger

    output = _write_experiment_dir(tmp_path / "a")
    _write_records(output, 4)
    uninterrupted = tmp_path / "b" / output.name
    shutil.copytree(output, uninterrupted)
    trials = ["run-01", "run-02", "run-03", "run-04"]
    # session-3 never returns. With one slot, session-4 never starts; with two, it
    # takes the slot session-2 left and finishes.
    finished = (
        ["run-01", "run-02"] if concurrency == 1 else ["run-01", "run-02", "run-04"]
    )
    waiting = asyncio.Event()

    async def fetch(session_id: str, *_args: object, **_kwargs: object) -> GradingInput:
        if session_id == "session-3":
            waiting.set()
            await asyncio.sleep(30)
        return _session(session_id)

    monkeypatch.setattr("metis.engine.extractor.get_langfuse_client", lambda: object())
    monkeypatch.setattr("metis.engine.extractor.fetch_session", fetch)
    task = asyncio.create_task(
        cli._evaluate_records(
            output,
            cli._load_evaluation_specification(output),
            [
                (p.parent.name, TrialRecord.load_file(p))
                for p in cli._trial_record_files(output)
            ],
            evaluation_log=EvaluationLogger(output / "logs"),
            trace_wait=TraceWaitSettings(timeout_seconds=90),
            concurrency=concurrency,
        )
    )
    await asyncio.wait_for(waiting.wait(), timeout=2)

    async def finished_files() -> None:
        while not all(trial_evaluation_path(output, t).exists() for t in finished):
            await asyncio.sleep(0.01)

    await asyncio.wait_for(finished_files(), timeout=2)
    capsys.readouterr()  # drop the output printed before the interrupt
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert (
        f"Interrupted. {len(finished)} of {len(trials)} trials are saved."
        in _one_line(capsys.readouterr().out)
    )
    assert list(load_trial_evaluations(output, trials)) == finished
    assert not (output / "outputs" / "reports" / "results.json").exists()

    calls = _patch_evaluation(monkeypatch)
    await asyncio.to_thread(_evaluate, output, resume=True, concurrency=concurrency)
    assert sorted(_fetched(calls)) == sorted(
        f"session-{int(t[-2:])}" for t in trials if t not in finished
    )

    await asyncio.to_thread(_evaluate, uninterrupted, resume=False)
    resumed, fresh = _results(output), _results(uninterrupted)
    assert [r.model_dump() for r in resumed.records] == [
        r.model_dump() for r in fresh.records
    ]
    assert resumed.timings["evaluation_seconds"] == round(
        grading_seconds(load_trial_evaluations(output, trials).values()), 1
    )
    resumed_files = load_trial_evaluations(output, trials)
    fresh_files = load_trial_evaluations(uninterrupted, trials)
    assert {t: _without_times(e) for t, e in resumed_files.items()} == {
        t: _without_times(e) for t, e in fresh_files.items()
    }


def test_grading_time_of_a_resumed_run_ignores_the_gap(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 3)
    write_trial_file(output, "run-01", session_id="session-1", seconds=10)
    write_trial_file(
        output,
        "run-02",
        session_id="session-2",
        started_at=_T0 + timedelta(hours=1),
        seconds=5,
    )
    _patch_evaluation(monkeypatch)

    _evaluate(output, resume=True)

    evaluations = load_trial_evaluations(output, ["run-01", "run-02", "run-03"])
    assert list(evaluations) == ["run-01", "run-02", "run-03"]
    seconds = _results(output).timings["evaluation_seconds"]
    assert seconds == round(grading_seconds(evaluations.values()), 1)
    assert seconds < 3600


def test_resume_counts_failures_from_before_the_interrupt(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 2)
    write_trial_file(
        output,
        "run-01",
        session_id="session-1",
        failure_reason=NO_TRACES,
    )
    calls = _patch_evaluation(monkeypatch)

    result = _resume(output)

    assert result.exit_code == 0, result.output
    assert _fetched(calls) == ["session-2"]
    out = _one_line(result.output)
    assert "2 run(s), 1 failed" in out
    assert f"Grade every trial again: {cli._evaluate_command(output.resolve())}" in out


def test_resume_does_not_retry_failed_or_errored_trials(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 3)
    write_trial_file(
        output, "run-01", session_id="session-1", failure_reason="trace unavailable"
    )
    write_trial_file(output, "run-02", session_id="session-2", outcome="errored")
    calls = _patch_evaluation(monkeypatch)

    result = _resume(output)

    assert result.exit_code == 0, result.output
    assert _fetched(calls) == ["session-3"]
    outcomes = [r.results[0].outcome for r in _results(output).records]
    assert outcomes == ["errored", "passed"]


@pytest.mark.parametrize(
    "content",
    [
        "",
        "{",
        "not json",
        json.dumps(
            {
                "schema_version": 2,
                "trial": "run-01",
                "records": [],
                "failure_reason": None,
                "started_at": _T0.isoformat(),
                "finished_at": _T0.isoformat(),
            }
        ),
    ],
)
def test_resume_grades_a_trial_whose_file_is_unreadable(
    monkeypatch, tmp_path: Path, content: str
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 1)
    path = trial_evaluation_path(output, "run-01")
    path.parent.mkdir(parents=True)
    path.write_text(content)
    calls = _patch_evaluation(monkeypatch)

    result = _resume(output)

    assert result.exit_code == 0, result.output
    assert _fetched(calls) == ["session-1"]
    assert [r.session_id for r in _results(output).records] == ["session-1"]


def _snapshot(output: Path) -> dict[Path, bytes]:
    return {
        path: path.read_bytes()
        for folder in ("logs", "outputs")
        for path in sorted((output / folder).rglob("*"))
        if path.is_file()
    }


def test_resume_with_complete_results_touches_nothing(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 2)
    _patch_evaluation(monkeypatch)
    assert (
        runner.invoke(app, ["evaluate", "--experiment-dir", str(output)]).exit_code == 0
    )
    before = _snapshot(output)
    calls = _patch_evaluation(monkeypatch)

    result = _resume(output)

    assert result.exit_code == 0, result.output
    assert "nothing to resume" in result.output
    results_file = output.resolve() / "outputs" / "reports" / "results.json"
    assert cli._report_command(results_file) in _one_line(result.output)
    assert "2 run(s), 0 failed" in result.output
    assert calls == []
    assert _snapshot(output) == before


def test_resume_with_unparsable_results_resumes(monkeypatch, tmp_path: Path) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 1)
    results_file = output / "outputs" / "reports" / "results.json"
    results_file.parent.mkdir(parents=True)
    results_file.write_text("{")
    present_at_fetch: list[bool] = []

    async def fetch(session_id: str, *_args: object, **_kwargs: object) -> GradingInput:
        present_at_fetch.append(results_file.exists())
        return _session(session_id)

    monkeypatch.setattr("metis.engine.extractor.get_langfuse_client", lambda: object())
    monkeypatch.setattr("metis.engine.extractor.fetch_session", fetch)

    result = _resume(output)

    assert result.exit_code == 0, result.output
    assert "nothing to resume" not in result.output
    assert present_at_fetch == [False]
    assert [r.session_id for r in _results(output).records] == ["session-1"]


def test_every_trial_failing_then_resume_says_nothing_to_resume(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 1)
    _patch_evaluation(monkeypatch, traces=0)
    assert (
        runner.invoke(app, ["evaluate", "--experiment-dir", str(output)]).exit_code == 0
    )
    assert _results(output).records == []
    calls = _patch_evaluation(monkeypatch)

    result = _resume(output)

    assert result.exit_code == 0, result.output
    assert "nothing to resume" in result.output
    assert "1 run(s), 1 failed" in result.output
    assert calls == []


def test_resume_with_every_trial_attempted_writes_results_without_fetching(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 2)
    write_trial_file(output, "run-01", session_id="session-1")
    write_trial_file(output, "run-02", session_id="session-2")
    calls = _patch_evaluation(monkeypatch)

    result = _resume(output)

    assert result.exit_code == 0, result.output
    assert calls == []
    assert [r.session_id for r in _results(output).records] == [
        "session-1",
        "session-2",
    ]


def test_resume_of_a_folder_with_results_but_no_trial_files_is_a_noop(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 1)
    results_file = output / "outputs" / "reports" / "results.json"
    EvaluationResults(run_id="report", records=[_grader_record("session-1")]).save(
        results_file
    )
    before = results_file.read_bytes()
    calls = _patch_evaluation(monkeypatch)

    result = _resume(output)

    assert result.exit_code == 0, result.output
    assert result.exception is None
    assert "nothing to resume" in result.output
    assert "nothing to evaluate" not in result.output
    assert "Traceback" not in result.output
    assert calls == []
    assert results_file.read_bytes() == before


def test_resume_ignores_files_of_trials_not_in_the_experiment(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 1)
    gone = write_trial_file(output, "gone", session_id="gone-session")
    _patch_evaluation(monkeypatch)

    result = _resume(output)

    assert result.exit_code == 0, result.output
    assert trial_evaluation_path(output, "gone").exists()
    assert load_trial_evaluations(output, ["gone"]) == {"gone": gone}
    assert [r.session_id for r in _results(output).records] == ["session-1"]


def test_resume_says_how_many_trials_are_already_evaluated(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 3)
    write_trial_file(output, "run-01", session_id="session-1")
    _patch_evaluation(monkeypatch)

    result = _resume(output)

    assert result.exit_code == 0, result.output
    assert "resuming: 1 of 3 trials already evaluated" in _one_line(result.output)
    log = (output / "logs" / "evaluate.log").read_text()
    assert "resuming: 1 of 3 trials already evaluated" in log


def test_resume_appends_to_the_evaluation_log(monkeypatch, tmp_path: Path) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 1)
    _patch_evaluation(monkeypatch)
    assert (
        runner.invoke(app, ["evaluate", "--experiment-dir", str(output)]).exit_code == 0
    )
    log_path = output / "logs" / "evaluate.log"
    first_run = log_path.read_text()
    (output / "outputs" / "reports" / "results.json").unlink()

    result = _resume(output)

    assert result.exit_code == 0, result.output
    log = log_path.read_text()
    assert log.startswith(first_run)
    assert log.count("EVALUATION STARTED") == 2


def test_resume_reports_the_attempted_trials_in_the_started_event(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 3)
    write_trial_file(output, "run-01", session_id="session-1")
    _patch_evaluation(monkeypatch)

    result = _resume(output)

    assert result.exit_code == 0, result.output
    lines = [
        json.loads(line)
        for line in (output / "logs" / "events.jsonl").read_text().splitlines()
    ]
    started = [
        line
        for line in lines
        if line.get("phase") == "evaluating"
        and line.get("status") == "started"
        and line.get("trial") is None
    ]
    assert [(line["total"], line["done"]) for line in started] == [(3, 1)]


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["evaluate", "run"])
async def test_the_interrupt_message_names_the_resume_command(
    monkeypatch, tmp_path: Path, capsys, command: str
) -> None:
    from metis.core.trials import TrialRecord
    from metis.engine.logging import EvaluationLogger

    output = _write_experiment_dir(tmp_path)
    _write_records(output, 3)
    waiting = asyncio.Event()

    async def fetch(*_args: object, **_kwargs: object) -> GradingInput:
        waiting.set()
        await asyncio.sleep(30)
        raise AssertionError("unreachable")

    monkeypatch.setattr("metis.engine.extractor.get_langfuse_client", lambda: object())
    monkeypatch.setattr("metis.engine.extractor.fetch_session", fetch)
    log = EvaluationLogger(output / "logs")
    task = asyncio.create_task(
        cli._evaluate_records(
            output,
            cli._load_evaluation_specification(output),
            [
                (p.parent.name, TrialRecord.load_file(p))
                for p in cli._trial_record_files(output)
            ],
            evaluation_log=log,
            trace_wait=TraceWaitSettings(timeout_seconds=90),
            command=command,  # type: ignore[arg-type]
        )
    )
    await asyncio.wait_for(waiting.wait(), timeout=2)
    capsys.readouterr()  # drop the output printed before the interrupt

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    out = _one_line(capsys.readouterr().out)
    assert "Interrupted. 0 of 3 trials are saved." in out
    assert f"To continue, run: {cli._resume_command(output.resolve(), command)}" in out
    assert "EVALUATION INTERRUPTED" in log.path.read_text()
    assert not (output / "outputs" / "reports" / "results.json").exists()


def test_the_progress_bar_of_a_resume_starts_at_the_trials_already_evaluated(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 3)
    write_trial_file(output, "run-01", session_id="session-1")
    _patch_evaluation(monkeypatch)
    added: list[tuple[int, int]] = []

    class Bar:
        def __enter__(self) -> Bar:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def add_task(self, _description: str, *, total: int, completed: int) -> int:
            added.append((total, completed))
            return 1

        def update(self, _task_id: int, **_kwargs: object) -> None:
            return None

    monkeypatch.setattr(cli.sys.stderr, "isatty", lambda: True)
    monkeypatch.setattr(cli, "_create_evaluation_progress", Bar)

    _evaluate(output, resume=True)

    assert added == [(3, 1)]
