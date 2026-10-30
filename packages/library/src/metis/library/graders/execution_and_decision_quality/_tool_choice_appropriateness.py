"""ToolChoiceAppropriatenessGrader: whether the selected tool is suitable.

Prompt adapted from Arize Phoenix evals tool selection classification evaluator
(Arize-ai/phoenix@d5f5e05, js/packages/phoenix-evals/src/__generated__/default_templates/
TOOL_SELECTION_CLASSIFICATION_EVALUATOR_CONFIG.ts).
Copyright 2025 Arize AI, Inc. Licensed under the Apache License, Version 2.0.
Changed for METIS: removed the safety and permission items, because safety is a separate
measure, mapped correct and incorrect to scores 1 and 0, and replaced the template variables
and output format with the session evidence and the shared judge instructions.
See metis/library/EXTERNAL_SOURCES.md for the license text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from metis.core.grading import GradingOutput
from metis.core.trace_processing import Problem
from metis.library.grader import Grader, JudgeArgs
from metis.library.judge import TaskArgs, ToolListArgs, judge, section
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


class ToolChoiceAppropriatenessArgs(JudgeArgs, TaskArgs, ToolListArgs):
    """Settings for the tool-choice appropriateness assessment.

    ``task_description`` provides the goal context. The tool list lets the judge assess
    whether an available alternative better fits the task and whether unused tools should
    have been used.
    """


class ToolChoiceAppropriatenessGrader(Grader[ToolChoiceAppropriatenessArgs]):
    """Assess whether the selected tool is suitable for the task.

    Evaluates tool suitability, including whether a tool is needed at all and
    whether an available alternative better fits the task. A session with no recorded
    tool calls is judged too: it fails when the task needed a tool, and passes when it
    did not. Tool arguments are assessed separately.

    Requires a tool list: the ``available_tools`` setting, or the tools the session
    offered. With neither, the result is errored without a judge call.
    """

    args_model = ToolChoiceAppropriatenessArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.TOOL_CHOICE_APPROPRIATENESS,
        scopes=(Scope.SESSION,),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self, tools: tuple[str, ...]) -> str:
        return (
            "You are an impartial judge evaluating an agent's tool-calling behavior, "
            "specifically whether the agent selected the most appropriate tool or tools "
            "for the task."
            + self.args.task_block()
            + section("available_tools", tools)
            + "\n\nYour task: Determine whether the agent's tool selection was correct or "
            "incorrect based on:\n"
            "- The conversation context in the session evidence\n"
            "- The available tools in the available_tools list above\n"
            "- The agent's output and tool invocation(s) in the session evidence\n\n"
            "Score 1 (correct) only when ALL of the following are true:\n"
            "- The agent chose the best available tool for the user query OR correctly "
            "avoided tools if none were needed.\n"
            "- The tool name exists in the available tools list.\n"
            "- The agent selected the correct number of tools for the task.\n\n"
            "Score 0 (incorrect) if ANY of the following are true:\n"
            "- The agent used a hallucinated or nonexistent tool.\n"
            "- The agent selected a tool when none was needed.\n"
            "- The agent did not use a tool when one was required.\n"
            "- The agent chose a suboptimal or irrelevant tool.\n"
            "- The tool name does not appear in the available tools list.\n\n"
            "Before providing your final judgment, explain your reasoning and consider:\n"
            "- What does the input context require?\n"
            "- Can this be answered without tools, or is a tool necessary?\n"
            "- If a tool was selected, does it exist in the available tools?\n"
            "- Does the selected tool's description match the user's needs?\n"
            "- Is there a better tool available that should have been chosen instead?"
            "\n\n<assessment_boundaries>\n"
            "The available_tools list above is the complete set the agent could "
            "choose from. Do not assume the trace shows every available tool — tools "
            "that were available but unused may still be the better choice. Arguments "
            "are assessed separately."
            "\n</assessment_boundaries>"
        )

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        tools = self.args.tool_list(input.traces)
        if not tools:
            return GradingOutput.errored(
                "No tool list: set available_tools, or record the tools the agent was "
                "offered."
            )
        scope = SCOPE_DEFINITIONS[self.scope]
        selected = scope.select(input, self.args)
        if isinstance(selected, Problem):
            return GradingOutput.errored(selected.detail)
        return GradingOutput(
            results=[
                await judge(
                    self,
                    llm,
                    label,
                    scope.render(thing),
                    self.criteria(tools),
                )
                for label, thing in selected.items()
            ]
        )
