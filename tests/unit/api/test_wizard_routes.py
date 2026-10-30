"""The HTTP adapter for the Interview lifecycle and compilation."""

from __future__ import annotations

from copy import deepcopy

import httpx
import pytest
from fastapi.testclient import TestClient

from metis.api.main import create_app
from metis.api.routes import wizard as wizard_routes
from metis.wizard.application.interviewer import InterviewerOutputError
from metis.wizard.contracts import (
    ChatRequest,
    ChatResponse,
    InterviewEndRequest,
    InterviewStartRequest,
    InterviewState,
    InterviewTurnRequest,
    Perspective,
    Specification,
)
from metis.wizard.domain.permissions import InterviewStep
from tests.fixtures.api._shared import scripted_interview_handler
from tests.fixtures.wizard.connections import (
    OPENAPI_DOCUMENT,
    PLANTED_SECRET,
    connection,
    http_binding,
    mock_client_factory,
)
from tests.fixtures.wizard.context import interview_context
from tests.fixtures.wizard.scripted import ScriptedInterviewer
from tests.fixtures.wizard.specifications import research_assistant


def _start_body() -> dict[str, object]:
    return InterviewStartRequest(
        description="A policy research assistant",
        known_capability_ids=[],
        capability_confidence="low",
    ).model_dump(mode="json")


def _empty_specification() -> dict[str, object]:
    return Specification.model_validate(
        {"target": {"name": "", "description": "", "users": ""}}
    ).model_dump(mode="json")


def _pending_state() -> InterviewState:
    return InterviewState(
        specification=research_assistant(),
        context=interview_context(),
        behaviours_confirmed=True,
        pending=ChatRequest(
            prompt="What should change?",
            request_id="req-1",
            stage=InterviewStep.CRITERIA,
        ),
    )


def test_start_returns_state_with_a_pending_request(client: TestClient) -> None:
    response = client.post("/api/v1/wizard/interview/start", json=_start_body())

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "success"
    assert body["outcome"] == "awaiting_response"
    assert body["state"]["pending"]["request_id"]
    assert body["state"]["context"]["perspective"] == "end_user"
    assert body["state"]["context"]["capability_evidence"] == {
        "known_capability_ids": [],
        "confidence": "low",
    }


def test_extract_returns_text_in_upload_order_without_server_state(
    make_client,
) -> None:
    extracted = make_client().post(
        "/api/v1/wizard/documents/extract",
        files=[
            ("files", ("second.txt", b"Second document", "text/plain")),
            ("files", ("first.md", b"# First document", "text/markdown")),
        ],
    )

    assert extracted.status_code == 200
    assert extracted.json() == {
        "documents": [
            {"name": "second.txt", "text": "Second document"},
            {"name": "first.md", "text": "# First document"},
        ]
    }

    started = make_client().post(
        "/api/v1/wizard/interview/start",
        json={
            **_start_body(),
            "documents": [extracted.json()["documents"][0]],
        },
    )
    assert started.status_code == 200
    state = started.json()["state"]
    assert state["context"]["opening_description"] == _start_body()["description"]
    assert state["context"]["documents"] == [
        {"name": "second.txt", "text": "Second document"}
    ]


def test_extract_returns_typed_file_error_and_no_partial_result(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/wizard/documents/extract",
        files=[
            ("files", ("readable.txt", b"Some text", "text/plain")),
            ("files", ("archive.xlsx", b"not read as text", "application/zip")),
        ],
    )

    assert response.status_code == 400
    assert response.json() == {
        "type": "failure",
        "code": "unsupported_file_type",
        "message": "archive.xlsx: Interview text is supported only for TXT, Markdown, YAML, JSON, CSV, PDF, and DOCX files.",
        "retryable": False,
    }


def test_start_records_the_chosen_perspective(client: TestClient) -> None:
    body = {
        "description": "A policy research assistant",
        "perspective": Perspective.SECURITY.value,
        "known_capability_ids": ["tool_use"],
        "capability_confidence": "high",
    }

    response = client.post("/api/v1/wizard/interview/start", json=body)

    assert response.status_code == 200
    assert response.json()["state"]["context"]["perspective"] == "security"
    assert response.json()["state"]["context"]["capability_evidence"] == {
        "known_capability_ids": ["tool_use"],
        "confidence": "high",
    }


def test_a_stale_request_id_is_a_400_with_the_state_echoed_back(
    client: TestClient,
) -> None:
    opening = client.post("/api/v1/wizard/interview/start", json=_start_body()).json()
    state = opening["state"]
    body = {
        "state": state,
        "request_id": "not-the-pending-id",
        "response": ChatResponse(text="hi").model_dump(mode="json"),
    }

    response = client.post("/api/v1/wizard/interview/turn", json=body)

    assert response.status_code == 400
    assert response.json()["code"] == "request_id_mismatch"
    assert response.json()["state"] == state


def test_a_body_that_breaks_the_schema_is_a_422_in_the_service_error_shape(
    client: TestClient,
) -> None:
    response = client.post("/api/v1/wizard/interview/start", json={})

    assert response.status_code == 422
    assert response.json()["type"] == "failure"
    assert response.json()["code"] == "validation_error"


@pytest.mark.parametrize("field", ["request_id", "stage"])
@pytest.mark.parametrize(
    "value", [pytest.param(None, id="null"), pytest.param("missing")]
)
def test_pending_request_metadata_is_required_and_non_null_over_http(
    client: TestClient, field: str, value: object
) -> None:
    opening = client.post("/api/v1/wizard/interview/start", json=_start_body()).json()
    state = deepcopy(opening["state"])
    if value == "missing":
        state["pending"].pop(field)
    else:
        state["pending"][field] = value
    body = {
        "state": state,
        "request_id": "req-1",
        "response": ChatResponse(text="a policy tool").model_dump(mode="json"),
    }

    response = client.post("/api/v1/wizard/interview/turn", json=body)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_an_exhausted_model_is_a_503_retryable_failure(make_client) -> None:
    class ClarifyUnavailable(ScriptedInterviewer):
        def clarify(self, specification, history, context=None):
            raise InterviewerOutputError("three attempts, all failed")

    client = make_client(ClarifyUnavailable())
    response = client.post("/api/v1/wizard/interview/start", json=_start_body())

    assert response.status_code == 503
    assert response.json()["code"] == "model_unavailable"
    assert response.json()["retryable"] is True
    assert response.json()["state"] is None


def test_an_exhausted_model_during_turn_is_a_503_with_safe_state(make_client) -> None:
    class ClarifyUnavailable(ScriptedInterviewer):
        def clarify(self, specification, history, context=None):
            raise InterviewerOutputError("three attempts, all failed")

    opening = (
        make_client().post("/api/v1/wizard/interview/start", json=_start_body()).json()
    )
    state = opening["state"]
    response = make_client(ClarifyUnavailable()).post(
        "/api/v1/wizard/interview/turn",
        json={
            "state": state,
            "request_id": state["pending"]["request_id"],
            "response": ChatResponse(text="It answers policy questions.").model_dump(
                mode="json"
            ),
        },
    )

    assert response.status_code == 503
    assert response.json()["code"] == "model_unavailable"
    assert response.json()["state"] == state


def test_an_exhausted_model_during_end_is_a_503_with_safe_state(make_client) -> None:
    class DraftUnavailable(ScriptedInterviewer):
        def draft_behaviours(self, specification, history, context=None):
            raise InterviewerOutputError("three attempts, all failed")

    state = InterviewState(
        specification=Specification.model_validate(
            {
                "target": {
                    "name": "Policy helper",
                    "description": "Answers policy questions",
                    "users": "Policy analysts",
                }
            }
        ),
        context=interview_context(),
    )
    response = make_client(DraftUnavailable()).post(
        "/api/v1/wizard/interview/end",
        json=InterviewEndRequest(state=state).model_dump(mode="json"),
    )

    assert response.status_code == 503
    assert response.json()["code"] == "model_unavailable"
    assert response.json()["state"] == state.model_dump(mode="json")


def test_an_unexpected_interview_fault_is_a_stable_500_failure(make_client) -> None:
    class BrokenInterviewer(ScriptedInterviewer):
        def clarify(self, specification, history, context=None):
            raise RuntimeError("unexpected provider bug")

    client = make_client(BrokenInterviewer())
    response = client.post("/api/v1/wizard/interview/start", json=_start_body())

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    assert response.json()["retryable"] is False


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v1/wizard/interview/start", _start_body()),
        (
            "/api/v1/wizard/interview/turn",
            InterviewTurnRequest(
                state=_pending_state(),
                request_id="req-1",
                response=ChatResponse(text="Make it clearer."),
            ).model_dump(mode="json"),
        ),
        (
            "/api/v1/wizard/interview/end",
            InterviewEndRequest(state=_pending_state()).model_dump(mode="json"),
        ),
    ],
)
def test_unexpected_interview_service_faults_are_stable_500_responses(
    path: str, body: dict[str, object]
) -> None:
    def fail(_request):
        raise RuntimeError("unexpected service fault")

    client = TestClient(
        create_app(interview_handler=fail), raise_server_exceptions=False
    )

    response = client.post(path, json=body)

    assert response.status_code == 500
    assert response.json() == {
        "type": "failure",
        "code": "internal_error",
        "message": "The API could not complete the request.",
        "retryable": False,
    }


def test_end_returns_best_effort_completion(client: TestClient) -> None:
    state = {
        "specification": research_assistant().model_dump(mode="json"),
        "context": interview_context().model_dump(mode="json"),
        "behaviours_confirmed": True,
        "confirmed": False,
        "history": [],
        "user_typed": [],
        "issued_ids": [],
        "pending": None,
    }

    response = client.post("/api/v1/wizard/interview/end", json={"state": state})

    assert response.status_code == 200
    assert response.json()["outcome"] == "done"


def test_compile_returns_the_two_file_named_yaml_strings(client: TestClient) -> None:
    response = client.post(
        "/api/v1/wizard/compile",
        json=research_assistant().model_dump(mode="json"),
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"specification.yaml", "specification"}
    assert body["specification.yaml"].strip()
    assert "scenarios" in body["specification.yaml"]


def test_a_specification_that_will_not_build_is_a_400_compilation_failure(
    client: TestClient,
) -> None:
    response = client.post("/api/v1/wizard/compile", json=_empty_specification())

    assert response.status_code == 400
    assert response.json()["code"] == "compilation_failed"


def test_an_unexpected_compile_fault_is_a_stable_500_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_specification):
        raise RuntimeError("unexpected compiler fault")

    monkeypatch.setattr(wizard_routes, "compile_specification", fail)
    client = TestClient(create_app(), raise_server_exceptions=False)

    response = client.post(
        "/api/v1/wizard/compile",
        json=research_assistant().model_dump(mode="json"),
    )

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"


def test_connection_check_returns_field_errors_without_the_rejected_value(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/wizard/connection/check",
        json={"binding": http_binding(auth={"secret_env": PLANTED_SECRET})},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["binding"] is None
    assert body["errors"][0]["loc"] == ["auth", "secret_env"]
    assert set(body["errors"][0]) == {"loc", "msg"}
    assert PLANTED_SECRET not in response.text


@pytest.mark.parametrize("operator_enabled", [False, True])
def test_connection_check_reaches_the_target_only_when_the_operator_turns_it_on(
    monkeypatch: pytest.MonkeyPatch, operator_enabled: bool
) -> None:
    from metis.wizard.application import connection as connection_module

    factory = mock_client_factory(lambda _: httpx.Response(200, json=OPENAPI_DOCUMENT))
    monkeypatch.setattr(connection_module, "_default_client", factory)
    monkeypatch.setenv("APP_KEY", PLANTED_SECRET)
    client = TestClient(
        create_app(scripted_interview_handler(), connection_check=operator_enabled)
    )

    response = client.post(
        "/api/v1/wizard/connection/check",
        json={"binding": http_binding(spec_url="https://app.example/openapi.json")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["live"] is operator_enabled
    assert body["status"] == ("checked" if operator_enabled else "unchecked")
    assert len(factory.requests) == (2 if operator_enabled else 0)
    assert PLANTED_SECRET not in response.text


def test_connection_check_never_puts_a_server_variable_into_a_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from metis.wizard.application import connection as connection_module

    factory = mock_client_factory(lambda _: httpx.Response(200, json=OPENAPI_DOCUMENT))
    monkeypatch.setattr(connection_module, "_default_client", factory)
    monkeypatch.setenv("APP_KEY", PLANTED_SECRET)
    client = TestClient(create_app(scripted_interview_handler(), connection_check=True))

    response = client.post(
        "/api/v1/wizard/connection/check",
        json={"binding": http_binding(spec_url="https://attacker.example/${APP_KEY}")},
    )

    body = response.json()
    probes = {probe["name"]: probe for probe in body["probes"]}
    assert factory.requests == []
    assert body["live"] is True
    assert body["status"] == "unchecked"
    # the variable probe still reports the server's environment
    assert probes["APP_KEY"]["message"] == "set"
    assert not probes["spec_url"]["ok"]
    assert "metis wizard connect" in probes["spec_url"]["message"]
    assert PLANTED_SECRET not in response.text


def test_connection_route_sets_and_removes_the_connection_on_state(
    client: TestClient,
) -> None:
    state = _pending_state().model_dump(mode="json")
    target = connection().model_dump(mode="json")

    connected = client.post(
        "/api/v1/wizard/connection", json={"state": state, "connection": target}
    )
    removed = client.post(
        "/api/v1/wizard/connection",
        json={"state": connected.json(), "connection": None},
    )

    assert connected.status_code == removed.status_code == 200
    assert connected.json()["context"]["connection"] == target
    assert connected.json()["specification"] == state["specification"]
    assert "connection" not in removed.json()["context"]


@pytest.mark.parametrize(
    "path", ["/api/v1/wizard/connection", "/api/v1/wizard/interview/start"]
)
def test_a_422_names_the_field_and_never_repeats_the_input(
    client: TestClient, path: str
) -> None:
    bad = {
        "transport": "http",
        "binding": http_binding(auth={"secret_env": PLANTED_SECRET}),
    }
    body = (
        {"state": _pending_state().model_dump(mode="json"), "connection": bad}
        if path.endswith("/connection")
        else {**_start_body(), "connection": bad}
    )

    response = client.post(path, json=body)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert "secret_env" in response.json()["message"]
    assert PLANTED_SECRET not in response.text


@pytest.mark.parametrize(
    ("host", "flag", "expected"),
    [
        ("127.0.0.1", None, True),
        ("0.0.0.0", None, False),
        ("0.0.0.0", "1", True),
        ("127.0.0.1", "0", False),
    ],
)
def test_the_live_check_is_on_for_a_local_api_unless_the_operator_says_otherwise(
    monkeypatch: pytest.MonkeyPatch, host: str, flag: str | None, expected: bool
) -> None:
    from metis.api.settings import CONNECTION_CHECK_ENV, connection_check_from_env

    monkeypatch.setenv("HOST", host)
    if flag is None:
        monkeypatch.delenv(CONNECTION_CHECK_ENV, raising=False)
    else:
        monkeypatch.setenv(CONNECTION_CHECK_ENV, flag)
    assert connection_check_from_env() is expected
