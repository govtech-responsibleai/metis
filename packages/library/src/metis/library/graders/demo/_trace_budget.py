"""DemoTraceBudgetGrader: the session stayed within a trace budget."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from pydantic import Field

from metis.core.grading import GraderResult, GradingOutput
from metis.core.trace_processing import Problem
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


class DemoTraceBudgetArgs(GraderArgs):
    max_traces: int = Field(
        default=10,
        ge=1,
        strict=True,
        description="Maximum number of traces allowed in the session.",
    )
    """The most traces the session may contain and still pass."""


class DemoTraceBudgetGrader(Grader[DemoTraceBudgetArgs]):
    """Demo: the session stayed within the allowed number of traces.

    The simplest use of the trace processor. Code-based and session-scoped: counts every recorded
    turn, including those whose target failed, and scores 1.0 when the count is at most
    ``max_traces`` and 0.0 otherwise. Errors on a session with no traces, since there is nothing
    to count. One trace is usually one persona message and the target's reply, so this is a
    budget on exchanges.
    """

    args_model = DemoTraceBudgetArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.TASK_CONSTRAINT_ADHERENCE,
        scopes=(Scope.SESSION,),
        grader_types=(GraderType.DETERMINISTIC,),
        reference_types=(ReferenceType.POLICY_RULE,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        selected = SCOPE_DEFINITIONS[self.scope].select(input, self.args)
        if isinstance(selected, Problem):
            return GradingOutput.errored("The session has no traces to count.")
        count, budget = len(selected["session"]), self.args.max_traces
        return GradingOutput(
            results=[
                GraderResult(
                    status="scored",
                    score=1.0 if count <= budget else 0.0,
                    reason=f"The session used {count} trace(s) against a budget of {budget}.",
                    scope="session",
                )
            ]
        )
