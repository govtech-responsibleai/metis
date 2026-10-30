"""HTTP routes for the wizard Interview lifecycle, document extraction, compilation and download.

This router is a thin HTTP adapter over the metis-wizard package. It parses a typed request body,
calls the wizard's public facade, and maps the typed result onto an HTTP status code — it adds no
behaviour of its own. Every stage, Specification, prompt, matching and compilation rule lives in
metis-wizard.

Document extraction stands outside the Interview lifecycle. It reads the uploaded file streams,
returns their text, and retains neither the files nor any state, so the caller holds the result.

For the lifecycle and complete client examples, see ``docs/guide/wizard/api.md``.

Status mapping (from the design):

| result                                           | status |
|--------------------------------------------------|-------:|
| successful start, turn, end, compile, or extract |    200 |
| valid JSON with invalid state or stale id        |    400 |
| unreadable or unsupported document upload        |    400 |
| exhausted model retries, unchanged state         |    503 |
| unexpected non-retryable failure                 |    500 |

A 400 carries a typed code: an `InterviewErrorCode` from the lifecycle routes, and a
`DocumentExtractionErrorCode` from the extraction route.

Request/Specification schema failures become 422 through the app's validation handler.
"""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, Annotated, Literal

from fastapi import APIRouter, Body, Depends, File, Form, Request, UploadFile
from fastapi.openapi.models import Example
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from metis.api.settings import SettingsError
from metis.wizard import (
    CompilationError,
    CompileResult,
    ConnectionCheckRequest,
    ConnectionCheckResult,
    DocumentExtractionError,
    DocumentExtractionErrorCode,
    DocumentExtractionResult,
    InterviewConfig,
    InterviewConnectionRequest,
    InterviewEndRequest,
    InterviewErrorCode,
    InterviewFailure,
    InterviewResult,
    InterviewStartRequest,
    InterviewState,
    InterviewSuccess,
    InterviewTurnRequest,
    Specification,
    SpecificationError,
    SpecificationFixture,
    TargetConnection,
    check_connection,
    compile_specification,
    extract_documents,
    interview_client_config,
    package_specification,
    set_connection,
    validate_binding,
)

if TYPE_CHECKING:
    from metis.api.settings import WizardDependencies

router = APIRouter(prefix="/api/v1/wizard", tags=["wizard"])

# Only two failure codes are not a plain caller error: an exhausted model gateway is a transient
# service condition, and an unexpected fault is a bug. Every other code is the client's to fix.
_STATUS: dict[InterviewErrorCode, int] = {
    InterviewErrorCode.MODEL_UNAVAILABLE: 503,
    InterviewErrorCode.INTERNAL_ERROR: 500,
}


class ServiceError(BaseModel):
    """The stable error body for compile and validation failures.

    It shares its shape — `type`, `code`, `message`, `retryable` — with `InterviewFailure`, so a
    client parses every failure the same way whichever route raised it.
    """

    type: Literal["failure"] = "failure"
    code: str
    message: str
    retryable: bool = False


class DocumentExtractionFailure(ServiceError):
    """The existing API failure shape with a typed document error code."""

    code: DocumentExtractionErrorCode  # pyright: ignore[reportIncompatibleVariableOverride]


def _example_state(pending: dict[str, object] | None) -> InterviewState:
    """Build one small, schema-valid state for the OpenAPI lifecycle examples."""
    return InterviewState.model_validate(
        {
            "specification": {
                "target": {
                    "name": "Research assistant",
                    "users": "Policy analysts",
                    "description": "Answers policy questions from approved sources.",
                }
            },
            "context": {
                "perspective": "end_user",
                "capability_evidence": {
                    "known_capability_ids": ["internet_search_access"],
                    "confidence": "medium",
                },
                "opening_description": "A research assistant for policy analysts.",
                "documents": [],
            },
            "pending": pending,
        }
    )


_CHAT_STATE = _example_state(
    {
        "type": "chat",
        "prompt": "Who uses the assistant, and what decisions does it support?",
        "request_id": "req-chat-example",
        "stage": "clarify",
    }
)
_CHOICE_STATE = _example_state(
    {
        "type": "choice",
        "prompt": "Review the proposed Behaviours.",
        "request_id": "req-choice-example",
        "stage": "behaviours",
        "options": [
            {
                "id": {"action": "continue"},
                "label": "Continue",
                "primary": True,
            }
        ],
    }
)
_FORM_STATE = _example_state(
    {
        "type": "form",
        "prompt": "Add the missing target details.",
        "request_id": "req-form-example",
        "stage": "clarify",
        "fields": [
            {
                "id": "target_name",
                "label": "Target name",
                "multiline": False,
            },
            {
                "id": "target_description",
                "label": "Target description",
            },
        ],
    }
)

_START_EXAMPLES: dict[str, Example] = {
    "research_assistant": Example(
        summary="Start with the complete opening evidence",
        value=InterviewStartRequest.model_validate(
            {
                "description": "A research assistant for policy analysts.",
                "perspective": "end_user",
                "known_capability_ids": ["internet_search_access"],
                "capability_confidence": "medium",
            }
        ).model_dump(mode="json"),
    ),
}
_TURN_EXAMPLES: dict[str, Example] = {
    "chat": Example(
        summary="Answer a chat screen",
        value=InterviewTurnRequest.model_validate(
            {
                "state": _CHAT_STATE,
                "request_id": "req-chat-example",
                "response": {
                    "type": "chat",
                    "text": "Policy analysts use it to compare new guidance.",
                },
            }
        ).model_dump(mode="json"),
    ),
    "choice": Example(
        summary="Choose an option offered by a choice screen",
        value=InterviewTurnRequest.model_validate(
            {
                "state": _CHOICE_STATE,
                "request_id": "req-choice-example",
                "response": {"type": "choice", "selected": ["continue"]},
            }
        ).model_dump(mode="json"),
    ),
    "form": Example(
        summary="Submit the fields offered by a form screen",
        value=InterviewTurnRequest.model_validate(
            {
                "state": _FORM_STATE,
                "request_id": "req-form-example",
                "response": {
                    "type": "form",
                    "values": {
                        "target_name": "Policy research assistant",
                        "target_description": (
                            "Answers policy questions from approved sources."
                        ),
                    },
                },
            }
        ).model_dump(mode="json"),
    ),
}
_END_EXAMPLES: dict[str, Example] = {
    "finish_latest_state": Example(
        summary="Ask for best-effort completion with the latest state",
        value=InterviewEndRequest(state=_CHAT_STATE).model_dump(mode="json"),
    ),
}
_AWAITING_RESPONSE_EXAMPLE = InterviewSuccess.model_validate(
    {
        "state": _CHAT_STATE,
        "stage": "clarify",
        "outcome": "awaiting_response",
    }
).model_dump(mode="json")
_RETRYABLE_FAILURE_EXAMPLE = InterviewFailure(
    code=InterviewErrorCode.MODEL_UNAVAILABLE,
    message="The Interview model is temporarily unavailable.",
    retryable=True,
    state=_CHAT_STATE,
).model_dump(mode="json")


@router.post(
    "/documents/extract",
    summary="Extract text from Interview documents",
    response_model=DocumentExtractionResult,
    responses={
        400: {"model": DocumentExtractionFailure},
        422: {"model": ServiceError},
        500: {"model": ServiceError},
    },
)
def extract_document_text(
    files: list[UploadFile] = File(...),
) -> JSONResponse:
    """Read selected file streams and return text without retaining files or state."""
    try:
        result = extract_documents(
            SpecificationFixture(name=upload.filename or "", stream=upload.file)
            for upload in files
        )
    except DocumentExtractionError as exc:
        return JSONResponse(
            DocumentExtractionFailure(
                code=exc.code,
                message=f"{exc.filename}: {exc}",
                retryable=False,
            ).model_dump(mode="json"),
            status_code=400,
        )
    finally:
        for upload in files:
            with suppress(OSError):
                upload.file.close()
    return JSONResponse(result.model_dump(mode="json"), status_code=200)


def get_dependencies(request: Request) -> WizardDependencies:
    """Return the startup-composed public Interview handler.

    Raises ``SettingsError`` (503 `model_unavailable`) when the app started without the
    interview settings.
    """
    dependencies = getattr(request.app.state, "wizard_dependencies", None)
    if dependencies is None:
        message = getattr(request.app.state, "settings_error", None)
        if message is not None:
            raise SettingsError(message)
        raise RuntimeError(
            "Wizard dependencies were not composed at application startup."
        )
    return dependencies


@router.get(
    "/config",
    summary="Get package-owned wizard client configuration",
    response_model=InterviewConfig,
    responses={500: {"model": ServiceError}},
)
def config() -> InterviewConfig:
    """Return presentation text without copying it into the HTTP client."""
    return interview_client_config()


class _ConnectionInvalid(ValueError):
    """A connection field that the route refuses. The message is safe to return: no value."""


def _target_connection(raw: str) -> TargetConnection:
    """Parse the connection form field and apply the same check as `/connection/check`."""
    target = TargetConnection.model_validate_json(raw)
    result = validate_binding(
        target.binding.model_dump(mode="json", exclude_defaults=True)
    )
    if result.errors:
        reasons = "; ".join(
            f"{'.'.join(str(part) for part in error.loc)}: {error.msg}"
            for error in result.errors
        )
        raise _ConnectionInvalid(f"The target connection is not valid. {reasons}")
    return target


@router.post(
    "/package",
    summary="Package a wizard Specification and fixtures into a ZIP",
    response_class=Response,
    response_model=None,
    responses={
        200: {
            "content": {
                "application/zip": {"schema": {"type": "string", "format": "binary"}}
            }
        },
        400: {"model": ServiceError},
        422: {"model": ServiceError},
        500: {"model": ServiceError},
    },
)
def package(
    specification: Annotated[str | None, Form()] = None,
    files: Annotated[list[UploadFile] | None, File()] = None,
    state: Annotated[str | None, Form()] = None,
    connection: Annotated[str | None, Form()] = None,
) -> Response | JSONResponse:
    """Build one request-scoped engine-ready ZIP without retaining uploaded files.

    Send `state` for an Interview or `specification` for a manual export. With `specification`,
    an optional `connection` (a `TargetConnection` as JSON) adds `outputs/target-binding.yaml`
    and names the generic runner, the same as an Interview with that connection. An Interview
    carries its connection in its state, so `connection` with `state` is rejected. A binding
    that fails the `/connection/check` validation gives 400 `validation_error`. The message
    names each field and its reason, and never a value.
    """
    uploads = files or []
    try:
        if (specification is None) == (state is None):
            raise ValueError("Supply exactly one of state or specification.")
        if state is not None and connection is not None:
            raise _ConnectionInvalid(
                "Send a connection only with a specification. "
                "An Interview state carries its own connection."
            )
        parsed = (
            InterviewState.model_validate_json(state)
            if state is not None
            else Specification.model_validate_json(specification or "")
        )
        target = _target_connection(connection) if connection is not None else None
        fixtures: list[SpecificationFixture] = []
        for upload in uploads:
            fixtures.append(
                SpecificationFixture(
                    name=upload.filename or "",
                    stream=upload.file,
                )
            )
        archive = package_specification(parsed, fixtures, connection=target)
    except (CompilationError, SpecificationError) as exc:
        return JSONResponse(
            ServiceError(
                code="compilation_failed", message=str(exc), retryable=False
            ).model_dump(),
            status_code=400,
        )
    except _ConnectionInvalid as exc:
        return JSONResponse(
            ServiceError(
                code="validation_error", message=str(exc), retryable=False
            ).model_dump(),
            status_code=400,
        )
    except ValueError:
        return JSONResponse(
            ServiceError(
                code="validation_error",
                message="Supply one valid Interview state or manual Specification.",
                retryable=False,
            ).model_dump(),
            status_code=400,
        )
    finally:
        for upload in uploads:
            with suppress(OSError):
                upload.file.close()
    return Response(
        content=archive.content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{archive.filename}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.post(
    "/interview/start",
    summary="Start a wizard Interview from its opening evidence",
    response_model=InterviewResult,
    responses={
        200: {
            "description": "The first client-held state and pending screen.",
            "content": {
                "application/json": {
                    "examples": {
                        "awaiting_response": {
                            "summary": "Save the returned state before the next turn",
                            "value": _AWAITING_RESPONSE_EXAMPLE,
                        }
                    }
                }
            },
        },
        400: {"model": InterviewFailure},
        422: {"model": ServiceError},
        500: {"model": InterviewFailure},
        503: {"model": InterviewFailure},
    },
)
def start(
    body: Annotated[
        InterviewStartRequest,
        Body(openapi_examples=_START_EXAMPLES),
    ],
    dependencies: WizardDependencies = Depends(get_dependencies),
) -> JSONResponse:
    """Create client-held Interview state from the complete opening input.

    Save the complete `state` from the success response. It is the state for the first turn.
    """
    result = dependencies.interview_handler(body)
    return _result_response(result)


@router.post(
    "/interview/turn",
    summary="Answer the pending request in one wizard Interview",
    response_model=InterviewResult,
    responses={
        400: {"model": InterviewFailure},
        422: {"model": ServiceError},
        500: {"model": InterviewFailure},
        503: {
            "model": InterviewFailure,
            "content": {
                "application/json": {
                    "examples": {
                        "retry_latest_state": {
                            "summary": "Keep the safe state and retry later",
                            "value": _RETRYABLE_FAILURE_EXAMPLE,
                        }
                    }
                }
            },
        },
    },
)
def turn(
    body: Annotated[
        InterviewTurnRequest,
        Body(openapi_examples=_TURN_EXAMPLES),
    ],
    dependencies: WizardDependencies = Depends(get_dependencies),
) -> JSONResponse:
    """Apply one typed response to the client's complete current Interview state.

    Send the latest full state and its pending request id. Replace the saved state with the state
    from each successful response.
    """
    result = dependencies.interview_handler(body)
    return _result_response(result)


@router.post(
    "/interview/end",
    summary="Best-effort finish one wizard Interview",
    response_model=InterviewResult,
    responses={
        400: {"model": InterviewFailure},
        422: {"model": ServiceError},
        500: {"model": InterviewFailure},
        503: {"model": InterviewFailure},
    },
)
def end(
    body: Annotated[
        InterviewEndRequest,
        Body(openapi_examples=_END_EXAMPLES),
    ],
    dependencies: WizardDependencies = Depends(get_dependencies),
) -> JSONResponse:
    """Run best-effort completion on the client's complete current Interview state.

    Save the returned state. An `awaiting_response` result contains another screen to answer.
    """
    result = dependencies.interview_handler(body)
    return _result_response(result)


@router.post(
    "/connection/check",
    summary="Check a target binding",
    response_model=ConnectionCheckResult,
    responses={422: {"model": ServiceError}, 500: {"model": ServiceError}},
)
def check_target_connection(
    body: ConnectionCheckRequest, request: Request
) -> ConnectionCheckResult:
    """Validate binding values and return field errors as `loc` and `msg` only.

    By default, the API reaches the target only when it listens on this computer (`127.0.0.1`,
    `localhost`, or `::1`). `METIS_API_CONNECTION_CHECK=1` or `0` overrides this. When the check
    is off, `live` is false and `status` is `unchecked`.

    The API never puts a value from its own environment into a URL that it requests. A URL that
    names a `${NAME}` variable is not requested, and its probe tells the user to check it with
    `metis wizard connect`.
    """
    # The check calls no model, so it reads its switch from the app and works without keys.
    live: bool = getattr(request.app.state, "connection_check", False)
    return check_connection(body.binding, live=live, expand_variables=False)


@router.post(
    "/connection",
    summary="Set or remove the target connection on Interview state",
    response_model=InterviewState,
    responses={422: {"model": ServiceError}, 500: {"model": ServiceError}},
)
def update_target_connection(body: InterviewConnectionRequest) -> InterviewState:
    """Return the state with the connection set, or removed when `connection` is null.

    This changes no Specification content and calls no model. Save the returned state.
    """
    return set_connection(body.state, body.connection)


def _result_response(result: InterviewResult) -> JSONResponse:
    """Map one public Interview result to its stable HTTP status and JSON body."""
    if isinstance(result, InterviewFailure):
        status = _STATUS.get(result.code, 400)
        return JSONResponse(result.model_dump(mode="json"), status_code=status)
    return JSONResponse(result.model_dump(mode="json"), status_code=200)


@router.post(
    "/compile",
    summary="Compile a finished wizard Specification into YAML",
    response_model=CompileResult,
    responses={
        400: {"model": ServiceError},
        422: {"model": ServiceError},
        500: {"model": ServiceError},
    },
)
def compile_(specification: Specification) -> JSONResponse:
    """Compile a runnable `Specification` into YAML with assigned Task IDs.

    The response contains `specification.yaml` and `specification` with assigned Task IDs.
    The API does not write files or save the Specification on the server.
    """
    try:
        result = compile_specification(specification)
    except CompilationError as exc:
        error = ServiceError(
            code="compilation_failed", message=str(exc), retryable=False
        )
        return JSONResponse(error.model_dump(), status_code=400)
    return JSONResponse(result.model_dump(mode="json", by_alias=True), status_code=200)


__all__ = ["InterviewConfig", "ServiceError", "router"]
