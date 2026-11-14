"""Tests for ``metis.engine.runs.evaluate`` and ``resume_evaluation``, called with no CLI."""

from __future__ import annotations

import asyncio
import io
import json
import shutil
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from metis.core import execution_layout
from metis.engine.extractor import TraceWaitSettings
from metis.engine.runs import (
    EvaluationInputError,
    EvaluationOutcome,
    RunStopped,
    evaluate,
    resume_evaluation,
)
from tests.unit.engine.test_cli_evaluate import (
    MINIMAL_EXPERIMENT,
    _patch_evaluation,
    _session,
    _write_experiment_dir,
    _write_records,
)
from tests.unit.engine.test_cli_evaluate_resume import write_trial_file

_WAIT = TraceWaitSettings(timeout_seconds=90)


def _console() -> tuple[Console, io.StringIO]:
    text = io.StringIO()
    return Console(file=text, width=200), text


def _phase_lines(experiment_dir: Path) -> list[tuple[str, str]]:
    path = experiment_dir / execution_layout.LOGS / execution_layout.EVENTS_FILE
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    return [(line["phase"], line["status"]) for line in lines if not line.get("trial")]


def _results(experiment_dir: Path) -> Path:
    return experiment_dir / execution_layout.RESULTS


def _fetch_that_waits(monkeypatch) -> threading.Event:
    """Every session waits for its traces until it is cancelled. Returns 'a fetch started'."""
    started = threading.Event()

    async def fetch(*_args: object, **_kwargs: object):
        started.set()
        await asyncio.sleep(30)
        raise AssertionError("a stopped session must not finish its fetch")

    monkeypatch.setattr("metis.engine.extractor.get_langfuse_client", lambda: object())
    monkeypatch.setattr("metis.engine.extractor.fetch_session", fetch)
    return started


def _in_a_thread(function, *args, **kwargs) -> tuple[threading.Thread, list[Any]]:
    """Run ``function`` in a worker thread, as the API does. The list gets its result."""
    outcome: list[Any] = []

    def run() -> None:
        try:
            outcome.append(function(*args, **kwargs))
        except BaseException as exc:
            outcome.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    return thread, outcome


def test_evaluate_grades_every_trial_and_writes_the_results(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 2)
    _patch_evaluation(monkeypatch)

    outcome = evaluate(
        output,
        trace_wait=_WAIT,
        concurrency=1,
        stop=threading.Event(),
        console=_console()[0],
    )

    assert outcome == EvaluationOutcome(2, 2, 0, _results(output))
    assert _phase_lines(output) == [
        ("evaluating", "started"),
        ("evaluating", "completed"),
    ]


@pytest.mark.parametrize("function", [evaluate, resume_evaluation])
def test_the_stop_flag_ends_the_evaluation_with_an_interrupted_line(
    monkeypatch, tmp_path: Path, function
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 3)
    started = _fetch_that_waits(monkeypatch)
    stop = threading.Event()

    thread, outcome = _in_a_thread(
        function,
        output,
        trace_wait=_WAIT,
        concurrency=1,
        stop=stop,
        console=_console()[0],
    )
    assert started.wait(timeout=5)
    stop.set()
    thread.join(timeout=10)

    assert not thread.is_alive()
    assert isinstance(outcome[0], RunStopped)
    assert _phase_lines(output)[-1] == ("evaluating", "interrupted")
    assert not _results(output).exists()


def test_a_stop_takes_effect_while_a_session_waits_for_its_traces(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 1)
    started = _fetch_that_waits(monkeypatch)
    stop = threading.Event()

    thread, outcome = _in_a_thread(
        evaluate,
        output,
        trace_wait=_WAIT,
        concurrency=1,
        stop=stop,
        console=_console()[0],
    )
    assert started.wait(timeout=5)
    stopped_at = time.monotonic()
    stop.set()
    thread.join(timeout=10)

    assert time.monotonic() - stopped_at < 2
    assert isinstance(outcome[0], RunStopped)


def test_a_stop_before_any_session_starts_ends_the_run(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 2)
    calls = _patch_evaluation(monkeypatch)
    stop = threading.Event()
    stop.set()

    with pytest.raises(RunStopped):
        evaluate(
            output,
            trace_wait=_WAIT,
            concurrency=1,
            stop=stop,
            console=_console()[0],
        )

    assert calls == []
    assert _phase_lines(output)[-1] == ("evaluating", "interrupted")
    assert not _results(output).exists()


def _earlier_evaluation(output: Path) -> dict[Path, bytes]:
    """The outputs of an evaluation that graded run-01, with a stale results.json and trace."""
    write_trial_file(
        output, "run-01", session_id="session-1", failure_reason="earlier failure"
    )
    trace = output / execution_layout.TRACES / "earlier.json"
    trace.parent.mkdir(parents=True, exist_ok=True)
    trace.write_text("{}")
    results = _results(output)
    results.parent.mkdir(parents=True, exist_ok=True)
    results.write_text("{}")
    return {
        path: path.read_bytes()
        for path in [
            *(output / execution_layout.EVALUATION).rglob("*.json"),
            trace,
        ]
    }


def test_evaluate_deletes_the_earlier_evaluation_outputs(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 2)
    earlier = _earlier_evaluation(output)
    calls = _patch_evaluation(monkeypatch)

    evaluate(
        output,
        trace_wait=_WAIT,
        concurrency=1,
        stop=threading.Event(),
        console=_console()[0],
    )

    assert sorted(call["session_id"] for call in calls) == ["session-1", "session-2"]
    assert not (output / execution_layout.TRACES / "earlier.json").exists()
    assert all(
        not path.exists() or path.read_bytes() != content
        for path, content in earlier.items()
    )
    assert json.loads(_results(output).read_text())["records"]


def test_resume_evaluation_keeps_the_earlier_evaluation_outputs(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 2)
    earlier = _earlier_evaluation(output)
    calls = _patch_evaluation(monkeypatch)

    resume_evaluation(
        output,
        trace_wait=_WAIT,
        concurrency=1,
        stop=threading.Event(),
        console=_console()[0],
    )

    assert [call["session_id"] for call in calls] == ["session-2"]
    assert {path: path.read_bytes() for path in earlier} == earlier


def test_a_missing_snapshot_raises_an_evaluation_input_error(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    shutil.rmtree(output / "inputs")
    _patch_evaluation(monkeypatch)
    console, text = _console()

    with pytest.raises(EvaluationInputError):
        evaluate(
            output,
            trace_wait=_WAIT,
            concurrency=1,
            stop=threading.Event(),
            console=console,
        )

    assert "Error:" in text.getvalue()
    assert _phase_lines(output)[-1] == ("evaluating", "failed")


def test_a_record_that_does_not_load_raises_an_evaluation_input_error(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 1)
    record = next((output / execution_layout.TRIALS).glob("*/record.json"))
    record.write_text("not json")
    _patch_evaluation(monkeypatch)

    with pytest.raises(EvaluationInputError, match="failed to load trial record"):
        evaluate(
            output,
            trace_wait=_WAIT,
            concurrency=1,
            stop=threading.Event(),
            console=_console()[0],
        )


def test_a_judge_grader_with_no_key_raises_an_evaluation_input_error(
    monkeypatch, tmp_path: Path
) -> None:
    for name in ("JUDGE_API_KEY", "OPENAI_API_KEY", "DEFAULT_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    output = _write_experiment_dir(
        tmp_path,
        content=MINIMAL_EXPERIMENT.replace("FixedScoreGrader", "EchoJudgeGrader"),
    )
    _write_records(output, 1)
    _patch_evaluation(monkeypatch)

    with pytest.raises(EvaluationInputError, match="no judge API key"):
        evaluate(
            output,
            trace_wait=_WAIT,
            concurrency=1,
            stop=threading.Event(),
            console=_console()[0],
        )


def test_an_unexpected_error_is_raised_as_itself_after_a_failed_line(
    monkeypatch, tmp_path: Path
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 1)
    _patch_evaluation(monkeypatch)

    def no_space(*_args: object, **_kwargs: object) -> None:
        raise OSError("No space left on device")

    monkeypatch.setattr(
        "metis.engine.evaluation.trial_files.save_trial_evaluation", no_space
    )
    console, text = _console()

    with pytest.raises(OSError, match="No space left on device"):
        evaluate(
            output,
            trace_wait=_WAIT,
            concurrency=1,
            stop=threading.Event(),
            console=console,
        )

    assert "Error: evaluation failed: No space left on device" in text.getvalue()
    assert _phase_lines(output)[-1] == ("evaluating", "failed")
    log = (output / execution_layout.LOGS / "evaluate.log").read_text()
    assert log.splitlines()[-1].endswith("EVALUATION FAILED — No space left on device")


def test_evaluate_writes_only_to_the_console_it_was_given(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    output = _write_experiment_dir(tmp_path)
    _write_records(output, 1)

    async def fetch(session_id: str, *_args: object, **_kwargs: object):
        return _session(session_id)

    monkeypatch.setattr("metis.engine.extractor.get_langfuse_client", lambda: object())
    monkeypatch.setattr("metis.engine.extractor.fetch_session", fetch)
    console, text = _console()

    evaluate(
        output,
        trace_wait=_WAIT,
        concurrency=1,
        stop=threading.Event(),
        console=console,
    )

    assert capsys.readouterr().out == ""
    assert "Evaluation 1/1" in text.getvalue()
    assert "Loaded 1 trial record(s)" in text.getvalue()
