"""What a grader returns, and what the orchestrator records from it.

A grader reaches a verdict by returning a ``score`` in [0, 1]; it never decides pass or fail.
The orchestrator applies the criterion's threshold and stores a ``RecordedResult``, so every
grader follows the same rule and a grader cannot return an outcome that contradicts its score.

A result that has no verdict is ``skipped`` or ``errored``. ``skipped`` means that the
grading worked, but the criterion does not apply to the session: the session can be read, and
the event that the measure looks for did not happen. ``errored`` means that the grader could
not reach a verdict: METIS could not read or find the evidence, a setting is missing or not
valid, or a grader LLM call failed or its reply could not be parsed. A ``Problem`` from the
trace processor is always ``errored``. Neither status says something about the target, so a
skip is never a pass and an error is never a fail. Both are left out of pass rates and
averages and reported separately.

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

    A grader that cannot judge the session returns one errored result with the reason, and a
    grader whose criterion does not apply to the session returns one skipped result. It never
    returns ``[]``. The orchestrator enforces that, replacing an empty output with a single errored
    result.
    """

    results: list[GraderResult]

    @classmethod
    def errored(cls, reason: str) -> Self:
        """One errored result for the whole run: the session cannot be judged, and why.

        For a session that can be read but that the criterion does not apply to, use
        ``skipped``."""
        return cls(results=[GraderResult(status="errored", reason=reason)])

    @classmethod
    def skipped(cls, reason: str) -> Self:
        """One skipped result for the whole run: the criterion does not apply to the session,
        and why.

        For a session that METIS cannot read, use ``errored``."""
        return cls(results=[GraderResult(status="skipped", reason=reason)])


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
