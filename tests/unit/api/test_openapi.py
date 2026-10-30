"""The generated OpenAPI document for the versioned Interview lifecycle."""

from __future__ import annotations

from fastapi.testclient import TestClient

from metis.wizard import (
    InterviewEndRequest,
    InterviewFailure,
    InterviewStartRequest,
    InterviewSuccess,
    InterviewTurnRequest,
)


def test_the_route_table_is_exactly_health_catalogues_interview_lifecycle_compile_and_package(
    client: TestClient,
) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert set(paths) == {
        "/health",
        "/api/v1/graders",
        "/api/v1/models",
        "/api/v1/wizard/config",
        "/api/v1/wizard/connection",
        "/api/v1/wizard/connection/check",
        "/api/v1/wizard/documents/extract",
        "/api/v1/wizard/package",
        "/api/v1/wizard/interview/start",
        "/api/v1/wizard/interview/turn",
        "/api/v1/wizard/interview/end",
        "/api/v1/wizard/compile",
    }


def test_grader_route_documents_success_and_internal_error(client: TestClient) -> None:
    responses = client.get("/openapi.json").json()["paths"]["/api/v1/graders"]["get"][
        "responses"
    ]
    assert {"200", "500"} <= set(responses)


def test_each_interview_route_documents_its_service_statuses(
    client: TestClient,
) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    for path in (
        "/api/v1/wizard/interview/start",
        "/api/v1/wizard/interview/turn",
        "/api/v1/wizard/interview/end",
    ):
        responses = paths[path]["post"]["responses"]
        assert {"200", "400", "422", "500", "503"}.issubset(responses)

    compile_responses = paths["/api/v1/wizard/compile"]["post"]["responses"]
    assert {"200", "400", "422", "500"}.issubset(compile_responses)


def test_wizard_tag_explains_the_client_held_state_loop(client: TestClient) -> None:
    document = client.get("/openapi.json").json()
    wizard = next(tag for tag in document["tags"] if tag["name"] == "wizard")

    assert "save the complete returned state" in wizard["description"].lower()
    assert "matching request id" in wizard["description"].lower()


def test_lifecycle_request_examples_are_named_and_schema_valid(
    client: TestClient,
) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    start_examples = paths["/api/v1/wizard/interview/start"]["post"]["requestBody"][
        "content"
    ]["application/json"]["examples"]
    assert set(start_examples) == {"research_assistant"}
    InterviewStartRequest.model_validate(start_examples["research_assistant"]["value"])

    turn_examples = paths["/api/v1/wizard/interview/turn"]["post"]["requestBody"][
        "content"
    ]["application/json"]["examples"]
    assert set(turn_examples) == {"chat", "choice", "form"}
    for name, example in turn_examples.items():
        request = InterviewTurnRequest.model_validate(example["value"])
        assert request.state.pending is not None
        assert request.request_id == request.state.pending.request_id
        assert request.response.type.value == name

    end_examples = paths["/api/v1/wizard/interview/end"]["post"]["requestBody"][
        "content"
    ]["application/json"]["examples"]
    assert set(end_examples) == {"finish_latest_state"}
    InterviewEndRequest.model_validate(end_examples["finish_latest_state"]["value"])


def test_lifecycle_response_examples_cover_success_and_safe_retry(
    client: TestClient,
) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    started = paths["/api/v1/wizard/interview/start"]["post"]["responses"]["200"][
        "content"
    ]["application/json"]["examples"]["awaiting_response"]["value"]
    InterviewSuccess.model_validate(started)

    retry = paths["/api/v1/wizard/interview/turn"]["post"]["responses"]["503"][
        "content"
    ]["application/json"]["examples"]["retry_latest_state"]["value"]
    failure = InterviewFailure.model_validate(retry)
    assert failure.retryable is True
    assert failure.state is not None


def test_concrete_request_models_have_flat_required_fields(client: TestClient) -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]

    start = schemas["InterviewStartRequest"]
    assert start["required"] == ["description"]
    assert start["additionalProperties"] is False
    assert "documents" in start["properties"]
    assert "documents" not in start["required"]

    turn = schemas["InterviewTurnRequest"]
    assert set(turn["required"]) == {"state", "request_id", "response"}
    assert turn["additionalProperties"] is False

    end = schemas["InterviewEndRequest"]
    assert end["required"] == ["state"]
    assert end["additionalProperties"] is False


def test_response_union_is_discriminated_by_result_type(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    result = paths["/api/v1/wizard/interview/turn"]["post"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    assert result["discriminator"]["propertyName"] == "type"
    assert set(result["discriminator"]["mapping"]) == {"success", "failure"}


def test_turn_response_body_is_discriminated_by_typed_response_kind(
    client: TestClient,
) -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    response = schemas["InterviewTurnRequest"]["properties"]["response"]

    assert response["discriminator"]["propertyName"] == "type"
    assert set(response["discriminator"]["mapping"]) == {
        "chat",
        "choice",
        "form",
    }


def test_state_schema_bounds_history_and_requires_non_null_pending_metadata(
    client: TestClient,
) -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]

    assert schemas["InterviewState-Input"]["properties"]["history"]["maxItems"] == 12
    for name in ("ChatRequest", "ChoiceRequest", "FormRequest"):
        request = schemas[f"{name}-Input" if name == "ChoiceRequest" else name]
        assert {"request_id", "stage"} <= set(request["required"])
        assert request["properties"]["request_id"] == {"type": "string"}
        assert request["properties"]["stage"] == {
            "$ref": "#/components/schemas/InterviewStep"
        }
