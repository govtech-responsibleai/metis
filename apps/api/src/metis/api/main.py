"""The app composition root.

`main.py` creates the FastAPI app, keeps `/health`, includes the wizard router, and installs the
handlers that give every failure one stable JSON shape. It holds no user state: each request
carries the whole client-held interview state in its body.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from metis.api import __version__, core_version
from metis.api.routes.graders import router as graders_router
from metis.api.routes.models import router as models_router
from metis.api.routes.wizard import ServiceError
from metis.api.routes.wizard import router as wizard_router
from metis.api.settings import (
    InterviewHandler,
    Settings,
    SettingsError,
    WizardDependencies,
    build_dependencies,
)
from metis.core.logging import get_logger
from metis.wizard import InterviewerUnavailable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


logger = get_logger(__name__)

_OPENAPI_TAGS = [
    {
        "name": "wizard",
        "description": (
            "Drive one stateless Wizard Interview. Start returns client-held state. "
            "For each turn, save the complete returned state, read its pending screen, and send "
            "that state with the matching request id and response. End can return another "
            "pending screen. Compile or package the Specification after outcome is done."
        ),
    }
]


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Compose production collaborators before the app accepts requests.

    Missing model settings do not stop the start. The app keeps the error, `GET /api/v1/models`
    reports the missing roles, and each Interview route returns 503 `model_unavailable`. The
    connection check, compile, and package routes call no model, so they work without keys.
    """
    if getattr(app.state, "wizard_dependencies", None) is None:
        settings = Settings.from_env()
        app.state.model_settings = settings
        app.state.connection_check = settings.connection_check
        try:
            app.state.wizard_dependencies = build_dependencies(settings)
        except SettingsError as exc:
            app.state.settings_error = str(exc)
            logger.warning("api_model_settings_missing")
    yield


def create_app(
    interview_handler: InterviewHandler | None = None,
    *,
    connection_check: bool = False,
) -> FastAPI:
    """Assemble the API for production or with an injected handler for offline tests."""
    app = FastAPI(
        title="METIS API",
        version=__version__,
        lifespan=_lifespan,
        openapi_tags=_OPENAPI_TAGS,
    )
    if interview_handler is not None:
        app.state.wizard_dependencies = WizardDependencies(
            interview_handler=interview_handler
        )
        app.state.connection_check = connection_check

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "core_version": core_version}

    app.include_router(wizard_router)
    app.include_router(graders_router)
    app.include_router(models_router)

    @app.exception_handler(RequestValidationError)
    def _on_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # A request or Specification that does not match its schema. Reported in the service error
        # shape, not FastAPI's default body, so a client parses one failure format everywhere.
        # The message names each field and its reason but never the rejected input, which can
        # be a secret pasted into a target binding.
        error = ServiceError(
            code="validation_error",
            message=_validation_message(exc),
            retryable=False,
        )
        return JSONResponse(error.model_dump(), status_code=422)

    @app.exception_handler(InterviewerUnavailable)
    def _on_interviewer_unavailable(
        _request: Request, exc: InterviewerUnavailable
    ) -> JSONResponse:
        # The gateway is not configured or cannot be reached; the request changed nothing, so it
        # is safe to retry once the service is configured.
        error = ServiceError(code="model_unavailable", message=str(exc), retryable=True)
        return JSONResponse(error.model_dump(), status_code=503)

    @app.exception_handler(SettingsError)
    def _on_settings_error(_request: Request, exc: SettingsError) -> JSONResponse:
        error = ServiceError(code="model_unavailable", message=str(exc), retryable=True)
        return JSONResponse(error.model_dump(), status_code=503)

    @app.exception_handler(Exception)
    def _on_unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "api_unexpected_error",
            error_type=type(exc).__name__,
        )
        error = ServiceError(
            code="internal_error",
            message="The API could not complete the request.",
            retryable=False,
        )
        return JSONResponse(error.model_dump(), status_code=500)

    return app


def _validation_message(exc: RequestValidationError) -> str:
    """Name each failed field and its reason, without the input value."""
    lines = [
        f"{' -> '.join(str(part) for part in error.get('loc', ()))}: {error.get('msg', '')}"
        for error in exc.errors()
    ]
    count = len(lines)
    heading = f"{count} validation error{'' if count == 1 else 's'} in the request"
    return "\n".join([heading, *lines])


app = create_app()


__all__ = ["app", "create_app"]
