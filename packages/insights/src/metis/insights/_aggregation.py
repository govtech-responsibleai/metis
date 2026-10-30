from __future__ import annotations

from dataclasses import dataclass
from math import fsum, isfinite, sqrt
from statistics import NormalDist
from typing import TYPE_CHECKING, Literal

from metis.insights._models import WilsonConfidenceInterval

if TYPE_CHECKING:
    from collections.abc import Iterable

    from metis.core.grading import RecordedResult
    from metis.core.reporting import GraderRecord


@dataclass(frozen=True)
class GraderRunSummary:
    score: float | None
    threshold: float | None
    outcome: Literal["passed", "failed", "skipped", "errored"]


def summarize_run(record: GraderRecord) -> GraderRunSummary:
    # A record holds one result per scope item, each already combined by its grader.
    # TODO: decide how one record's results combine; until then, use an equal-weight mean.
    scores = [result.score for result in record.results if result.score is not None]
    if not scores:
        outcome = (
            "errored"
            if any(r.outcome == "errored" for r in record.results)
            else "skipped"
        )
        return GraderRunSummary(None, None, outcome)
    threshold = record.grader_args.get("threshold")
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not isfinite(threshold)
        or not 0 <= threshold <= 1
    ):
        raise ValueError(
            f"Invalid recorded threshold for {record.task_id} / trial {record.trial_index} / "
            f"session {record.session_id} / {record.criterion_id} / {record.grader_fqn}: "
            "expected a finite number from 0 to 1"
        )
    score = fsum(scores) / len(scores)
    return GraderRunSummary(
        score, float(threshold), "passed" if score >= threshold else "failed"
    )


@dataclass
class OutcomeCounts:
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errored: int = 0
    score_sum: float = 0.0

    def add(self, result: RecordedResult | GraderRunSummary) -> None:
        if result.outcome == "passed":
            self.passed += 1
        elif result.outcome == "failed":
            self.failed += 1
        elif result.outcome == "skipped":
            self.skipped += 1
        else:
            self.errored += 1
        if result.score is not None:
            self.score_sum += result.score

    def merge(self, other: OutcomeCounts) -> None:
        self.passed += other.passed
        self.failed += other.failed
        self.skipped += other.skipped
        self.errored += other.errored
        self.score_sum += other.score_sum

    @property
    def evaluated(self) -> int:
        return self.passed + self.failed

    @property
    def total(self) -> int:
        return self.evaluated + self.skipped + self.errored

    @property
    def pass_rate(self) -> float | None:
        return self.passed / self.evaluated if self.evaluated else None

    @property
    def average_score(self) -> float | None:
        return self.score_sum / self.evaluated if self.evaluated else None

    def as_dict(self) -> dict[str, int]:
        return {
            "pass": self.passed,
            "fail": self.failed,
            "skip": self.skipped,
            "error": self.errored,
        }


def mean_of(values: Iterable[float | None]) -> float | None:
    """Return the unweighted mean of the values that exist, or `None` if none exist."""
    present = [value for value in values if value is not None]
    return fsum(present) / len(present) if present else None


def aggregate_graders(
    records: Iterable[GraderRecord],
) -> dict[tuple[str, str], OutcomeCounts]:
    counts: dict[tuple[str, str], OutcomeCounts] = {}
    for record in records:
        bucket = counts.setdefault(
            (record.criterion_id, record.grader_fqn), OutcomeCounts()
        )
        bucket.add(summarize_run(record))
    return counts


def wilson_interval(passed: int, failed: int) -> WilsonConfidenceInterval | None:
    n = passed + failed
    if n == 0:
        return None
    # Wilson keeps bounds in [0, 1] and retains uncertainty when all trials pass or fail.
    # The normal (Wald) interval has zero width in those cases.
    z_squared = NormalDist().inv_cdf(0.975) ** 2
    proportion = passed / n
    denominator = 1 + z_squared / n
    center = (proportion + z_squared / (2 * n)) / denominator
    margin = (
        sqrt(z_squared * (proportion * (1 - proportion) / n + z_squared / (4 * n * n)))
        / denominator
    )
    return WilsonConfidenceInterval(
        lower=0.0 if passed == 0 else max(0.0, center - margin),
        upper=1.0 if failed == 0 else min(1.0, center + margin),
    )
