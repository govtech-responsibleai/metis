"""A small recorded experiment for insights report contract tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import yaml

from metis.core import SessionTraces, execution_layout
from metis.core.grading import RecordedResult
from metis.core.reporting import EvaluationResults, GraderRecord
from metis.core.traces import Observation, Trace
from metis.core.trials import TrialConfig, TrialOutcome, TrialRecord

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


# One feature. B-1 has two criteria, B-2 has one. Two test cases with two trials each.
TASKS = {"T-1": "S-1", "T-2": "S-2"}
GRADERS = {"C-1": "g.one.Grader", "C-2": "g.two.Grader", "C-3": "g.three.Grader"}


def specification() -> dict[str, Any]:
    def criterion(cid: str) -> dict[str, Any]:
        return {
            "id": cid,
            "description": f"The response meets check {cid}.",
            "grader_fqn": GRADERS[cid],
            "grader_args": {"threshold": 0.5},
        }

    def behaviour(bid: str, criteria: list[str]) -> dict[str, Any]:
        return {
            "id": bid,
            "name": bid,
            "description": f"{bid}. Detail.",
            "measured": True,
            "criteria": [criterion(cid) for cid in criteria],
        }

    return {
        "target": {"name": "Target"},
        "features": [
            {
                "id": "F-1",
                "name": "Feature one",
                "behaviours": [
                    behaviour("B-1", ["C-1", "C-2"]),
                    behaviour("B-2", ["C-3"]),
                ],
            }
        ],
        "personas": [{"id": "P-1", "description": "Persona"}],
        "scenarios": [
            {"id": "S-1", "description": "One"},
            {"id": "S-2", "description": "Two"},
        ],
        "tasks": [
            {
                "id": task_id,
                "scenario_ref": scenario,
                "persona_ref": "P-1",
                "num_trials": 2,
                "behaviour_refs": ["B-1", "B-2"],
            }
            for task_id, scenario in TASKS.items()
        ],
    }


def grader_record(
    task_id: str,
    trial: int,
    cid: str,
    *results: float | str,
    threshold: object = 0.5,
    model: str = "judge-a",
) -> GraderRecord:
    """Build one grader run. A float is a scored result; a string is an unscored outcome."""
    recorded = []
    for value in results:
        if isinstance(value, str):
            recorded.append(
                RecordedResult.model_validate({"outcome": value, "reason": value})
            )
        else:
            outcome = "passed" if value >= 0.5 else "failed"
            recorded.append(
                RecordedResult(outcome=outcome, score=value, reason="scored")
            )
    return GraderRecord(
        session_id=f"{task_id}-{trial}",
        scenario_id=TASKS[task_id],
        task_id=task_id,
        trial_index=trial,
        criterion_id=cid,
        grader_fqn=GRADERS[cid],
        grader_args={"threshold": threshold, "model": model},
        results=recorded,
    )


def grader_records() -> list[GraderRecord]:
    """C-1: four runs, all pass. C-2: one run, fails. C-3: skipped and errored only."""
    return [
        grader_record("T-1", 1, "C-1", 1.0, 0.8),
        grader_record("T-1", 2, "C-1", 0.6),
        grader_record("T-2", 1, "C-1", 0.9),
        grader_record("T-2", 2, "C-1", 0.7),
        grader_record("T-1", 1, "C-2", 0.2),
        grader_record("T-1", 1, "C-3", "skipped"),
        grader_record("T-2", 1, "C-3", "errored"),
    ]


def trial_record(
    task_id: str, trial: int, stop_reason: str = "goal_achieved"
) -> TrialRecord:
    return TrialRecord(
        config=TrialConfig(
            task_id=task_id, trial_index=trial, persona="P-1", scenario=TASKS[task_id]
        ),
        outcome=TrialOutcome(
            stop_reason=stop_reason, simulated_turns_completed=3, duration_seconds=1.0
        ),
        target_session_id=f"{task_id}-{trial}",
    )


def write_experiment(root: Path, records: list[GraderRecord]) -> Path:
    (root / "inputs").mkdir(parents=True)
    (root / "inputs/specification.yaml").write_text(yaml.safe_dump(specification()))
    for task_id in TASKS:
        for trial in (1, 2):
            trial_dir = root / "outputs/trials" / f"{task_id}-{trial}"
            trial_dir.mkdir(parents=True)
            (trial_dir / "record.json").write_text(
                trial_record(task_id, trial).model_dump_json()
            )
    results_path = root / "outputs/reports/results.json"
    EvaluationResults(run_id="run-1", records=records).save(results_path)
    return results_path


def save_trial_traces(root: Path, session_id: str, traces: Sequence[Trace]) -> Path:
    """Save traces where `metis engine evaluate` puts them for one trial session."""
    path = root / execution_layout.TRACES / execution_layout.trace_file_name(session_id)
    SessionTraces.from_traces(session_id, traces).save(path)
    return path


def turn_trace(index: int, user: str, reply: str | None) -> Trace:
    """One trace whose root observation is one user message and the target's reply."""
    root = Observation(
        id=f"o{index}", trace_id=f"t{index}", type="SPAN", input=user, output=reply
    )
    return Trace(id=f"t{index}", session_id="any", observations=(root,))
