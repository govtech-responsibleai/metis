"""Opt-in live checks of the decision grader against direct provider endpoints."""

import os

import pytest
from openai import AsyncOpenAI
from tests.fixtures.criterion_judge import recorded_session

from metis.core.console import console
from metis.core.model_settings import load_env
from metis.library.grader import LLMSettings
from metis.library.graders import CriterionDecisionGrader
from metis.library.graders._criterion_decision import CriterionDecisionArgs

pytestmark = pytest.mark.skipif(
    os.environ.get("METIS_RUN_DECISION_SMOKE") != "1",
    reason="Set METIS_RUN_DECISION_SMOKE=1 to call the live decision APIs.",
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "key_var", "base_url", "model"),
    [
        ("typesafe", "TYPESAFE_API_KEY", "https://api.typesafe.ai/v1", "jev-latest"),
        ("openai", "OPENAI_API_KEY", "https://api.openai.com/v1", "gpt-6-luna"),
    ],
)
async def test_live_decision_grader(provider, key_var, base_url, model):
    load_env()
    key = os.environ.get(key_var)
    assert key, f"Set {key_var} in the worktree's .env file."
    async with AsyncOpenAI(api_key=key, base_url=base_url, timeout=60) as client:
        scores = []
        for text in ("example.org", "banana"):
            grader = CriterionDecisionGrader(
                CriterionDecisionArgs(
                    provider=provider,
                    model=model,
                    criterion=f"The assistant's final response contains the exact text '{text}'.",
                )
            )
            [result] = (
                await grader.grade(recorded_session(), LLMSettings(client))
            ).results
            assert result.status == "scored", result.reason
            assert result.score is not None
            scores.append(result.score)
            console.print(
                f"{provider} ({model}), {text}: {result.score:.6f}", markup=False
            )
        assert scores[0] > scores[1], (
            "The cited source must score above an absent word."
        )
