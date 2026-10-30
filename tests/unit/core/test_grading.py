"""GraderResult / GradingOutput (what a grader returns) and RecordedResult (what is stored)."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from metis.core.grading import GraderResult, GradingOutput, RecordedResult


class TestGraderResult:
    @pytest.mark.parametrize("score", [0.0, 0.5, 1.0])
    def test_scored_accepts_scores_in_range(self, score: float) -> None:
        assert GraderResult(status="scored", score=score, reason="r").score == score

    @pytest.mark.parametrize("score", [-0.01, 1.01, math.nan])
    def test_scored_rejects_out_of_range_or_nan(self, score: float) -> None:
        with pytest.raises(ValidationError):
            GraderResult(status="scored", score=score, reason="r")

    def test_scored_requires_a_score(self) -> None:
        with pytest.raises(ValidationError, match="score"):
            GraderResult(status="scored", reason="r")

    @pytest.mark.parametrize("status", ["skipped", "errored"])
    def test_unscored_statuses_reject_a_score(self, status: str) -> None:
        with pytest.raises(ValidationError, match="score"):
            GraderResult(status=status, score=0.0, reason="r")  # type: ignore[arg-type]

    @pytest.mark.parametrize("status", ["skipped", "errored"])
    def test_unscored_statuses_default_score_to_none(self, status: str) -> None:
        assert GraderResult(status=status, reason="r").score is None  # type: ignore[arg-type]

    def test_reason_is_required(self) -> None:
        with pytest.raises(ValidationError, match="reason"):
            GraderResult(status="skipped")  # type: ignore[call-arg]

    def test_unknown_status_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GraderResult(status="passed", score=1.0, reason="r")  # type: ignore[arg-type]


class TestGradingOutput:
    def test_holds_results(self) -> None:
        out = GradingOutput(results=[GraderResult(status="skipped", reason="none")])
        assert len(out.results) == 1

    def test_empty_results_are_allowed_by_the_model(self) -> None:
        """The orchestrator, not the model, turns [] into an errored result."""
        assert GradingOutput(results=[]).results == []


class TestRecordedResult:
    @pytest.mark.parametrize("outcome", ["passed", "failed"])
    def test_verdicts_require_a_score(self, outcome: str) -> None:
        with pytest.raises(ValidationError, match="score"):
            RecordedResult(outcome=outcome, reason="r")  # type: ignore[arg-type]

    @pytest.mark.parametrize("outcome", ["skipped", "errored"])
    def test_non_verdicts_reject_a_score(self, outcome: str) -> None:
        with pytest.raises(ValidationError, match="score"):
            RecordedResult(outcome=outcome, score=1.0, reason="r")  # type: ignore[arg-type]

    def test_verdict_score_must_be_in_range(self) -> None:
        with pytest.raises(ValidationError):
            RecordedResult(outcome="passed", score=1.5, reason="r")
