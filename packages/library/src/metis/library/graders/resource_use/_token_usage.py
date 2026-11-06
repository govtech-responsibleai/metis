"""TokenUsageGrader: the session stayed within a token budget."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Literal

from pydantic import Field

from metis.core.grading import GraderResult, GradingOutput
from metis.core.trace_processing import Problem, token_usage
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


class TokenUsageArgs(GraderArgs):
    max_total_tokens: int = Field(
        ge=1,
        strict=True,
        description="Maximum number of tokens allowed in the session.",
    )
    """The most tokens the session may consume and still pass."""

    token_category: Literal["input", "output", "total"] = Field(
        default="total",
        description="Which token category to measure: input, output, or total.",
    )
    """Which token category to count. Defaults to total."""


class TokenUsageGrader(Grader[TokenUsageArgs]):
    """The session stayed within the allowed number of tokens.

    Counts tokens recorded by the trace source across all GENERATION observations. Which token
    category is counted (input, output, or total) is set by ``token_category``; the default is
    total. Observations without usage data are not counted.
    """

    args_model = TokenUsageArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.TOKEN_USAGE,
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
        usage = token_usage(input.traces)
        if isinstance(usage, Problem):
            return GradingOutput.errored(usage.detail)
        category = self.args.token_category
        if category not in usage:
            return GradingOutput.errored(
                f"The token category {category!r} is not in the recorded usage data "
                f"(available: {', '.join(sorted(usage))})."
            )
        count = usage[category]
        budget = self.args.max_total_tokens
        return GradingOutput(
            results=[
                GraderResult(
                    status="scored",
                    score=1.0 if count <= budget else 0.0,
                    reason=f"The session used {count:,} {category} token(s) against a "
                    f"budget of {budget:,}.",
                    scope="session",
                )
            ]
        )
