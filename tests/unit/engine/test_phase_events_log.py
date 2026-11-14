"""``simulate``, ``evaluate`` and ``run`` write the progress of an experiment to
logs/events.jsonl.

The tests run the real commands with a fake runner, a scripted user agent and a fake
Langfuse fetch, so no service is called. Each line must pass the published schema.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import jsonschema
import pytest
from typer.testing import CliRunner

from metis.core.phase_events import INTERRUPTED_REASON, PhaseEventLog
from metis.core.traces import GradingInput, Observation, Trace
from metis.core.trials import TrialConfig, TrialOutcome, TrialRecord
from metis.engine import cli
from metis.engine.cli import app
from metis.engine.extractor.langfuse import NO_TRACES, TracesNotReadyError, TraceWait
from metis.engine.simulation.binding import TargetBindingError
from metis.engine.simulation.exceptions import ConsecutiveFailureEscalation
from metis.engine.simulation.experiment import (
    TrialPlanItem,
    _worker,
    trial_end_reason,
    trial_end_status,
)
from metis.engine.simulation.types import Persona, Scenario, UserAgentOutput
from tests.unit.engine.test_runner_ref import StubRunnerFactory

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()

FACTORY = "tests.unit.engine.test_runner_ref.StubRunnerFactory"
SPECIFICATION = f"""schema_version: 1
id: events-exp
runner_factory_ref: {FACTORY}
personas:
- id: alice
  name: alice
  description: test persona
scenarios:
- id: task-1
  name: task-1
  description: test scenario
target:
  name: Test target
  users: Test users
  description: Test target
tasks:
- id: TC-001
  scenario_ref: task-1
  persona_ref: alice
  fixtures: []
  num_trials: 2
  max_turns: 2
  behaviour_refs: [EB-1]
features:
- id: F-1
  name: Responses
  description: Responses
  behaviours:
  - id: EB-1
    name: Respond
    description: Respond correctly
    measured: true
    criteria:
    - id: AC-1-1
      name: Check 1
      description: "Given a request, when the agent responds, then it is met."
      grader_fqn: tests.unit.engine.graders_for_tests.FixedScoreGrader
      grader_args: {{}}
"""


class _TwoTurnAgent:
    """Sends two messages, then says the goal is met."""

    def __init__(self, **_kwargs: object) -> None:
        self._turns = 0

    async def decide(self, turn: int, *_args: object) -> UserAgentOutput:
        self._turns += 1
        if self._turns > 2:
            return UserAgentOutput(reasoning="r", action="", decision="goal_achieved")
        return UserAgentOutput(reasoning="r", action="Say ⟦hi⟧", decision="continue")

    def remember(self, *_args: object) -> None:
        pass


def _session(session_id: str) -> GradingInput:
    trace = Trace(
        id=f"{session_id}-t",
        session_id=session_id,
        observations=(Observation(id="o", trace_id=f"{session_id}-t", output="ok"),),
    )
    return GradingInput(traces=(trace,))


@pytest.fixture
def schema(repo_root: Path) -> dict:
    path = repo_root / "packages/core/schemas/phase-event.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def fake_services(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_configure_process_logging", lambda *_a, **_k: None)
    monkeypatch.setattr("metis.engine.simulation.trial.UserAgent", _TwoTurnAgent)
    monkeypatch.setattr(
        "tests.unit.engine.test_runner_ref.StubRunner.session_id",
        property(lambda _self: "session-1"),
    )
    monkeypatch.setattr("metis.engine.extractor.get_langfuse_client", lambda: object())

    async def fetch(session_id: str, *_args: object, **_kwargs: object) -> GradingInput:
        return _session(session_id)

    monkeypatch.setattr("metis.engine.extractor.fetch_session", fetch)


class UnboundRunnerFactory(StubRunnerFactory):
    """A factory whose target binding cannot be used."""

    @classmethod
    def from_specification(cls, *_args: object) -> UnboundRunnerFactory:
        raise TargetBindingError("binding.yaml: base_url is not set")


def _run(
    tmp_path: Path, *args: str, command: str = "run", exit_code: int = 0
) -> list[dict]:
    no_tui = [] if command == "evaluate" else ["--no-tui"]
    result = runner.invoke(app, [command, *args, *no_tui])
    assert result.exit_code == exit_code, result.output
    path = _run_folder(tmp_path) / "logs" / "events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _run_folder(tmp_path: Path) -> Path:
    return next((tmp_path / "project" / "experiments" / "execute").iterdir())


def _input_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "specification.yaml").write_text(SPECIFICATION)
    monkeypatch.setattr(cli, "find_project_root", lambda: tmp_path / "project")
    return input_dir


def _phases(events: list[dict]) -> list[tuple[str, str]]:
    """The phase and status of each line about a whole phase."""
    return [
        (event["phase"], event["status"]) for event in events if event["trial"] is None
    ]


def _trial_lines(events: list[dict], trial: str) -> list[tuple[str, str]]:
    """The phase and status of each line about ``trial``."""
    return [
        (event["phase"], event["status"]) for event in events if event["trial"] == trial
    ]


@pytest.mark.usefixtures("fake_services")
def test_every_line_of_an_experiment_passes_the_published_schema(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, schema: dict
) -> None:
    input_dir = _input_dir(monkeypatch, tmp_path)

    events = _run(tmp_path, "--input-dir", str(input_dir))

    for event in events:
        jsonschema.validate(instance=event, schema=schema)
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert _phases(events) == [
        ("simulating", "started"),
        ("simulating", "completed"),
        ("evaluating", "started"),
        ("evaluating", "completed"),
    ]
    for trial in ["TC-001-alice-1", "TC-001-alice-2"]:
        assert _trial_lines(events, trial) == [
            ("simulating", "started"),
            ("simulating", "running"),
            ("simulating", "running"),
            ("simulating", "completed"),
            ("evaluating", "started"),
            ("evaluating", "completed"),
        ]
    assert events[0] == {**events[0], "total": 2, "done": 0}
    turns = [event for event in events if event["status"] == "running"]
    assert [(event["attempt"], event["turn"]) for event in turns[:2]] == [
        (1, 1),
        (1, 2),
    ]


@pytest.mark.usefixtures("fake_services")
def test_a_resume_appends_and_continues_the_sequence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, schema: dict
) -> None:
    input_dir = _input_dir(monkeypatch, tmp_path)
    first = _run(tmp_path, "--input-dir", str(input_dir))
    run_folder = _run_folder(tmp_path)
    record_path = run_folder / "outputs" / "trials" / "TC-001-alice-2" / "record.json"
    record = TrialRecord.load_file(record_path)
    record.outcome.stop_reason = "interrupted"
    record_path.write_text(record.model_dump_json())

    events = _run(tmp_path, "--resume", "--experiment-dir", str(run_folder))

    resumed = events[len(first) :]
    assert events[: len(first)] == first
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    for event in resumed:
        jsonschema.validate(instance=event, schema=schema)
    assert resumed[0] == {
        **resumed[0],
        "phase": "simulating",
        "trial": None,
        "status": "started",
        "total": 2,
        "done": 1,
    }
    simulated = {event["trial"] for event in resumed if event["phase"] == "simulating"}
    assert simulated == {None, "TC-001-alice-2"}


@pytest.mark.usefixtures("fake_services")
def test_simulate_writes_only_the_simulating_phase(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, schema: dict
) -> None:
    input_dir = _input_dir(monkeypatch, tmp_path)

    events = _run(tmp_path, "--input-dir", str(input_dir), command="simulate")

    for event in events:
        jsonschema.validate(instance=event, schema=schema)
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert _phases(events) == [("simulating", "started"), ("simulating", "completed")]
    assert {event["phase"] for event in events} == {"simulating"}


@pytest.mark.usefixtures("fake_services")
def test_evaluate_appends_its_own_phase(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, schema: dict
) -> None:
    input_dir = _input_dir(monkeypatch, tmp_path)
    simulated = _run(tmp_path, "--input-dir", str(input_dir), command="simulate")

    events = _run(
        tmp_path,
        "--experiment-dir",
        str(_run_folder(tmp_path)),
        command="evaluate",
    )

    evaluated = events[len(simulated) :]
    assert events[: len(simulated)] == simulated
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    for event in evaluated:
        jsonschema.validate(instance=event, schema=schema)
    assert _phases(evaluated) == [
        ("evaluating", "started"),
        ("evaluating", "completed"),
    ]
    assert evaluated[0]["total"] == 2
    graded = [
        event["trial"]
        for event in evaluated
        if event["trial"] and event["status"] == "completed"
    ]
    assert graded == ["TC-001-alice-1", "TC-001-alice-2"]


@pytest.mark.usefixtures("fake_services")
def test_a_trial_that_cannot_be_graded_fails_with_its_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, schema: dict
) -> None:
    input_dir = _input_dir(monkeypatch, tmp_path)
    simulated = _run(tmp_path, "--input-dir", str(input_dir), command="simulate")

    async def no_traces(*_args: object, **_kwargs: object) -> GradingInput:
        raise TracesNotReadyError(TraceWait("no_traces", 2, 90.0))

    monkeypatch.setattr("metis.engine.extractor.fetch_session", no_traces)

    events = _run(
        tmp_path,
        "--experiment-dir",
        str(_run_folder(tmp_path)),
        command="evaluate",
    )

    evaluated = events[len(simulated) :]
    for event in evaluated:
        jsonschema.validate(instance=event, schema=schema)
    failed = [
        event for event in evaluated if event["trial"] and event["status"] == "failed"
    ]
    assert [event["reason"] for event in failed] == [NO_TRACES] * 2


@pytest.mark.usefixtures("fake_services")
def test_a_failed_phase_gives_its_reason_and_skips_the_later_phase(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, schema: dict
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "specification.yaml").write_text(
        SPECIFICATION.replace(FACTORY, f"{__name__}.UnboundRunnerFactory")
    )
    monkeypatch.setattr(cli, "find_project_root", lambda: tmp_path / "project")

    events = _run(tmp_path, "--input-dir", str(input_dir), exit_code=1)

    for event in events:
        jsonschema.validate(instance=event, schema=schema)
    assert _phases(events) == [
        ("simulating", "started"),
        ("simulating", "failed"),
        ("evaluating", "skipped"),
    ]
    assert events[-2]["reason"] == "binding.yaml: base_url is not set"


@pytest.mark.usefixtures("fake_services")
def test_a_simulation_with_no_records_fails_and_skips_evaluation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    input_dir = _input_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_trial_record_files", lambda _root: [])

    events = _run(tmp_path, "--input-dir", str(input_dir), exit_code=1)

    assert _phases(events)[-2:] == [("simulating", "failed"), ("evaluating", "skipped")]
    assert events[-2]["reason"] == "No trial records found."


@pytest.mark.asyncio
async def test_each_attempt_of_a_trial_is_numbered_and_the_last_one_fails(
    tmp_path: Path, schema: dict
) -> None:
    scenario = Scenario(
        id="task-1",
        task_id="TC-001",
        description="s",
        persona_refs=["alice"],
        max_trial_retries=1,
    )
    persona = Persona(id="alice", name="alice", description="p")
    events = PhaseEventLog.for_experiment_dir(tmp_path)

    with patch("metis.engine.simulation.trial.Orchestrator") as orchestrator:
        orchestrator.return_value.execute = AsyncMock(
            side_effect=ConsecutiveFailureEscalation("2 consecutive turn failures")
        )
        orchestrator.return_value.partial_record = MagicMock(
            return_value=_record("system_error")
        )
        await _worker(
            worker_id=0,
            runner_factory=StubRunnerFactory(),
            worker_trials=[TrialPlanItem(scenario, persona, 1)],
            experiment_root=tmp_path,
            fixtures_dir=tmp_path / "fixtures",
            fixture_content_descriptions={},
            console_lock=asyncio.Lock(),
            started_scenarios=set(),
            trial_max_retries=2,
            trial_retry_delay_seconds=0.0,
            events=events,
        )

    lines = [json.loads(line) for line in events.path.read_text().splitlines()]
    for line in lines:
        jsonschema.validate(instance=line, schema=schema)
    assert [(line["status"], line["attempt"]) for line in lines] == [
        ("started", 1),
        ("retrying", 1),
        ("started", 2),
        ("failed", 2),
    ]
    retry, ended = lines[1], lines[3]
    assert retry["reason"] == (
        "ConsecutiveFailureEscalation: 2 consecutive turn failures"
    )
    assert ended["reason"] == "2 consecutive turn failures"


@pytest.mark.asyncio
async def test_a_trial_ends_when_its_events_cannot_be_written(tmp_path: Path) -> None:
    scenario = Scenario(
        id="task-1", task_id="TC-001", description="s", persona_refs=["alice"]
    )
    persona = Persona(id="alice", name="alice", description="p")
    (tmp_path / "logs").write_text("a file where the logs folder should be")

    with patch("metis.engine.simulation.trial.Orchestrator") as orchestrator:
        orchestrator.return_value.execute = AsyncMock(
            return_value=_record("goal_achieved")
        )
        records = await _worker(
            worker_id=0,
            runner_factory=StubRunnerFactory(),
            worker_trials=[TrialPlanItem(scenario, persona, 1)],
            experiment_root=tmp_path,
            fixtures_dir=tmp_path / "fixtures",
            fixture_content_descriptions={},
            console_lock=asyncio.Lock(),
            started_scenarios=set(),
            trial_max_retries=1,
            trial_retry_delay_seconds=0.0,
            events=PhaseEventLog.for_experiment_dir(tmp_path),
        )

    assert [record.outcome.stop_reason for record in records] == ["goal_achieved"]


def _record(stop_reason: str, **outcome: object) -> TrialRecord:
    return TrialRecord(
        config=TrialConfig(persona="alice", scenario="task-1"),
        outcome=TrialOutcome(
            stop_reason=stop_reason,
            simulated_turns_completed=1,
            duration_seconds=2.0,
            **outcome,  # type: ignore[arg-type]
        ),
    )


def test_how_a_trial_ends_follows_its_stop_reason() -> None:
    failed = _record("system_error", failure_message="fixture_never_uploaded: a.csv")
    assert (trial_end_status(failed), trial_end_reason(failed)) == (
        "failed",
        "fixture_never_uploaded: a.csv",
    )
    interrupted = _record("interrupted")
    assert (trial_end_status(interrupted), trial_end_reason(interrupted)) == (
        "interrupted",
        INTERRUPTED_REASON,
    )
    stopped = _record("max_turns")
    assert (trial_end_status(stopped), trial_end_reason(stopped)) == ("completed", None)
