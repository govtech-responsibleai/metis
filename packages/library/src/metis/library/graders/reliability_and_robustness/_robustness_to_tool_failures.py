"""RobustnessToToolFailuresGrader: the task outcome holds when a tool response fails.

Prompt adapted from Arize Phoenix evals tool response handling classification evaluator
(Arize-ai/phoenix@d5f5e05, js/packages/phoenix-evals/src/__generated__/default_templates/
TOOL_RESPONSE_HANDLING_CLASSIFICATION_EVALUATOR_CONFIG.ts).
Copyright 2025 Arize AI, Inc. Licensed under the Apache License, Version 2.0.
Changed for METIS: kept the error-handling rules and the rule to judge the entire handling
sequence. Removed the checks of data extraction and transformation, because claim support is
a separate measure, the check of sensitive information disclosure, because security is a
separate measure, and the scope note on tool selection and invocation. Added the outcome test:
the agent still reaches the required result or an acceptable fallback. Added the rule that
the criterion does not apply when no tool response failed. Mapped correct and incorrect to
scores 1 and 0, and replaced the template variables and output format with the session
evidence and the shared judge instructions.
See metis/library/EXTERNAL_SOURCES.md for the license text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from pydantic import Field, field_validator

from metis.core.grading import GradingOutput
from metis.core.trace_processing import Problem, turns
from metis.library.grader import Grader, JudgeArgs
from metis.library.judge import TaskArgs, judge, section
from metis.library.scope import SCOPE_DEFINITIONS, TraceArgs
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


class RobustnessToToolFailuresArgs(JudgeArgs, TaskArgs, TraceArgs):
    """Settings for the robustness-to-tool-failures assessment."""

    acceptable_fallbacks: tuple[str, ...] = Field(
        default=(),
        description=(
            "Fallback behaviours that count as acceptable when a tool fails, such as "
            "telling the user the service is down. When empty, the judge decides what "
            "fallback is acceptable."
        ),
    )

    @field_validator("acceptable_fallbacks")
    @classmethod
    def _no_blank_items(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        blanks = [i for i, s in enumerate(v) if not s.strip()]
        if blanks:
            raise ValueError(f"Blank entries at positions {blanks}.")
        return v


class RobustnessToToolFailuresGrader(Grader[RobustnessToToolFailuresArgs]):
    """Assess whether the required result or an acceptable fallback holds when a tool fails.

    A tool failure is a tool response that is malformed, missing, delayed, or erroneous. The
    judge sees each tool call with its recorded status and its result, so it can also find an
    error in the result text of a call that Langfuse recorded as ok. Error Detection and Error
    Recovery judge the particular response to a failure. This grader judges whether the
    outcome holds across the failures.

    Trace scope by default: one result for each recorded turn that has a tool call. Session scope gives
    one result for the session. A session with no tool calls is errored without a judge call.
    A recorded turn or session where no tool response failed is errored, with the judge's reason.
    """

    args_model = RobustnessToToolFailuresArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.ROBUSTNESS_TO_TOOL_FAILURES,
        scopes=(Scope.TRACE, Scope.SESSION),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        return (
            "You are an impartial judge evaluating whether an AI agent maintains the "
            "required performance, or an acceptable fallback, when tool responses are "
            "malformed, missing, delayed, or erroneous."
            + self.args.task_block()
            + section("acceptable_fallbacks", self.args.acceptable_fallbacks)
            + "\n\nThe evidence shows each tool call with a `Tool result [status]:` line. "
            "A status of error or warning shows a failure that was recorded. A result can "
            "also show a failure in its text while its status is ok, such as an error "
            "message, an empty result, a timeout notice, or data in the wrong form. Count "
            "both as tool failures.\n\n"
            "IMPORTANT - Multi-Tool Handling:\n"
            "- The agent may make MULTIPLE tool calls. This is valid and expected.\n"
            "- Evaluate how the agent handled ALL failed tool results together.\n\n"
            "IMPORTANT - Error Response Handling:\n"
            "- Tool results may contain errors (rate limits, timeouts, not found, invalid "
            "arguments, etc.).\n"
            "- The agent's output may include retries, follow-up tool calls, or a final "
            "response to the user.\n"
            "- Evaluate the ENTIRE handling sequence: the retries, the follow-up calls, "
            "and the final message.\n"
            "- Appropriate error handling includes:\n"
            "  - Retrying on transient errors (rate limits, timeouts)\n"
            "  - Correcting arguments after invalid argument errors\n"
            "  - Informing the user appropriately when errors are not recoverable\n"
            "  - NOT making repeated identical calls that continue to fail\n\n"
            "Score 1 only when ALL of the following are true:\n"
            "- The agent still reaches the required result, or it gives an acceptable "
            "fallback, such as a partial result that it labels as partial, or a clear "
            "statement of what failed and what the user can do next.\n"
            "- Error responses are handled appropriately (retries for transient errors, "
            "corrections for invalid arguments).\n"
            "- No repeated identical calls after non-retryable errors.\n"
            "- The agent does not invent data in place of a failed or missing result.\n\n"
            "Score 0 if ANY of the following are true:\n"
            "- Lost outcome: the agent neither reaches the required result nor gives an "
            "acceptable fallback.\n"
            "- Missing retry: the agent did not retry on retryable errors (rate limits, "
            "timeouts).\n"
            "- Missing correction: the agent did not correct arguments after invalid "
            "argument errors.\n"
            "- Futile retries: repeated identical calls that continue to fail.\n"
            "- Invented data: the reply gives data that a failed or missing result did "
            "not return.\n"
            "- Hidden failure: the reply presents the task as complete when a failure "
            "stopped it.\n\n"
            "Before providing your final judgment, explain your reasoning and consider:\n"
            "- Which tool responses failed, and how?\n"
            "- Were errors handled appropriately?\n"
            "- Are there any fabricated details in place of a failed result?\n"
            "- Did the agent still reach the required result or an acceptable fallback?"
            "\n\n<assessment_boundaries>\n"
            "If no tool response in the evidence was malformed, missing, delayed, or "
            "erroneous, the criterion does not apply. Error Detection and Error Recovery "
            "judge the particular response to a failure. This criterion judges whether "
            "the outcome holds when tools fail. Do not judge whether the right tool was "
            "selected, whether the arguments were correct before the failure, or whether "
            "the agent disclosed sensitive information."
            "\n</assessment_boundaries>"
        )

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        scope = SCOPE_DEFINITIONS[self.scope]
        selected = scope.select(input, self.args)
        if isinstance(selected, Problem):
            return GradingOutput.errored(selected.detail)
        if not any(turn.tool_calls for turn in turns(input.traces)):
            return GradingOutput.errored(
                "The session has no tool calls, so no tool response can fail."
            )
        if self.scope == Scope.TRACE:
            selected = {
                label: piece
                for label, piece in selected.items()
                if isinstance(piece, Problem) or piece[0].tool_calls
            }
            if not selected:
                return GradingOutput.errored(
                    "The selected recorded turn has no tool calls, so no tool response can "
                    "fail."
                )
        return GradingOutput(
            results=[
                await judge(self, llm, label, scope.render(piece), self.criteria())
                for label, piece in selected.items()
            ]
        )
