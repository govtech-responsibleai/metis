"""Graders that engine tests name by FQN in their specification.yaml strings.

They live in an importable test module, not in metis-library, so engine tests resolve FQNs
through the same ``importlib`` path a real spec takes without depending on the catalogue.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field

from metis.core.grading import GraderResult, GradingOutput
from metis.library.grader import Grader, GraderArgs, JudgeArgs

if TYPE_CHECKING:
    from metis.core.specification import Specification
    from metis.core.traces import GradingInput
    from metis.library.grader import LLMSettings

FQN = "tests.unit.engine.graders_for_tests"


class ScoreArgs(GraderArgs):
    score: float = Field(default=1.0, ge=0, le=1)


class FixedScoreGrader(Grader[ScoreArgs]):
    """Scores every session with the score its args name."""

    args_model = ScoreArgs

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        return GradingOutput(
            results=[
                GraderResult(
                    status="scored",
                    score=self.args.score,
                    reason=f"{len(input.traces)} trace(s)",
                )
            ]
        )


class FixtureArgs(GraderArgs):
    fixture: str


class FixtureGrader(Grader[FixtureArgs]):
    """Needs a fixture the experiment declares: exercises check_setup."""

    args_model = FixtureArgs

    @classmethod
    def check_setup(cls, args: FixtureArgs, spec: Specification) -> list[str]:
        declared = {f for task in spec.tasks for f in task.fixtures}
        if args.fixture not in declared:
            return [f"fixture '{args.fixture}' is not used by any task"]
        return []

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        return GradingOutput(results=[GraderResult(status="skipped", reason="n/a")])


class EchoJudgeArgs(JudgeArgs):
    pass


class EchoJudgeGrader(Grader[EchoJudgeArgs]):
    """Model-based: needs the judge gateway, and records its resolved model."""

    args_model = EchoJudgeArgs

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        return GradingOutput(
            results=[GraderResult(status="scored", score=0.5, reason=self.args.model)]
        )


class NotAGrader:
    pass


class BrokenSetupGrader(Grader[ScoreArgs]):
    args_model = ScoreArgs

    @classmethod
    def check_setup(cls, args: ScoreArgs, spec: Specification) -> list[str]:
        raise KeyError("fixtures")

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        raise NotImplementedError
