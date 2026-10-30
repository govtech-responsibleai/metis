"""OutputNaturalnessGrader: the assistant's replies read as fluent, idiomatic text."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from pydantic import Field

from metis.core.grading import GradingOutput
from metis.core.trace_processing import Problem, render_dialogue
from metis.library.grader import Grader, JudgeArgs
from metis.library.judge import judge
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
from metis.library.text import NonEmptyText  # noqa: TC001 — a Pydantic field type

if TYPE_CHECKING:
    from metis.core.traces import GradingInput
    from metis.library.grader import LLMSettings

_CRITERIA = (
    "You are grading output naturalness: whether the assistant's replies read as fluent, "
    "conventional writing in their language, as a fluent reader would write it. Check "
    "spelling and grammar; natural word choice and idiom; sentences that flow into each "
    "other; and the absence of stiff, robotic, garbled, or machine-translated phrasing, "
    "stray markup, or text that switches language without reason. Score 1 when the replies "
    "read naturally. Score 0 when a reply has errors or phrasing awkward enough that a "
    "fluent reader would notice. Naturalness does not require sounding human. Do not judge "
    "tone, organization, correctness, or task success."
)


class OutputNaturalnessArgs(JudgeArgs, SubsessionArgs):
    conventions: NonEmptyText | None = Field(
        default=None,
        description=(
            "The norms that a fluent reader or listener of the output expects, such as "
            '"Singapore English" or "British spelling".'
        ),
    )


class OutputNaturalnessGrader(Grader[OutputNaturalnessArgs]):
    """Whether the assistant's replies read as fluent, idiomatic text in their language.

    At session scope, by default, one verdict on all replies. At subsession scope, one verdict
    for each reply. Text only. The judge reads the replies alone, because fluency is a
    property of the assistant's own writing; the user's messages would only add text to
    ignore. The criteria draw on MLflow Fluency. DeepEval Voice Naturalness is the reference
    for a later voice mode.
    """

    args_model = OutputNaturalnessArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.OUTPUT_NATURALNESS,
        scopes=(Scope.SESSION, Scope.SUBSESSION),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        if self.args.conventions is None:
            return _CRITERIA
        return (
            f"{_CRITERIA} Judge against these conventions: {self.args.conventions} A form "
            "that these conventions allow is not an error, even when another variety would "
            "use a different form."
        )

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        selected = SCOPE_DEFINITIONS[self.scope].select(input, self.args)
        if isinstance(selected, Problem):
            return GradingOutput.errored(selected.detail)
        return GradingOutput(
            results=[
                await judge(
                    self,
                    llm,
                    label,
                    render_dialogue(turns, assistant_only=True),
                    self.criteria(),
                )
                for label, turns in selected.items()
            ]
        )
