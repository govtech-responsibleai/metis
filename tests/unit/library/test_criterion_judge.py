"""The criterion judge grades recorded evidence and reports model failures."""

import asyncio
import json

import pytest
from pydantic import ValidationError

from metis.core.artifacts import Artifact
from metis.core.traces import GradingInput
from metis.library.grader import CriterionJudgeArgs, LLMSettings
from metis.library.graders import CriterionJudgeGrader
from metis.library.judgment_form import JUDGMENT_FORM_DEFINITIONS, BinaryJudgment
from metis.library.taxonomy import (
    Aggregation,
    GraderType,
    JudgmentForm,
    ReferenceType,
    Scope,
)
from tests.fixtures.criterion_judge import judge_client, recorded_session


def test_uses_the_shared_binary_judgment_definition() -> None:
    assert CriterionJudgeGrader.taxonomy.model_dump() == {
        "measure": None,
        "scopes": (Scope.SESSION,),
        "grader_types": (GraderType.LLM,),
        "reference_types": (ReferenceType.RUBRIC_BASED,),
        "judgment_forms": (JudgmentForm.BINARY,),
        "aggregations": (Aggregation.NONE_SINGLE_SCORE,),
    }
    (judgment_form,) = CriterionJudgeGrader.taxonomy.judgment_forms
    definition = JUDGMENT_FORM_DEFINITIONS[judgment_form]
    assert definition.response_model is BinaryJudgment
    assert "score 1" in definition.output_instructions


@pytest.mark.parametrize(
    ("reply", "status", "score"),
    [
        (
            {"status": "scored", "score": 1, "reason": "The source is named."},
            "scored",
            1,
        ),
        (
            {
                "status": "scored",
                "score": 0,
                "reason": "The required citation is absent.",
            },
            "scored",
            0,
        ),
        (
            {
                "status": "not_applicable",
                "score": None,
                "reason": "The condition did not occur.",
            },
            "errored",
            None,
        ),
        ({"status": "scored", "score": 0.5, "reason": "Partial."}, "errored", None),
        ({"status": "scored", "score": True, "reason": "Yes."}, "errored", None),
        ({"status": "scored", "score": "1", "reason": "Yes."}, "errored", None),
        ({"status": "not_applicable", "score": 1, "reason": "No."}, "errored", None),
        ({"status": "scored", "score": 1, "reason": " "}, "errored", None),
        ("not json", "errored", None),
        ("", "errored", None),
    ],
)
def test_response_contract_and_recorded_evidence(reply, status, score) -> None:
    requests = []
    client = judge_client(
        reply if isinstance(reply, str) else json.dumps(reply), requests
    )
    grader = CriterionJudgeGrader(
        CriterionJudgeArgs(model="test-judge", criterion="Name a source.")
    )

    async def run():
        async with client:
            return await grader.grade(recorded_session(), LLMSettings(client))

    [result] = asyncio.run(run()).results
    assert (result.status, result.score) == (status, score)
    assert result.reason.strip()
    [request] = requests
    assert request["model"] == "test-judge"
    assert "Name a source." in request["input"][0]["content"]
    [evidence] = request["input"][1]["content"]
    assert evidence["text"] == (
        "## Turn 1\nUser: Find a source\nTool search: [unreadable: missing: the tool call has no arguments]\n"
        'Tool result [ok]: {"url": "example.org"}\nAssistant: The source is example.org'
    )
    assert result.scope == "session"


def test_provider_failure_is_an_error() -> None:
    requests = []
    client = judge_client("unavailable", requests, status_code=503)
    grader = CriterionJudgeGrader(
        CriterionJudgeArgs(model="test-judge", criterion="Name a source.")
    )

    async def run():
        async with client:
            return await grader.grade(recorded_session(), LLMSettings(client))

    [result] = asyncio.run(run()).results
    assert result.status == "errored"
    assert result.score is None
    assert len(requests) == 1


@pytest.mark.parametrize(
    "artifacts",
    [
        (),
        (
            Artifact(
                name="answer.txt",
                source="target",
                state="received",
                path="/unread/answer.txt",
            ),
        ),
    ],
)
def test_empty_session_is_errored_without_a_model_call(artifacts) -> None:
    requests = []
    client = judge_client("unused", requests)
    grader = CriterionJudgeGrader(
        CriterionJudgeArgs(model="test-judge", criterion="Name a source.")
    )

    async def run():
        async with client:
            return await grader.grade(
                GradingInput(traces=(), artifacts=artifacts), LLMSettings(client)
            )

    [result] = asyncio.run(run()).results
    assert (result.status, result.reason) == ("errored", "The session has no turns.")
    assert requests == []


def test_runtime_instructions_must_be_nonempty() -> None:
    with pytest.raises(ValidationError, match="criterion"):
        CriterionJudgeArgs(model="test-judge", criterion=" ")


@pytest.mark.parametrize(
    ("max_input_tokens", "status"), [(100_000, "scored"), (5_000, "errored")]
)
def test_a_request_above_the_input_limit_errors_without_a_model_call(
    max_input_tokens, status
) -> None:
    requests = []
    client = judge_client('{"status":"scored","score":1,"reason":"Yes."}', requests)
    grader = CriterionJudgeGrader(
        CriterionJudgeArgs(
            model="test-judge",
            criterion="Name a source.",
            max_input_tokens=max_input_tokens,
        )
    )

    async def run():
        async with client:
            return await grader.grade(recorded_session(), LLMSettings(client))

    [result] = asyncio.run(run()).results
    assert result.status == status
    if status == "errored":
        assert requests == []
        assert "the limit is 5,000" in result.reason
    else:
        assert len(requests) == 1
