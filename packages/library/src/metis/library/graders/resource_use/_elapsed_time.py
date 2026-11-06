"""ElapsedTimeGrader: the session completed within a time budget."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from pydantic import Field

from metis.core.grading import GraderResult, GradingOutput
from metis.core.trace_processing import Problem, session_elapsed_seconds
from metis.library.grader import Grader, GraderArgs
from metis.library.scope import SCOPE_DEFINITIONS
from metis.library.taxonomy import (
    Aggregation,
    GraderTaxonomy,
    GraderType,
    JudgmentForm,
    Measure,
    ReferenceType,
    Scope,
)

if TYPE_CHECKING:
    from metis.core.traces import GradingInput
    from metis.library.grader import LLMSettings


class ElapsedTimeArgs(GraderArgs):
    max_seconds: float = Field(
        gt=0,
        strict=True,
        description="Maximum wall-clock seconds allowed for the session.",
    )
    """The most seconds the session may take and still pass."""


class ElapsedTimeGrader(Grader[ElapsedTimeArgs]):
    """The session completed within the allowed wall-clock time.

    Measures the elapsed seconds from the first recorded turn's start to the last recorded
    turn's end.
    """

    args_model = ElapsedTimeArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.ELAPSED_TIME,
        scopes=(Scope.SESSION,),
        grader_types=(GraderType.DETERMINISTIC,),
        reference_types=(ReferenceType.POLICY_RULE,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        selected = SCOPE_DEFINITIONS[self.scope].select(input, self.args)
        if isinstance(selected, Problem):
            return GradingOutput.errored("The session has no traces to measure.")
        elapsed = session_elapsed_seconds(input.traces)
        if isinstance(elapsed, Problem):
            return GradingOutput.errored(elapsed.detail)
        budget = self.args.max_seconds
        return GradingOutput(
            results=[
                GraderResult(
                    status="scored",
                    score=1.0 if elapsed <= budget else 0.0,
                    reason=f"The session took {elapsed:.1f} second(s) against a budget "
                    f"of {budget:.1f}.",
                    scope="session",
                )
            ]
        )
