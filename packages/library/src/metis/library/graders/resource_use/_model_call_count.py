"""ModelCallCountGrader: the session stayed within a model-call budget."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from pydantic import Field

from metis.core.grading import GraderResult, GradingOutput
from metis.core.trace_processing import Problem, generation_count
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


class ModelCallCountArgs(GraderArgs):
    max_calls: int = Field(
        ge=1,
        strict=True,
        description="Maximum number of model calls allowed in the session.",
    )
    """The most model calls the session may make and still pass."""


class ModelCallCountGrader(Grader[ModelCallCountArgs]):
    """The session stayed within the allowed number of model calls.

    Counts every GENERATION observation, including retries and failed attempts. Each GENERATION
    observation is one model-call attempt.
    """

    args_model = ModelCallCountArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.MODEL_CALL_COUNT,
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
        count = generation_count(input.traces)
        budget = self.args.max_calls
        return GradingOutput(
            results=[
                GraderResult(
                    status="scored",
                    score=1.0 if count <= budget else 0.0,
                    reason=f"The session made {count} model call(s) against a budget "
                    f"of {budget}.",
                    scope="session",
                )
            ]
        )
