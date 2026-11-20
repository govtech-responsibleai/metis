"""Offline checks for the Engine cases and their Touchstone verdicts export."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from metis.core import execution_layout as layout
from metis.core.grading import RecordedResult
from metis.core.reporting import EvaluationResults, GraderRecord
from metis.core.trials import TrialConfig, TrialOutcome, TrialRecord
from metis.engine.simulation.binding import load_target_binding
from metis.engine.simulation.types import Specification
from metis.testbed.regrade import http_root
from metis.testbed.touchstone import TouchstoneMap, export_verdicts, verdict

ENGINE = Path(__file__).resolve().parents[3] / "packages/testbed/engine"
ENGINE_CASES = sorted(path.parent for path in ENGINE.glob("*/*/touchstone.yaml"))
RUN_A = ENGINE / "skydesk/run-a"


def _result(outcome: str, reason: str = "-") -> RecordedResult:
    score = {"passed": 1.0, "failed": 0.0}.get(outcome)
    return RecordedResult.model_validate(
        {"outcome": outcome, "score": score, "reason": reason}
    )


def _write_run(
    root: Path,
    sessions: list[tuple[str, str | None, str]],
    outcomes: dict[tuple[str, str], str],
) -> Path:
    """An execution folder: a record per (Scenario, session ID, stop reason), and results."""
    experiment = root / "skydesk-run-a-20270301-120000"
    for index, (scenario, session_id, stop_reason) in enumerate(sessions):
        path = experiment / layout.TRIALS / f"trial-{index}" / layout.TRIAL_RECORD
        path.parent.mkdir(parents=True)
        record = TrialRecord(
            config=TrialConfig(task_id=f"TC-{index}", persona="P-1", scenario=scenario),
            outcome=TrialOutcome(
                stop_reason=stop_reason,
                simulated_turns_completed=2,
                duration_seconds=1.0,
            ),
            target_session_id=session_id,
        )
        path.write_text(record.model_dump_json(), encoding="utf-8")
    EvaluationResults(
        run_id="r",
        records=[
            GraderRecord(
                session_id=session_id,
                scenario_id="S-1",
                task_id="TC-0",
                trial_index=1,
                criterion_id=criterion_id,
                grader_fqn="metis.library.graders.CriterionJudgeGrader",
                grader_args={},
                results=[_result(outcome)],
            )
            for (session_id, criterion_id), outcome in outcomes.items()
        ],
    ).save(experiment / layout.RESULTS)
    return experiment


@pytest.mark.parametrize(
    "case", ENGINE_CASES, ids=lambda case: f"{case.parent.name}/{case.name}"
)
def test_each_engine_case_loads_for_the_engine_and_its_map_covers_it(
    case: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    specification = Specification.load_file(case / "specification.yaml")
    binding = case / specification.target_binding
    for name in re.findall(r"\$\{(\w+)\}", binding.read_text(encoding="utf-8")):
        monkeypatch.setenv(name, "http://127.0.0.1:8100")
    load_target_binding(case, specification.target_binding)
    mapping = TouchstoneMap.load_file(case / "touchstone.yaml")
    criteria = {c.id for b in specification.behaviours() for c in b.criteria}
    assert set(mapping.checks) == criteria
    assert set(mapping.scenarios) == {s.id for s in specification.scenarios}
    assert len(set(mapping.checks.values())) == len(mapping.checks)


def test_export_reports_each_session_under_the_suite_ids(tmp_path: Path) -> None:
    experiment = _write_run(
        tmp_path,
        [("S-1", "sd-1", "goal_achieved"), ("S-4", None, "system_error")],
        {("sd-1", "AC-2-1"): "failed", ("sd-1", "AC-9-9"): "passed"},
    )
    mapping = TouchstoneMap.load_file(RUN_A / "touchstone.yaml")
    exported = export_verdicts(experiment, mapping)

    assert exported["schema_version"] == 1
    assert exported["evaluator"].startswith("METIS ")
    assert exported["run"] == experiment.name
    first, second = exported["sessions"]
    assert first["session_id"] == "sd-1"
    assert first["scenario"] == "move-to-thursday"
    assert first["goal_achieved"] is True
    assert first["turns"] == 2
    # A criterion the map does not name is left out.
    assert first["verdicts"] == {"confirmation": {"verdict": "fail", "reason": "-"}}
    assert second["session_id"] is None
    assert second["scenario"] == "last-seat"
    assert second["goal_achieved"] is False
    assert second["verdicts"] == {}


@pytest.mark.parametrize(
    ("outcomes", "expected"),
    [
        (["passed", "failed"], "fail"),
        (["passed", "skipped"], "pass"),
        (["skipped", "skipped"], "skipped"),
    ],
)
def test_a_criterion_fails_if_any_result_failed(
    outcomes: list[str], expected: str
) -> None:
    assert verdict([_result(o) for o in outcomes]) == expected


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("No change or cancellation failed in this session.", "n/a"),
        (
            "The judge request needs about 177,231 estimated tokens; the limit is 128,000.",
            "errored",
        ),
        ("Judge failed: APIConnectionError: Connection error.", "errored"),
        ("The session has no turns.", "errored"),
    ],
)
def test_an_errored_result_does_not_apply_unless_metis_wrote_the_reason(
    reason: str, expected: str
) -> None:
    assert verdict([_result("errored", reason)]) == expected


def test_http_root_puts_the_request_and_endpoint_spans_above_the_turn() -> None:
    rows = (
        {"id": "turn", "parentObservationId": None, "traceId": "t"},
        {"id": "model", "parentObservationId": "turn", "traceId": "t"},
    )
    request, endpoint, turn, model = http_root(rows)
    assert request["parentObservationId"] is None
    assert request["isRootObservation"] == "True"
    assert endpoint["parentObservationId"] == request["id"]
    assert turn["parentObservationId"] == endpoint["id"]
    assert turn["isRootObservation"] == model["isRootObservation"] == "False"
    assert model["parentObservationId"] == "turn"
    assert rows[0]["parentObservationId"] is None
