"""Decision graders use typed provider replies and the shared session view."""

import asyncio
import json

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import ValidationError

from metis.core.traces import GradingInput
from metis.library.grader import LLMSettings, criterion_judge_args
from metis.library.graders import CriterionDecisionGrader
from metis.library.graders._criterion_decision import CriterionDecisionArgs
from metis.library.judgment_form import JUDGMENT_FORM_DEFINITIONS
from metis.library.taxonomy import GraderType, JudgmentForm
from tests.fixtures.criterion_judge import recorded_session


def response_body(provider, applicable=0.99, satisfied=0.87):
    if provider == "typesafe":
        return {
            "model": "jev-latest",
            "answers": {
                "applicable": {"type": "noul", "noul": applicable},
                "satisfied": {"type": "noul", "noul": satisfied},
            },
            "usage": {"input_tokens": 100, "output_tokens": 0},
        }
    return {
        "model": "gpt-6-luna",
        "answers": [
            {"type": "predicate", "name": "applicable", "probability": applicable},
            {"type": "predicate", "name": "satisfied", "probability": satisfied},
        ],
        "usage": {"input_tokens": 100, "output_tokens": 0},
    }


def grade(provider, body, *, input=None, status_code=200, max_input_tokens=128_000):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            status_code,
            content=body if isinstance(body, str) else json.dumps(body),
            headers={"content-type": "application/json"},
        )

    async def run():
        async with AsyncOpenAI(
            api_key="test-only",
            base_url="https://judge.invalid/v1",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        ) as client:
            grader = CriterionDecisionGrader(
                CriterionDecisionArgs(
                    provider=provider,
                    model="test-decision-model",
                    criterion="Name a source.",
                    max_input_tokens=max_input_tokens,
                )
            )
            output = await grader.grade(
                input if input is not None else recorded_session(), LLMSettings(client)
            )
            return output.results

    [result] = asyncio.run(run())
    return result, requests


@pytest.mark.parametrize("provider", ["openai", "typesafe"])
def test_satisfaction_probability_is_the_score(provider):
    result, [request] = grade(provider, response_body(provider))
    assert (result.status, result.score, result.scope) == ("scored", 0.87, "session")
    assert result.measurements == {"applicable": 0.99, "satisfied": 0.87}
    assert "probabilities only" in result.reason
    body = json.loads(request.content)
    assert body["model"] == "test-decision-model"
    assert request.headers["authorization"] == "Bearer test-only"
    if provider == "typesafe":
        assert request.url.path == "/v1/systemone"
        evidence = body["state"]
        questions = body["questions"]
        assert {q["type"] for q in questions.values()} == {"noul"}
    else:
        assert request.url.path == "/v1/decisions"
        evidence = body["input"]
        questions = {q["name"]: q for q in body["questions"]}
        assert {q["type"] for q in questions.values()} == {"predicate"}
    assert evidence.startswith("## Turn 1\nUser: Find a source")
    assert "Tool result [ok]" in evidence
    assert "Assistant: The source is example.org" in evidence
    assert set(questions) == {"applicable", "satisfied"}
    assert all("Name a source." in q["instructions"] for q in questions.values())
    assert all("untrusted evidence" in q["instructions"] for q in questions.values())


@pytest.mark.parametrize("provider", ["openai", "typesafe"])
@pytest.mark.parametrize("satisfied", [0.0, 0.2, 0.5, 1.0])
def test_applicable_criteria_keep_the_probability_without_a_pass_fail_mapping(
    provider, satisfied
):
    result, _ = grade(provider, response_body(provider, satisfied=satisfied))
    assert (result.status, result.score) == ("scored", satisfied)


@pytest.mark.parametrize("provider", ["openai", "typesafe"])
def test_inapplicable_criterion_is_an_error(provider):
    result, _ = grade(provider, response_body(provider, applicable=0.1))
    assert (result.status, result.score) == ("errored", None)
    assert "does not apply" in result.reason
    assert result.measurements == {"applicable": 0.1, "satisfied": 0.87}


@pytest.mark.parametrize("provider", ["openai", "typesafe"])
@pytest.mark.parametrize(
    "probability", [None, True, "0.8", -0.1, 1.1, float("nan"), float("inf")]
)
def test_invalid_probability_is_an_error(provider, probability):
    body = response_body(provider, satisfied=probability)
    result, _ = grade(provider, body)
    assert (result.status, result.score) == ("errored", None)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"answers": []},
        {"answers": [{"type": "refusal", "name": "applicable"}]},
        {
            "answers": [
                {"type": "predicate", "name": "applicable", "probability": 1},
                {"type": "predicate", "name": "applicable", "probability": 1},
            ]
        },
    ],
)
def test_missing_refused_or_duplicate_answers_are_errors(body):
    result, _ = grade("openai", body)
    assert (result.status, result.score) == ("errored", None)


@pytest.mark.parametrize("provider", ["openai", "typesafe"])
@pytest.mark.parametrize(
    "body", [{}, "not json", {"answers": {"satisfied": {"type": "noul", "noul": 0.9}}}]
)
def test_incomplete_or_unreadable_response_is_an_error(provider, body):
    result, _ = grade(provider, body)
    assert (result.status, result.score) == ("errored", None)


@pytest.mark.parametrize("provider", ["openai", "typesafe"])
def test_provider_errors_do_not_disclose_the_response_body(provider):
    result, requests = grade(
        provider, {"error": "private-session-or-key"}, status_code=503
    )
    assert (result.status, result.score) == ("errored", None)
    assert "private-session-or-key" not in result.reason
    assert len(requests) == 1


@pytest.mark.parametrize("provider", ["openai", "typesafe"])
def test_empty_session_errors_before_the_request(provider):
    result, requests = grade(provider, {}, input=GradingInput(traces=(), artifacts=()))
    assert (result.status, result.score) == ("errored", None)
    assert requests == []


@pytest.mark.parametrize("provider", ["openai", "typesafe"])
def test_input_budget_errors_before_the_request(provider):
    result, requests = grade(provider, {}, max_input_tokens=10)
    assert (result.status, result.score, result.scope) == ("errored", None, "session")
    assert "the limit is 10" in result.reason
    assert requests == []


def test_description_drives_the_decision_grader_and_its_taxonomy():
    settings = criterion_judge_args(
        CriterionDecisionArgs,
        {"model": "jev-latest", "provider": "typesafe"},
        "Name a source.",
    )
    grader = CriterionDecisionGrader(CriterionDecisionArgs.model_validate(settings))
    assert grader.args.criterion == "Name a source."
    assert grader.taxonomy.grader_types == (GraderType.DECISION_MODEL,)
    assert grader.judgment_form == JudgmentForm.SCALAR
    with pytest.raises(ValidationError):
        CriterionDecisionArgs.model_validate({**settings, "provider": "unknown"})


@pytest.mark.parametrize(
    ("status", "score", "valid"),
    [
        ("scored", 0.0, True),
        ("scored", 0.87, True),
        ("scored", 1.0, True),
        ("not_applicable", None, True),
        ("scored", None, False),
        ("scored", True, False),
        ("scored", "0.87", False),
        ("scored", -0.1, False),
        ("scored", 1.1, False),
        ("scored", float("nan"), False),
        ("not_applicable", 0.5, False),
    ],
)
def test_scalar_form_requires_a_bounded_score_only_for_scored_results(
    status, score, valid
):
    model = JUDGMENT_FORM_DEFINITIONS[JudgmentForm.SCALAR].response_model
    data = {"status": status, "score": score, "reason": "Assessment."}
    if valid:
        assert model.model_validate(data).model_dump() == data
    else:
        with pytest.raises(ValidationError):
            model.model_validate(data)
