"""Tests for ``metis.engine.run.simulate`` and ``resume_simulation``, called with no CLI."""

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
from metis.core.logging import configure_logging, get_logger
from metis.engine.run import (
    EvaluationInputError,
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
    _write_evaluation_outputs,
    _write_record,
)


@pytest.fixture(autouse=True)
def _reset_logging():
    yield
    structlog.reset_defaults()
    logging.getLogger().handlers.clear()


def _console() -> tuple[Console, io.StringIO]:
    text = io.StringIO()
    # soft_wrap: a message holds a temp path of any length, and must stay on one line.
    return Console(file=text, width=200, soft_wrap=True), text


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


def test_simulate_again_clears_the_evaluation_of_the_earlier_trials(
    monkeypatch, tmp_path: Path
) -> None:
    experiment_dir = _experiment(tmp_path)
    _fake_trials(monkeypatch)
    simulate(
        experiment_dir, concurrency=1, stop=threading.Event(), console=_console()[0]
    )
    evaluation_paths = _write_evaluation_outputs(experiment_dir)

    simulate(
        experiment_dir, concurrency=1, stop=threading.Event(), console=_console()[0]
    )

    assert [path.exists() for path in evaluation_paths] == [False, False, False]


def test_a_stop_before_simulate_starts_keeps_the_evaluation(
    monkeypatch, tmp_path: Path
) -> None:
    experiment_dir = _experiment(tmp_path)
    _fake_trials(monkeypatch)
    evaluation_paths = _write_evaluation_outputs(experiment_dir)
    stop = threading.Event()
    stop.set()

    with pytest.raises(RunStopped):
        simulate(experiment_dir, concurrency=1, stop=stop, console=_console()[0])

    assert [path.exists() for path in evaluation_paths] == [True, True, True]


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


@pytest.mark.parametrize("function", [simulate, resume_simulation])
def test_a_folder_that_does_not_exist_raises_a_run_error_and_creates_nothing(
    tmp_path: Path, function
) -> None:
    missing = tmp_path / "no-such-experiment"
    console, text = _console()

    with pytest.raises(RunError):
        function(missing, concurrency=1, stop=threading.Event(), console=console)

    assert "does not exist" in text.getvalue()
    assert not missing.exists()


@pytest.mark.parametrize("function", [simulate, resume_simulation])
def test_a_folder_with_no_snapshot_raises_a_run_error(tmp_path: Path, function) -> None:
    folder = tmp_path / "not-an-experiment"
    folder.mkdir()
    console, text = _console()

    with pytest.raises(RunError):
        function(folder, concurrency=1, stop=threading.Event(), console=console)

    assert "no 'specification/' snapshot" in text.getvalue()
    assert list(folder.iterdir()) == []


@pytest.mark.parametrize("function", [simulate, resume_simulation])
@pytest.mark.parametrize(
    "snapshot",
    ["schema_version: 1\nid: [not, a, string\n", "schema_version: 1\nid: test-exp\n"],
    ids=["not-yaml", "not-a-specification"],
)
def test_a_snapshot_that_does_not_load_raises_and_writes_nothing(
    monkeypatch, tmp_path: Path, function, snapshot: str
) -> None:
    experiment_dir = _experiment(tmp_path)
    plans = _fake_trials(monkeypatch)
    simulate(
        experiment_dir, concurrency=1, stop=threading.Event(), console=_console()[0]
    )
    events = experiment_dir / execution_layout.LOGS / execution_layout.EVENTS_FILE
    before = events.read_bytes()
    outputs = sorted(p for p in (experiment_dir / "outputs").rglob("*"))
    (experiment_dir / execution_layout.SPECIFICATION).write_text(snapshot)
    console, text = _console()

    with pytest.raises(EvaluationInputError):
        function(experiment_dir, concurrency=1, stop=threading.Event(), console=console)

    assert "failed to load experiment snapshot" in text.getvalue()
    assert len(plans) == 1
    assert events.read_bytes() == before
    assert sorted(p for p in (experiment_dir / "outputs").rglob("*")) == outputs


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
    from metis.core import langfuse_links

    experiment_dir = _experiment(tmp_path)
    _fake_trials(monkeypatch)
    # With no logging configured, structlog prints the lookup's warning to stdout. The
    # CLI and the API send it to stderr, so it is not console output.
    monkeypatch.setattr(langfuse_links, "target_langfuse_project", lambda: None)
    console, text = _console()

    simulate(experiment_dir, concurrency=1, stop=threading.Event(), console=console)

    assert capsys.readouterr().out == ""
    assert "SIMULATION" in text.getvalue()
    assert "completed in" in text.getvalue()


def test_a_stop_before_the_trials_start_changes_nothing(
    monkeypatch, tmp_path: Path
) -> None:
    from tests.unit.engine.test_cli_simulate import _write_evaluation_outputs

    experiment_dir = _experiment(tmp_path, TWO_TRIAL_EXPERIMENT)
    _write_record(experiment_dir, "TC-001-alice-1", "goal_achieved")
    _write_record(experiment_dir, "TC-001-alice-2", "interrupted")
    evaluation_outputs = _write_evaluation_outputs(experiment_dir)
    plans = _fake_trials(monkeypatch)
    stop = threading.Event()
    stop.set()
    console, text = _console()

    with pytest.raises(RunStopped):
        resume_simulation(experiment_dir, concurrency=1, stop=stop, console=console)

    assert plans == []
    assert all(path.exists() for path in evaluation_outputs)
    assert "SIMULATION" not in text.getvalue()
    assert _events(experiment_dir)[-1] == ("simulating", "interrupted")


def test_the_trial_lines_and_the_summary_go_to_the_console_it_was_given(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    from metis.core.trials import TrialConfig, TrialOutcome, TrialRecord

    experiment_dir = _experiment(tmp_path)

    async def fake_worker(**kwargs: object) -> list[TrialRecord]:
        console = kwargs["console"]
        assert isinstance(console, Console)
        console.print("  [w0] worker line")
        _write_record(experiment_dir, "TC-001-alice-1")
        return [
            TrialRecord(
                config=TrialConfig(persona="alice", scenario="task-1"),
                outcome=TrialOutcome(
                    stop_reason="goal_achieved",
                    simulated_turns_completed=1,
                    duration_seconds=1.0,
                ),
            )
        ]

    monkeypatch.setattr(experiment_module, "_worker", fake_worker)
    console, text = _console()

    simulate(experiment_dir, concurrency=1, stop=threading.Event(), console=console)

    # structlog's defaults print log lines to stdout, so the check is on the console text
    stdout = capsys.readouterr().out
    assert "worker line" not in stdout
    assert "SIMULATION SUMMARY" not in stdout
    assert "worker line" in text.getvalue()
    assert "SIMULATION SUMMARY" in text.getvalue()
    assert "Goals achieved: 1/1" in text.getvalue()


def test_two_simulates_on_two_threads_keep_their_trial_logs_apart(
    monkeypatch, tmp_path: Path
) -> None:
    # One Specification for both, so both runs log under the same trial key.
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first = _experiment(tmp_path / "a")
    second = _experiment(tmp_path / "b")
    configure_logging(level="DEBUG")
    both_open = threading.Barrier(2, timeout=10)
    halfway = threading.Barrier(2, timeout=10)
    first_ended = threading.Event()

    def fake_execute_experiment(*_args: object, **kwargs: object) -> None:
        output_dir = kwargs["output_dir"]
        assert isinstance(output_dir, Path)
        router = kwargs["log_router"]
        router.open_trial("TC-001", "alice", trial_index=1, num_trials=1)  # type: ignore[union-attr]
        both_open.wait()
        log = get_logger("test.two_runs")
        for n in range(20):
            if n == 10:
                halfway.wait()
                if output_dir == second:
                    # The first run ends, and puts back its logging, while this one logs.
                    assert first_ended.wait(10)
            log.info(
                "step",
                scenario_id="TC-001",
                persona_id="alice",
                trial_index=1,
                run=str(output_dir),
                n=n,
            )
        router.close_trial("TC-001", "alice", trial_index=1)  # type: ignore[union-attr]
        _write_record(output_dir, "TC-001-alice-1")

    monkeypatch.setattr(
        experiment_module, "execute_experiment", fake_execute_experiment
    )
    errors: list[BaseException] = []

    def run(experiment_dir: Path) -> None:
        try:
            simulate(
                experiment_dir,
                concurrency=1,
                stop=threading.Event(),
                console=_console()[0],
            )
        except BaseException as exc:
            errors.append(exc)
        finally:
            if experiment_dir == first:
                first_ended.set()

    threads = [threading.Thread(target=run, args=(d,)) for d in (first, second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert errors == []
    for own, other in ((first, second), (second, first)):
        log_file = own / execution_layout.LOGS / "simulate-TC-001_alice-01.log"
        lines = [line for line in log_file.read_text().splitlines() if " step " in line]
        assert [f"n={n}" in line for n, line in enumerate(lines)] == [True] * 20
        # Both folders have the same name, in two project folders, so the tag is the path.
        assert all(
            f"run={own} " in line or line.endswith(f"run={own}") for line in lines
        )
        assert not any(f"run={other}" in line for line in lines)


def test_a_simulate_whose_orchestration_log_fails_puts_back_the_logging(
    monkeypatch, tmp_path: Path
) -> None:
    from metis.engine.logging import router as router_module
    from metis.engine.run import _simulation

    experiment_dir = _experiment(tmp_path)
    _fake_trials(monkeypatch)
    configure_logging(level="INFO")
    before = structlog.get_config()

    def no_orchestration_log(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(_simulation, "OrchestrationLogger", no_orchestration_log)

    with pytest.raises(OSError, match="disk full"):
        simulate(
            experiment_dir, concurrency=1, stop=threading.Event(), console=_console()[0]
        )

    assert structlog.get_config() == before
    assert router_module._install_count == 0


def test_simulate_looks_up_the_target_project_once_and_gives_it_to_the_trials(
    monkeypatch, tmp_path: Path
) -> None:
    from metis.core import langfuse_links
    from metis.core.langfuse_links import TargetProject

    experiment_dir = _experiment(tmp_path, TWO_TRIAL_EXPERIMENT)
    project = TargetProject("https://lf.example", "p1")
    lookups: list[object] = []

    def lookup(*args: object, **kwargs: object) -> TargetProject:
        lookups.append(args)
        return project

    monkeypatch.setattr(langfuse_links, "target_langfuse_project", lookup)
    given: list[object] = []

    def fake_execute_experiment(*_args: object, **kwargs: object) -> None:
        given.append(kwargs["target_project"])
        _write_record(kwargs["output_dir"], "TC-001-alice-1")  # type: ignore[arg-type]

    monkeypatch.setattr(
        experiment_module, "execute_experiment", fake_execute_experiment
    )

    simulate(
        experiment_dir, concurrency=1, stop=threading.Event(), console=_console()[0]
    )

    assert len(lookups) == 1
    assert given == [project]


def test_simulate_without_target_langfuse_keys_still_completes(
    monkeypatch, tmp_path: Path
) -> None:
    experiment_dir = _experiment(tmp_path)
    given: list[object] = []

    def fake_execute_experiment(*_args: object, **kwargs: object) -> None:
        given.append(kwargs["target_project"])
        _write_record(kwargs["output_dir"], "TC-001-alice-1")  # type: ignore[arg-type]

    monkeypatch.setattr(
        experiment_module, "execute_experiment", fake_execute_experiment
    )

    simulate(
        experiment_dir, concurrency=1, stop=threading.Event(), console=_console()[0]
    )

    assert given == [None]
    assert _events(experiment_dir)[-1] == ("simulating", "completed")
