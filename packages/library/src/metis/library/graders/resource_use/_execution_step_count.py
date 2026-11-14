"""ExecutionStepCountGrader: the session stayed within an execution-step budget."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from pydantic import Field

from metis.core.grading import GraderResult, GradingOutput
from metis.core.trace_processing import Problem, execution_step_count
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


class ExecutionStepCountArgs(GraderArgs):
    max_steps: int = Field(
        ge=1,
        strict=True,
        description="Maximum number of execution steps allowed in the session.",
    )
    """The most execution steps the session may take and still pass."""


class ExecutionStepCountGrader(Grader[ExecutionStepCountArgs]):
    """The session stayed within the allowed number of execution steps.

    One execution step is one non-root observation of type GENERATION, TOOL, or AGENT. SPAN
    observations are structural grouping and excluded. This counts model calls, tool calls, and
    sub-agent invocations independently.
    """

    args_model = ExecutionStepCountArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.EXECUTION_STEP_COUNT,
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
        count = execution_step_count(input.traces)
        budget = self.args.max_steps
        return GradingOutput(
            results=[
                GraderResult(
                    status="scored",
                    score=1.0 if count <= budget else 0.0,
                    reason=f"The session took {count} execution step(s) against a "
                    f"budget of {budget}.",
                    scope="session",
                    measurements={"execution_steps": float(count)},
                )
            ]
        )
