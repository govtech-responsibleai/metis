"""Tests for ``metis.engine.runs.simulate`` and ``resume_simulation``, called with no CLI."""

from __future__ import annotations

import contextlib
import io
import json
import logging
import threading
from pathlib import Path

import pytest
import structlog
from rich.console import Console

from metis.core import execution_layout
from metis.core.logging import configure_logging
from metis.engine.runs import (
    RunError,
    RunStopped,
    prepare_experiment,
    resume_simulation,
    simulate,
)
from metis.engine.simulation import experiment as experiment_module
from tests.unit.engine.test_cli_simulate import (
    MINIMAL_EXPERIMENT,
    TWO_TRIAL_EXPERIMENT,
    _write_record,
)


@pytest.fixture(autouse=True)
def _reset_logging():
    yield
    structlog.reset_defaults()
    logging.getLogger().handlers.clear()


def _console() -> tuple[Console, io.StringIO]:
    text = io.StringIO()
    return Console(file=text, width=200), text


def _experiment(tmp_path: Path, content: str = MINIMAL_EXPERIMENT) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    (source / "specification.yaml").write_text(content)
    project = tmp_path / "project"
    project.mkdir()
    return prepare_experiment(source, project_dir=project, console=_console()[0])


def _events(experiment_dir: Path) -> list[tuple[str, str]]:
    path = experiment_dir / execution_layout.LOGS / execution_layout.EVENTS_FILE
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    return [(line["phase"], line["status"]) for line in lines if not line.get("trial")]


def _fake_trials(monkeypatch, *, stop: bool = False, error: Exception | None = None):
    """Replace the trials with a fake that writes one record, then stops or fails."""
    plans: list[list[object]] = []

    def fake_execute_experiment(*_args: object, **kwargs: object) -> None:
        plans.append(list(kwargs["trial_plan"]))  # type: ignore[arg-type]
        output_dir = kwargs["output_dir"]
        assert isinstance(output_dir, Path)
        _write_record(output_dir, "TC-001-alice-1")
        if stop:
            kwargs["stop"].set()  # type: ignore[union-attr]
        if error is not None:
            raise error

    monkeypatch.setattr(
        experiment_module, "execute_experiment", fake_execute_experiment
    )
    return plans


def test_simulate_runs_the_trials_and_ends_with_a_completed_line(
    monkeypatch, tmp_path: Path
) -> None:
    experiment_dir = _experiment(tmp_path)
    _fake_trials(monkeypatch)

    result = simulate(
        experiment_dir, concurrency=1, stop=threading.Event(), console=_console()[0]
    )

    assert result == experiment_dir
    assert _events(experiment_dir) == [
        ("simulating", "started"),
        ("simulating", "completed"),
    ]


def test_the_stop_flag_ends_simulate_with_an_interrupted_line(
    monkeypatch, tmp_path: Path
) -> None:
    experiment_dir = _experiment(tmp_path)
    _fake_trials(monkeypatch, stop=True)

    with pytest.raises(RunStopped):
        simulate(
            experiment_dir,
            concurrency=1,
            stop=threading.Event(),
            console=_console()[0],
        )

    assert _events(experiment_dir)[-1] == ("simulating", "interrupted")


def test_the_stop_flag_ends_resume_simulation_with_an_interrupted_line(
    monkeypatch, tmp_path: Path
) -> None:
    experiment_dir = _experiment(tmp_path, TWO_TRIAL_EXPERIMENT)
    _write_record(experiment_dir, "TC-001-alice-1", "goal_achieved")
    _write_record(experiment_dir, "TC-001-alice-2", "interrupted")
    plans = _fake_trials(monkeypatch, stop=True)

    with pytest.raises(RunStopped):
        resume_simulation(
            experiment_dir,
            concurrency=1,
            stop=threading.Event(),
            console=_console()[0],
        )

    assert [[item[2] for item in plan] for plan in plans] == [[2]]  # type: ignore[index]
    assert _events(experiment_dir)[-1] == ("simulating", "interrupted")


def test_resume_with_nothing_to_redo_completes_even_if_stop_is_set(
    monkeypatch, tmp_path: Path
) -> None:
    experiment_dir = _experiment(tmp_path)
    _write_record(experiment_dir, "TC-001-alice-1", "goal_achieved")
    plans = _fake_trials(monkeypatch)
    stop = threading.Event()
    stop.set()
    console, text = _console()

    resume_simulation(experiment_dir, concurrency=1, stop=stop, console=console)

    assert plans == []
    assert "nothing to resume" in text.getvalue()
    assert _events(experiment_dir)[-1] == ("simulating", "completed")


def test_no_trial_records_raises_a_run_error(monkeypatch, tmp_path: Path) -> None:
    experiment_dir = _experiment(tmp_path)
    monkeypatch.setattr(experiment_module, "execute_experiment", lambda *_a, **_k: None)

    with pytest.raises(RunError) as caught:
        simulate(
            experiment_dir,
            concurrency=1,
            stop=threading.Event(),
            console=_console()[0],
        )

    assert str(caught.value) == "No trial records found."
    assert _events(experiment_dir)[-1] == ("simulating", "failed")


def test_an_error_in_the_trials_ends_simulate_with_a_failed_line(
    monkeypatch, tmp_path: Path
) -> None:
    experiment_dir = _experiment(tmp_path)
    _fake_trials(monkeypatch, error=RuntimeError("runner crashed"))

    with pytest.raises(RuntimeError, match="runner crashed"):
        simulate(
            experiment_dir,
            concurrency=1,
            stop=threading.Event(),
            console=_console()[0],
        )

    assert _events(experiment_dir)[-1] == ("simulating", "failed")


def test_simulate_runs_in_a_worker_thread(monkeypatch, tmp_path: Path) -> None:
    experiment_dir = _experiment(tmp_path)
    _fake_trials(monkeypatch)
    errors: list[BaseException] = []

    def run() -> None:
        try:
            simulate(
                experiment_dir,
                concurrency=1,
                stop=threading.Event(),
                console=_console()[0],
            )
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(timeout=10)

    assert not thread.is_alive()
    assert errors == []
    assert _events(experiment_dir)[-1] == ("simulating", "completed")


@pytest.mark.parametrize("error", [None, RuntimeError("runner crashed")])
def test_the_structlog_config_after_simulate_is_the_one_before_it(
    monkeypatch, tmp_path: Path, error: Exception | None
) -> None:
    experiment_dir = _experiment(tmp_path)
    _fake_trials(monkeypatch, error=error)
    configure_logging(level="INFO")
    before = structlog.get_config()

    with contextlib.suppress(RuntimeError):
        simulate(
            experiment_dir,
            concurrency=1,
            stop=threading.Event(),
            console=_console()[0],
        )

    assert structlog.get_config() == before


def test_simulate_writes_only_to_the_console_it_was_given(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    experiment_dir = _experiment(tmp_path)
    _fake_trials(monkeypatch)
    console, text = _console()

    simulate(experiment_dir, concurrency=1, stop=threading.Event(), console=console)

    assert capsys.readouterr().out == ""
    assert "SIMULATION" in text.getvalue()
    assert "completed in" in text.getvalue()
