"""The concrete Interview request and result shapes on the wire."""

import pytest
from pydantic import TypeAdapter, ValidationError

from metis.wizard.contracts import (
    ChatResponse,
    ChoiceRequest,
    ChoiceResponse,
    CompileResult,
    InterviewDocument,
    InterviewEndRequest,
    InterviewErrorCode,
    InterviewFailure,
    InterviewRequest,
    InterviewResult,
    InterviewStartRequest,
    InterviewState,
    InterviewSuccess,
    InterviewTurnRequest,
    Option,
    OptionId,
    Specification,
    Target,
)
from metis.wizard.domain.permissions import InterviewStep
from tests.fixtures.wizard.context import interview_context


def _state() -> InterviewState:
    return InterviewState(
        specification=Specification(
            target=Target(name="n", description="d", users="u")
        ),
        context=interview_context(),
        pending=ChoiceRequest(
            prompt="Continue?",
            options=[Option(id=OptionId(action="continue"), label="Continue")],
            request_id="req-1",
            stage=InterviewStep.BEHAVIOURS,
        ),
    )


def test_each_concrete_request_rebuilds_from_json() -> None:
    requests = [
        InterviewStartRequest(
            description="A policy assistant",
            known_capability_ids=[],
            capability_confidence="low",
            documents=[
                InterviewDocument(name="policy.md", text="Policy"),
                InterviewDocument(name="sample.csv"),
            ],
        ),
        InterviewTurnRequest(
            state=_state(), request_id="req-1", response=ChoiceResponse(selected=[])
        ),
        InterviewEndRequest(state=_state()),
    ]
    adapter = TypeAdapter(InterviewRequest)

    for request in requests:
        rebuilt = adapter.validate_json(adapter.dump_json(request))
        assert type(rebuilt) is type(request)
        assert rebuilt == request


def test_a_turn_keeps_its_typed_response_across_the_wire() -> None:
    request = InterviewTurnRequest(
        state=_state(), request_id="req-9", response=ChatResponse(text="hello")
    )

    rebuilt = InterviewTurnRequest.model_validate_json(request.model_dump_json())

    assert isinstance(rebuilt.response, ChatResponse)
    assert rebuilt.request_id == "req-9"


def test_start_requires_non_blank_description() -> None:
    with pytest.raises(ValidationError):
        InterviewStartRequest(
            description="  ", known_capability_ids=[], capability_confidence="low"
        )


@pytest.mark.parametrize("confidence", ["low", "medium", "high"])
def test_start_requires_explicit_capability_evidence(confidence: str) -> None:
    request = InterviewStartRequest(
        description="A policy assistant",
        known_capability_ids=[],
        capability_confidence=confidence,
    )

    assert request.documents == []
    assert request.known_capability_ids == []
    assert request.capability_confidence.value == confidence


@pytest.mark.parametrize(
    "documents",
    [
        [{"name": "../policy.pdf"}],
        [{"name": "Policy.pdf"}, {"name": "policy.PDF"}],
        [{"name": f"file-{i}.txt"} for i in range(21)],
        [{"name": "policy.txt", "text": "x" * 500_001}],
        [{"name": f"policy-{i}.txt", "text": "x" * 400_000} for i in range(3)],
    ],
)
def test_start_rejects_unsafe_or_oversized_document_context(
    documents: list[dict],
) -> None:
    with pytest.raises(ValidationError):
        InterviewStartRequest(
            description="A policy assistant",
            known_capability_ids=[],
            capability_confidence="low",
            documents=documents,
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"description": "x", "known_capability_ids": []},
        {"description": "x", "capability_confidence": "low"},
        {
            "description": "x",
            "known_capability_ids": ["tool_use", "tool_use"],
            "capability_confidence": "low",
        },
        {
            "description": "x",
            "known_capability_ids": ["not_a_capability"],
            "capability_confidence": "low",
        },
    ],
)
def test_start_rejects_missing_duplicate_or_unknown_capability_input(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        InterviewStartRequest.model_validate(payload)


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (InterviewStartRequest, {"description": "x", "state": None}),
        (
            InterviewTurnRequest,
            {
                "state": _state().model_dump(),
                "request_id": "req-1",
                "response": {},
                "description": "field from start",
            },
        ),
        (InterviewEndRequest, {"state": _state().model_dump(), "response": {}}),
    ],
)
def test_lifecycle_requests_forbid_fields_from_another_operation(
    model, payload
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_the_result_union_rebuilds_success_and_failure_from_json() -> None:
    adapter: TypeAdapter[InterviewResult] = TypeAdapter(InterviewResult)
    success = InterviewSuccess(
        state=_state(),
        stage=InterviewStep.BEHAVIOURS,
        outcome="awaiting_response",
    )
    failure = InterviewFailure(
        code=InterviewErrorCode.REQUEST_ID_MISMATCH,
        message="stale",
        retryable=False,
        state=_state(),
    )

    for result in (success, failure):
        rebuilt = adapter.validate_json(adapter.dump_json(result))
        assert type(rebuilt) is type(result)


def test_the_compile_result_keeps_its_file_named_aliases() -> None:
    from tests.fixtures.wizard.specifications import research_assistant

    result = CompileResult(
        specification_yaml="schema_version: 1\n", specification=research_assistant()
    )
    assert (
        result.model_dump(by_alias=True)["specification.yaml"] == "schema_version: 1\n"
    )
