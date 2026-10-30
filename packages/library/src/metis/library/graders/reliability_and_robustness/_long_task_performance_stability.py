"""LongTaskPerformanceStabilityGrader: performance holds as the task gets longer."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from pydantic import Field

from metis.core.grading import GradingOutput
from metis.core.trace_processing import Problem, turns
from metis.library.grader import Grader, JudgeArgs
from metis.library.judge import TaskArgs, judge
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


class LongTaskPerformanceStabilityArgs(JudgeArgs, TaskArgs):
    """Settings for the long-task performance stability assessment."""

    min_turns: int = Field(
        default=4,
        ge=2,
        strict=True,
        description=(
            "Sessions with fewer recorded turns are errored, because a short session "
            "cannot show a drop."
        ),
    )


class LongTaskPerformanceStabilityGrader(Grader[LongTaskPerformanceStabilityArgs]):
    """Assess whether performance holds as the number of dependent steps increases.

    Session scope, because a drop is a relation between early and late recorded turns. The
    judge reads the whole session and compares the later recorded turns with the earlier ones.
    It judges the change with task length. A session where every recorded turn is equally poor
    is stable, and other graders judge its quality. State Tracking judges one action that
    tracks state.

    A session with fewer than ``min_turns`` recorded turns is errored without a judge call.
    """

    args_model = LongTaskPerformanceStabilityArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.LONG_TASK_PERFORMANCE_STABILITY,
        scopes=(Scope.SESSION,),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        return (
            "You are assessing whether an agent keeps its performance as a long task "
            "continues. Compare the later turns of the session with the earlier turns."
            + self.args.task_block()
            + "\n\nIn each turn, look at these points:\n"
            "- Correct progress: the reply does what the user asked in that turn, and it "
            "uses the correct results of earlier steps.\n"
            "- Instructions in force: the reply follows every earlier instruction that the "
            "user did not withdraw, such as a format, a limit, or a preference.\n"
            "- Consistency: the reply does not contradict an earlier decision or fact, and "
            "it does not redo or undo completed work without a reason.\n\n"
            "Score 1 when the later turns are as good as the earlier turns on these points. "
            "Score 0 when the later turns show failures that the earlier turns do not, such "
            "as an instruction that the agent followed early and then dropped, a loss of "
            "track of the task, or more errors as the session gets longer. In your reason, "
            "name the turns that show the change."
            "\n\n<assessment_boundaries>\n"
            "Judge the change in performance over the session. A session with the same "
            "quality in every turn is stable, even when that quality is poor. Do not score "
            "a failure that is already present in the first turns as a drop."
            "\n</assessment_boundaries>"
        )

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        scope = SCOPE_DEFINITIONS[self.scope]
        selected = scope.select(input, self.args)
        if isinstance(selected, Problem):
            return GradingOutput.errored(selected.detail)
        count = len(turns(input.traces))
        if count < self.args.min_turns:
            return GradingOutput.errored(
                f"The session has {count} recorded turn(s). A drop in performance needs "
                f"at least {self.args.min_turns}."
            )
        return GradingOutput(
            results=[
                await judge(self, llm, label, scope.render(piece), self.criteria())
                for label, piece in selected.items()
            ]
        )
