"""MonetaryCostGrader: the session stayed within a monetary cost budget."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from pydantic import Field

from metis.core.grading import GraderResult, GradingOutput
from metis.core.trace_processing import Problem, turns, usage_of
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


class MonetaryCostArgs(GraderArgs):
    max_cost: float = Field(
        gt=0,
        strict=True,
        description="Maximum monetary cost in USD allowed for the session.",
    )
    """The most the session may cost (USD) and still pass."""


class MonetaryCostGrader(Grader[MonetaryCostArgs]):
    """The session stayed within the allowed monetary cost.

    Reads cost data recorded by the trace source, in USD. Uses Langfuse's ``costDetails`` or
    ``calculatedTotalCost`` from each GENERATION observation. Grader costs are not included.
    """

    args_model = MonetaryCostArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.MONETARY_COST,
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
        usage = usage_of(turns(input.traces))
        if isinstance(usage, Problem):
            return GradingOutput.errored(usage.detail)
        cost = usage.cost
        if cost is None:
            return GradingOutput.errored(
                "Token usage was recorded but no observation has cost data."
            )
        budget = self.args.max_cost
        return GradingOutput(
            results=[
                GraderResult(
                    status="scored",
                    score=1.0 if cost <= budget else 0.0,
                    reason=f"The session cost ${cost:.4f} USD against a budget of "
                    f"${budget:.4f} USD.",
                    scope="session",
                    measurements={"cost_usd": cost},
                )
            ]
        )
