"""RobustnessToContextDegradationGrader: performance holds when the context is degraded."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from pydantic import Field, field_validator

from metis.core.grading import GradingOutput
from metis.core.trace_processing import Problem
from metis.library.grader import Grader, JudgeArgs
from metis.library.judge import TaskArgs, judge, section
from metis.library.scope import SCOPE_DEFINITIONS, SubsessionArgs
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


class RobustnessToContextDegradationArgs(JudgeArgs, TaskArgs, SubsessionArgs):
    """Settings for the robustness-to-context-degradation assessment."""

    degradation: tuple[str, ...] = Field(
        default=(),
        description=(
            "What makes the context harder in this session, and where the needed evidence "
            "is, such as 'Turn 3 adds a stale price; the current price is in turn 1.' A turn "
            "number is a recorded turn, as the `turn:N` labels count it. When empty, the "
            "judge looks for long, noisy, incomplete, or stale context itself."
        ),
    )

    @field_validator("degradation")
    @classmethod
    def _no_blank_items(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        blanks = [i for i, s in enumerate(v) if not s.strip()]
        if blanks:
            raise ValueError(f"Blank entries at positions {blanks}.")
        return v


class RobustnessToContextDegradationGrader(Grader[RobustnessToContextDegradationArgs]):
    """Assess whether performance holds when the context is long, noisy, incomplete, or stale.

    Subsession scope by default: one result for each recorded turn, judged with the recorded
    turns before it.
    Session scope gives one result for the session. When indispensable evidence is missing,
    the correct reply asks, says that it does not know, or abstains. Use of Prior Information
    judges recall in general. This grader judges whether performance holds when the context is
    degraded. A recorded turn or session whose context is not degraded in a way that bears on the
    reply is errored, with the judge's reason.
    """

    args_model = RobustnessToContextDegradationArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.ROBUSTNESS_TO_CONTEXT_DEGRADATION,
        scopes=(Scope.SUBSESSION, Scope.SESSION),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        return (
            "You are assessing whether an agent keeps its performance when the context it "
            "has is degraded. Degraded context is long, noisy, incomplete, or stale. "
            "Examples are irrelevant history, noise in messages or tool results, stale or "
            "conflicting information, and context that was shortened or summarised, such "
            "as by a context compaction step."
            + self.args.task_block()
            + section("degradation", self.args.degradation)
            + "\n\nScore 1 when the reply still uses the evidence that it needs, and is "
            "not misled by the degradation:\n"
            "- It finds and uses the needed facts and instructions among irrelevant "
            "history or noise.\n"
            "- It uses the current information when stale or conflicting information is "
            "also present.\n"
            "- It keeps the needed facts and instructions when earlier context was "
            "shortened or summarised.\n"
            "- When indispensable evidence is missing, it asks for the evidence, says that "
            "it does not know, or abstains. It does not guess.\n\n"
            "Score 0 when the reply uses stale or wrong information, loses a needed fact or "
            "instruction, or invents the missing evidence."
            "\n\n<assessment_boundaries>\n"
            "If the context in the evidence is not degraded in a way that bears on the "
            "judged reply, the criterion does not apply. Use of Prior Information judges "
            "recall in general. This criterion judges whether performance holds when the "
            "context is degraded."
            "\n</assessment_boundaries>"
        )

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        scope = SCOPE_DEFINITIONS[self.scope]
        selected = scope.select(input, self.args)
        if isinstance(selected, Problem):
            return GradingOutput.errored(selected.detail)
        return GradingOutput(
            results=[
                await judge(self, llm, label, scope.render(piece), self.criteria())
                for label, piece in selected.items()
            ]
        )
