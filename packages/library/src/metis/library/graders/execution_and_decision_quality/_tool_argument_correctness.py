"""ToolArgumentCorrectnessGrader: whether submitted tool parameters are valid and aligned.

Prompt adapted from Arize Phoenix evals tool invocation classification evaluator
(Arize-ai/phoenix@d5f5e05, js/packages/phoenix-evals/src/__generated__/default_templates/
TOOL_INVOCATION_CLASSIFICATION_EVALUATOR_CONFIG.ts).
Copyright 2025 Arize AI, Inc. Licensed under the Apache License, Version 2.0.
Changed for METIS: removed the unsafe-content items, because safety is a separate measure,
mapped correct and incorrect to scores 1 and 0, and replaced the tool schema, the template
variables and the output format with the available_tools list and the shared judge instructions.
See metis/library/EXTERNAL_SOURCES.md for the license text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from pydantic import Field, field_validator

from metis.core.grading import GradingOutput
from metis.core.trace_processing import Problem, turns
from metis.library.grader import Grader, JudgeArgs
from metis.library.judge import (
    TaskArgs,
    ToolListArgs,
    available_tools_block,
    judge,
    section,
)
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


class ToolArgumentCorrectnessArgs(JudgeArgs, TaskArgs, ToolListArgs):
    """Settings for the tool-argument correctness assessment.

    ``task_description`` provides the goal context. ``argument_requirements``
    optionally specifies syntactic or semantic requirements for tool parameters.
    """

    argument_requirements: tuple[str, ...] = Field(
        default=(),
        description=(
            "Specific syntactic or semantic requirements for tool parameters. "
            "When empty, the judge assesses general argument correctness."
        ),
    )

    @field_validator("argument_requirements")
    @classmethod
    def _no_blank_items(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        blanks = [i for i, s in enumerate(v) if not s.strip()]
        if blanks:
            raise ValueError(f"Blank entries at positions {blanks}.")
        return v


class ToolArgumentCorrectnessGrader(Grader[ToolArgumentCorrectnessArgs]):
    """Assess whether submitted tool parameters are valid and semantically aligned.

    Evaluates syntactic validity and semantic appropriateness of tool arguments.
    Tool selection is assessed separately. A session with no recorded tool calls is
    errored. The judge checks the arguments against the tool list (the ``available_tools``
    setting, or the tools the session offered).
    """

    args_model = ToolArgumentCorrectnessArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.TOOL_ARGUMENT_CORRECTNESS,
        scopes=(Scope.SESSION,),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self, tools: tuple[str, ...]) -> str:
        return (
            "You are an impartial judge evaluating an agent's tool-calling behavior, "
            "specifically whether the agent invoked a tool (or tools) correctly with "
            "valid arguments and proper formatting."
            + self.args.task_block()
            + section("argument_requirements", self.args.argument_requirements)
            + available_tools_block(
                tools,
                "Check each submitted argument against the tool's description in "
                "available_tools: the tool name, the parameter names, and the types "
                "where the description gives them.",
            )
            + (
                ""
                if tools
                else " The rules below that mention available_tools then apply only "
                "where the evidence itself shows a tool's parameters."
            )
            + "\n\nYour task: Determine whether the agent's tool invocation(s) were "
            "correct or incorrect based on:\n"
            "- The full conversation context (including all previous turns, not just "
            "the most recent message)\n"
            "- The tool descriptions in available_tools\n"
            "- The agent's tool invocation(s) with arguments\n\n"
            "IMPORTANT - Tool Invocation vs. Tool Selection:\n"
            "- You are ONLY evaluating the tool invocation, not the tool selection.\n"
            "- If the tool selection is incorrect or not relevant to the user's query, "
            "but the tool invocation is correct, score 1.\n"
            "- If the tool selection is correct but the tool invocation is incorrect, "
            "score 0.\n\n"
            "IMPORTANT - Multi-Tool Invocations:\n"
            "- The agent may invoke MULTIPLE tools in a single response. This is valid "
            "and expected for complex requests.\n"
            "- When multiple tools are invoked, evaluate EACH tool invocation "
            "independently.\n"
            "- Score 1 only if ALL tool invocations are correct.\n"
            "- Score 0 if ANY tool invocation has an error.\n\n"
            "IMPORTANT - Conversation Context:\n"
            "- Read the entire conversation history carefully, not just the final user "
            "message.\n"
            "- Argument values may need to be extracted from EARLIER turns in the "
            "conversation (e.g., user mentions a location, date, or quantity in a "
            "previous message).\n"
            "- The agent should use context from the full conversation to populate "
            "argument values correctly.\n\n"
            "Score 1 (correct) only when ALL of the following are true for EVERY tool "
            "invocation:\n"
            "- JSON is properly structured (if applicable).\n"
            "- All required fields/parameters are present.\n"
            "- No hallucinated or nonexistent fields (all fields exist in the tool "
            "descriptions in available_tools).\n"
            "- Argument values match the user's intent from the conversation context "
            "(correct types, realistic values).\n\n"
            "Score 0 (incorrect) if ANY of the following are true for ANY tool "
            "invocation:\n"
            "- The invocation contains hallucinated or nonexistent fields not in the "
            "tool descriptions in available_tools.\n"
            "- Required fields/parameters are missing.\n"
            "- JSON is improperly formatted or malformed.\n"
            "- Argument values are incorrect, hallucinated, or do not match user intent "
            "from the conversation.\n\n"
            "Before providing your final judgment, explain your reasoning and consider:\n"
            "- How many tools were invoked? Evaluate each one.\n"
            "- Does each tool invocation match the tool descriptions in available_tools "
            "for that tool?\n"
            "- Are all required parameters provided with appropriate values for each "
            "invocation?\n"
            "- Are there any extra fields that don't exist in the tool descriptions in "
            "available_tools?\n"
            "- Looking at the FULL conversation: do the argument values accurately "
            "reflect what the user requested across all messages?\n"
            "- Check that you are not evaluating the tool selection, only the tool "
            "invocation."
            "\n\n<assessment_boundaries>\n"
            "Assess syntactic validity and semantic appropriateness of submitted "
            "parameters. Tool selection is a separate criterion."
            "\n</assessment_boundaries>"
        )

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        scope = SCOPE_DEFINITIONS[self.scope]
        selected = scope.select(input, self.args)
        if isinstance(selected, Problem):
            return GradingOutput.errored(selected.detail)
        if not any(turn.tool_calls for turn in turns(input.traces)):
            return GradingOutput.errored(
                "The session has no recorded tool calls, so tool argument correctness "
                "cannot be assessed."
            )
        return GradingOutput(
            results=[
                await judge(
                    self,
                    llm,
                    label,
                    scope.render(thing),
                    self.criteria(self.args.tool_list(input.traces)),
                )
                for label, thing in selected.items()
            ]
        )
