"""The engine-private per-trial evaluation file."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from metis.core.grading import RecordedResult
from metis.core.reporting import GraderRecord
from metis.engine.evaluation.trial_files import (
    TrialEvaluation,
    grading_seconds,
    load_trial_evaluations,
    save_trial_evaluation,
    trial_evaluation_path,
)

if TYPE_CHECKING:
    from pathlib import Path

_T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _record() -> GraderRecord:
    return GraderRecord(
        session_id="s1",
        scenario_id="sc",
        task_id="tk",
        trial_index=0,
        criterion_id="c",
        grader_fqn="pkg.grader",
        grader_args={"k": 1},
        results=[RecordedResult(outcome="passed", score=1.0, reason="ok")],
    )


def _evaluation(
    trial: str = "t1",
    start: float = 0,
    end: float = 1,
    records: list[GraderRecord] | None = None,
    failure_reason: str | None = None,
) -> TrialEvaluation:
    return TrialEvaluation(
        trial=trial,
        records=[_record()] if records is None else records,
        failure_reason=failure_reason,
        started_at=_T0 + timedelta(seconds=start),
        finished_at=_T0 + timedelta(seconds=end),
    )


def _valid_json(**overrides: object) -> str:
    data = _evaluation().model_dump(mode="json") | overrides
    return json.dumps(data)


def test_a_saved_evaluation_loads_back_equal(tmp_path: Path) -> None:
    saved = _evaluation()
    save_trial_evaluation(tmp_path, saved)
    assert load_trial_evaluations(tmp_path, ["t1"]) == {"t1": saved}


def test_failed_trial_keeps_its_reason(tmp_path: Path) -> None:
    saved = _evaluation(records=[], failure_reason="No traces found in Langfuse")
    save_trial_evaluation(tmp_path, saved)
    loaded = load_trial_evaluations(tmp_path, ["t1"])
    assert loaded["t1"].failure_reason == "No traces found in Langfuse"
    assert loaded["t1"].records == []


@pytest.mark.parametrize(
    "content",
    ["", '{"schema_version": 1, "trial"', "not json", _valid_json(schema_version=2)],
)
def test_a_bad_file_counts_as_not_attempted(tmp_path: Path, content: str) -> None:
    path = trial_evaluation_path(tmp_path, "t1")
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")
    assert load_trial_evaluations(tmp_path, ["t1"]) == {}


def test_a_file_naming_another_trial_counts_as_not_attempted(tmp_path: Path) -> None:
    path = trial_evaluation_path(tmp_path, "t1")
    path.parent.mkdir(parents=True)
    path.write_text(_valid_json(trial="other"), encoding="utf-8")
    assert load_trial_evaluations(tmp_path, ["t1"]) == {}


def test_a_naive_timestamp_is_rejected(tmp_path: Path) -> None:
    path = trial_evaluation_path(tmp_path, "t1")
    path.parent.mkdir(parents=True)
    path.write_text(_valid_json(started_at="2026-01-01T00:00:00"), encoding="utf-8")
    assert load_trial_evaluations(tmp_path, ["t1"]) == {}


def test_files_of_trials_not_in_the_experiment_are_ignored_and_kept(
    tmp_path: Path,
) -> None:
    save_trial_evaluation(tmp_path, _evaluation("gone"))
    save_trial_evaluation(tmp_path, _evaluation("t1"))
    assert list(load_trial_evaluations(tmp_path, ["t1"])) == ["t1"]
    assert trial_evaluation_path(tmp_path, "gone").exists()


def test_results_come_back_in_the_order_asked(tmp_path: Path) -> None:
    save_trial_evaluation(tmp_path, _evaluation("a"))
    save_trial_evaluation(tmp_path, _evaluation("b"))
    assert list(load_trial_evaluations(tmp_path, ["b", "a"])) == ["b", "a"]


def test_grading_time_counts_overlap_once_and_gaps_not_at_all() -> None:
    a = _evaluation("a", 0, 10)
    b = _evaluation("b", 3, 7)
    c = _evaluation("c", 20, 25)
    assert grading_seconds([c, a, b]) == 15.0


def test_grading_time_of_nothing_is_zero() -> None:
    assert grading_seconds([]) == 0.0
