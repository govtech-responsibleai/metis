"""What a grader returns, and what the orchestrator records from it.

A grader reaches a verdict by returning a ``score`` in [0, 1]; it never decides pass or fail.
The orchestrator applies the criterion's threshold and stores a ``RecordedResult``, so every
grader follows the same rule and a grader cannot return an outcome that contradicts its score.

``errored`` means the grader could not reach a verdict: the session lacks the evidence its
measure needs, the event it looks for did not happen, or a grader LLM call failed or its reply
could not be parsed. An error says something about the grading, not the target, so it is never
a fail. ``skipped`` is never a pass. Library graders do not return it; it stays for graders
outside the library. Both are left out of pass rates and averages and reported separately.

A result can also carry ``measurements``: the named numbers the grader computed on the way to
its result. A decision model records the probability of each question it was asked. These are
evidence for a reader, not scores, so nothing aggregates them. A result of any status can
carry them, because a grader that reaches no verdict can still report what it measured.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator


class GraderResult(BaseModel):
    """What a grader reports for one thing it judged: a recorded turn, a run of recorded turns,
    the session or a file."""

    status: Literal["scored", "skipped", "errored"]
    score: float | None = Field(default=None, ge=0, le=1)
    """In [0, 1] when ``status`` is ``"scored"``; always ``None`` otherwise."""
    reason: str
    scope: str | None = None
    """The label of what the result is about, such as ``"session"``, ``"turn:3"`` or
    ``"artifact:report.pdf"``. ``None`` when the grader does not divide the session."""
    measurements: dict[str, float] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    """The named numbers the grader computed to reach this result, such as a decision model's
    probability for each question. Reported as evidence and never scored. ``None`` when the
    grader measures nothing beyond its score."""

    @model_validator(mode="after")
    def _score_matches_status(self) -> Self:
        if self.status == "scored" and self.score is None:
            raise ValueError("a scored result needs a score")
        if self.status != "scored" and self.score is not None:
            raise ValueError(f"a {self.status} result must not carry a score")
        return self


class GradingOutput(BaseModel):
    """What one grader run returns: one result for each thing it judged.

    A grader that cannot judge the session returns one errored result with the reason, never
    ``[]``. The orchestrator enforces that, replacing an empty output with a single errored
    result.
    """

    results: list[GraderResult]

    @classmethod
    def errored(cls, reason: str) -> Self:
        """One errored result for the whole run: the session cannot be judged, and why."""
        return cls(results=[GraderResult(status="errored", reason=reason)])


class RecordedResult(BaseModel):
    """One ``GraderResult`` after the orchestrator has applied the threshold."""

    outcome: Literal["passed", "failed", "skipped", "errored"]
    score: float | None = Field(default=None, ge=0, le=1)
    """Set for passed and failed; ``None`` for skipped and errored."""
    reason: str
    scope: str | None = None
    """Carried through from ``GraderResult.scope``."""
    measurements: dict[str, float] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    """Carried through from ``GraderResult.measurements``."""

    @model_validator(mode="after")
    def _score_matches_outcome(self) -> Self:
        verdict = self.outcome in ("passed", "failed")
        if verdict and self.score is None:
            raise ValueError(f"a {self.outcome} result needs a score")
        if not verdict and self.score is not None:
            raise ValueError(f"a {self.outcome} result must not carry a score")
        return self
