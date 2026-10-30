"""DemoRequiredToolGrader: the target called a given tool somewhere in the session."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from pydantic import Field

from metis.core.grading import GraderResult, GradingOutput
from metis.core.trace_processing import Problem, turns
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


class DemoRequiredToolArgs(GraderArgs):
    tool_name: str = Field(min_length=1)
    """The name of the tool call the session must contain, exactly as traced."""


class DemoRequiredToolGrader(Grader[DemoRequiredToolArgs]):
    """Demo: the target made a ``tool_name`` call at least once.

    Shows a code-based grader: it declares a taxonomy and selects the session like a model-based one,
    then checks the tool calls itself with no judge call. Every ``TOOL`` observation counts, at
    any depth, so a call a sub-agent made several levels down still counts. Scores 1.0 if found,
    else 0.0. Errors on a session with no recorded turns.
    """

    args_model = DemoRequiredToolArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.TOOL_CHOICE_APPROPRIATENESS,
        scopes=(Scope.SESSION,),
        grader_types=(GraderType.DETERMINISTIC,),
        reference_types=(ReferenceType.EXPECTED_TRAJECTORY_ACTION,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        selected = SCOPE_DEFINITIONS[self.scope].select(input, self.args)
        if isinstance(selected, Problem):
            return GradingOutput.errored(selected.detail)
        session = turns(input.traces)
        calls = tuple(call for turn in session for call in turn.tool_calls)
        name = self.args.tool_name
        matches = [call for call in calls if call.name == name]
        if not matches:
            result = GraderResult(
                status="scored",
                score=0.0,
                reason=f"No {name} call in {len(calls)} tool call(s) across {len(session)} recorded turn(s).",
                scope="session",
            )
        else:
            first = matches[0]
            by = f" by {first.agent}" if first.agent else ""
            result = GraderResult(
                status="scored",
                score=1.0,
                reason=f"{name} was called {len(matches)} time(s), first in recorded "
                f"turn {first.turn_index + 1}{by}.",
                scope="session",
            )
        return GradingOutput(results=[result])
