"""Shared definitions for aggregation rules: how a multi-rule grader combines its rules.

A grader that checks several rules judges each rule on its own, then combines the rule
results with ``AGGREGATION_DEFINITIONS[grader.aggregation]`` into one result for each thing it
judged. A grader that checks one criterion declares ``none_single_score`` and does not combine
anything. The engine records the rule on ``GraderRecord.aggregation``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from metis.core.grading import GraderResult
from metis.library.taxonomy import Aggregation

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


def _single(results: Sequence[GraderResult], label: str) -> GraderResult:
    (result,) = results
    return result.model_copy(update={"scope": label})


def _pass_if_all(results: Sequence[GraderResult], label: str) -> GraderResult:
    """0 when any rule failed; else errored when any rule errored; else 1."""
    if failed := [r.reason for r in results if r.status == "scored" and r.score != 1.0]:
        return _result("scored", 0.0, "Not every rule is met", failed, label)
    if errored := [r.reason for r in results if r.status != "scored"]:
        return _result(
            "errored",
            None,
            "No rule failed, but some could not be judged",
            errored,
            label,
        )
    return _result("scored", 1.0, "Every rule is met", [], label)


def _pass_if_any(results: Sequence[GraderResult], label: str) -> GraderResult:
    """1 when any rule passed; else errored when any rule errored; else 0."""
    if passed := [r.reason for r in results if r.status == "scored" and r.score == 1.0]:
        return _result("scored", 1.0, "A rule is met", passed[:1], label)
    if errored := [r.reason for r in results if r.status != "scored"]:
        return _result(
            "errored",
            None,
            "No rule is met, and some could not be judged",
            errored,
            label,
        )
    return _result("scored", 0.0, "No rule is met", [r.reason for r in results], label)


def _result(
    status: str, score: float | None, summary: str, reasons: list[str], label: str
) -> GraderResult:
    reason = summary + (": " + " ".join(reasons) if reasons else ".")
    return GraderResult(status=status, score=score, reason=reason, scope=label)  # type: ignore[arg-type]


AGGREGATION_DEFINITIONS: dict[
    Aggregation, Callable[[Sequence[GraderResult], str], GraderResult]
] = {
    Aggregation.NONE_SINGLE_SCORE: _single,
    Aggregation.PASS_IF_ALL: _pass_if_all,
    Aggregation.PASS_IF_ANY: _pass_if_any,
}
