"""EvaluationResults: the results.json file `metis engine evaluate` writes.

Same version guard as TrialRecord: an explicit schema_version we cannot read fails loudly on
load; a missing key takes the default.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from metis.core.grading import RecordedResult
from metis.core.reporting import (
    _EVALUATION_RESULTS_VERSION,
    EvaluationResults,
    GraderRecord,
)


def _record(**overrides: object) -> GraderRecord:
    fields: dict[str, object] = {
        "session_id": "s-1",
        "scenario_id": "direct-question",
        "task_id": "TC-001",
        "trial_index": 1,
        "criterion_id": "AC-UNI-22",
        "grader_fqn": "metis.library.graders.demo.DemoTraceBudgetGrader",
        "grader_args": {"threshold": 0.5, "max_traces": 4},
        "results": [
            RecordedResult(outcome="passed", score=1.0, reason="routed → analyst")
        ],
    }
    fields.update(overrides)
    return GraderRecord.model_validate(fields)


def _results() -> EvaluationResults:
    return EvaluationResults(
        run_id="report",
        records=[
            _record(),
            _record(
                criterion_id="AC-2",
                results=[
                    RecordedResult(outcome="skipped", reason="no output"),
                    RecordedResult(outcome="errored", reason="judge reply unparseable"),
                ],
            ),
        ],
        timings={"graders_seconds": 1.2},
        latency_seconds=1.2,
    )


class TestVersion:
    def test_current_version_is_1(self) -> None:
        assert _EVALUATION_RESULTS_VERSION == 1
        loaded = EvaluationResults.model_validate({"schema_version": 1, "run_id": "r"})
        assert loaded.records == []
        assert loaded.latency_seconds is None

    def test_missing_version_takes_the_default(self) -> None:
        assert EvaluationResults.model_validate({"run_id": "r"}).schema_version == 1

    def test_unsupported_version_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Unsupported schema_version 99"):
            EvaluationResults.model_validate({"schema_version": 99, "run_id": "r"})

    @pytest.mark.parametrize("old_key", ["turn_results", "session_results"])
    def test_the_old_turn_and_session_format_is_rejected(self, old_key: str) -> None:
        """The old format has the same schema_version, so its keys are what tell it apart."""
        with pytest.raises(ValidationError, match="re-run `metis engine evaluate`"):
            EvaluationResults.model_validate(
                {"schema_version": 1, "run_id": "r", old_key: []}
            )


class TestGraderRecord:
    def test_requires_at_least_one_result(self) -> None:
        with pytest.raises(ValidationError, match="results"):
            _record(results=[])

    def test_keeps_resolved_grader_args(self) -> None:
        record = _record(grader_args={"threshold": 0.8, "model": "gpt-4o"})
        assert record.grader_args["model"] == "gpt-4o"


class TestFile:
    def test_round_trips_through_a_file_as_utf8(self, tmp_path: Path) -> None:
        original = _results()
        path = tmp_path / "reports" / "results.json"

        original.save(path)

        text = path.read_bytes().decode("utf-8")
        assert text.endswith("\n")
        assert "→" in text
        assert EvaluationResults.load_file(path) == original

    def test_malformed_json_raises_validation_error(self, tmp_path: Path) -> None:
        path = tmp_path / "results.json"
        path.write_text("{", encoding="utf-8")
        with pytest.raises(ValidationError):
            EvaluationResults.load_file(path)

    def test_wrong_version_in_a_file_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "results.json"
        path.write_text('{"schema_version": 99, "run_id": "r"}', encoding="utf-8")
        with pytest.raises(ValidationError, match="different version of metis-engine"):
            EvaluationResults.load_file(path)

    def test_missing_file_raises_oserror(self, tmp_path: Path) -> None:
        with pytest.raises(OSError):
            EvaluationResults.load_file(tmp_path / "absent.json")
