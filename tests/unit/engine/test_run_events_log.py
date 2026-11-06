"""``metis engine run`` writes the progress of a run to logs/events.jsonl.

The test runs the real command with a fake runner, a scripted user agent and a fake
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

from metis.core.run_events import RunEventLog
from metis.core.traces import GradingInput, Observation, Trace
from metis.core.trials import TrialConfig, TrialOutcome, TrialRecord
from metis.engine import cli
from metis.engine.cli import app
from metis.engine.simulation.exceptions import ConsecutiveFailureEscalation
from metis.engine.simulation.experiment import (
    TrialPlanItem,
    _worker,
    trial_end_fields,
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
    path = repo_root / "packages/core/schemas/run-event.schema.json"
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


def _run(tmp_path: Path, *args: str) -> list[dict]:
    result = runner.invoke(app, ["run", *args, "--no-tui"])
    assert result.exit_code == 0, result.output
    run_folder = next((tmp_path / "project" / "experiments" / "execute").iterdir())
    path = run_folder / "logs" / "events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.usefixtures("fake_services")
def test_every_line_of_a_run_passes_the_published_schema(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, schema: dict
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "specification.yaml").write_text(SPECIFICATION)
    monkeypatch.setattr(cli, "_find_project_root", lambda: tmp_path / "project")

    events = _run(tmp_path, "--input-dir", str(input_dir))

    for event in events:
        jsonschema.validate(instance=event, schema=schema)
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    trial_events = [
        (event["type"], event.get("trial"))
        for event in events
        if event["type"] not in ("run_started", "phase_started", "run_ended")
    ]
    trials = ["TC-001-alice-1", "TC-001-alice-2"]
    assert trial_events == [
        *(
            pair
            for trial in trials
            for pair in [
                ("trial_started", trial),
                ("turn", trial),
                ("turn", trial),
                ("trial_ended", trial),
            ]
        ),
        *(
            pair
            for trial in trials
            for pair in [
                ("trace_wait_started", trial),
                ("trace_wait_ended", trial),
                ("grade", trial),
                ("trial_graded", trial),
            ]
        ),
    ]
    run_events = [event for event in events if event.get("trial") is None]
    assert [
        (event["type"], event.get("phase"), event.get("total")) for event in run_events
    ] == [
        ("run_started", None, None),
        ("phase_started", "simulating", 2),
        ("phase_started", "evaluating", 2),
        ("run_ended", None, None),
    ]
    assert run_events[-1]["status"] == "completed"
    grade = next(event for event in events if event["type"] == "grade")
    assert (grade["criterion_id"], grade["passed"]) == ("AC-1-1", 1)
    wait_end = next(event for event in events if event["type"] == "trace_wait_ended")
    assert (wait_end["outcome"], wait_end["traces"]) == ("found", 1)


@pytest.mark.usefixtures("fake_services")
def test_a_resumed_run_appends_and_continues_the_sequence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, schema: dict
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "specification.yaml").write_text(SPECIFICATION)
    monkeypatch.setattr(cli, "_find_project_root", lambda: tmp_path / "project")
    first = _run(tmp_path, "--input-dir", str(input_dir))
    run_folder = next((tmp_path / "project" / "experiments" / "execute").iterdir())
    record_path = run_folder / "outputs" / "trials" / "TC-001-alice-2" / "record.json"
    record = TrialRecord.load_file(record_path)
    record.outcome.stop_reason = "system_error"
    record_path.write_text(record.model_dump_json())

    events = _run(tmp_path, "--resume", "--experiment-dir", str(run_folder))

    resumed = events[len(first) :]
    assert events[: len(first)] == first
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    for event in resumed:
        jsonschema.validate(instance=event, schema=schema)
    assert resumed[0]["type"] == "run_started" and resumed[0]["resumed"] is True
    assert resumed[1] == {
        **resumed[1],
        "phase": "simulating",
        "total": 2,
        "done": 1,
        "trials": ["TC-001-alice-2"],
    }


@pytest.mark.asyncio
async def test_a_failed_attempt_writes_a_retry_and_the_trial_ends_failed(
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
    events = RunEventLog.for_run_folder(tmp_path)

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
    assert [line["type"] for line in lines] == [
        "trial_started",
        "trial_retry",
        "trial_ended",
    ]
    retry, ended = lines[1], lines[2]
    assert (retry["attempt"], retry["max_attempts"]) == (1, 2)
    assert retry["failure_type"] == "ConsecutiveFailureEscalation"
    assert retry["reason"] == "2 consecutive turn failures"
    assert (ended["status"], ended["failure_reason"]) == (
        "failed",
        "2 consecutive turn failures",
    )


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


def test_trial_end_status_follows_the_stop_reason() -> None:
    failed = trial_end_fields(
        _record("system_error", failure_message="fixture_never_uploaded: a.csv")
    )
    assert (failed["status"], failed["failure_reason"]) == (
        "failed",
        "fixture_never_uploaded: a.csv",
    )
    assert trial_end_fields(_record("interrupted"))["status"] == "interrupted"
    stopped = trial_end_fields(_record("max_turns"))
    assert (stopped["status"], stopped["failure_reason"]) == ("completed", None)
