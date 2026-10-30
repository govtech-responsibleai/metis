"""Read-only grader catalogue routes.

This module owns the presentation-only catalogue capability. It uses the public wizard facade and
does not import wizard application or library internals.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from metis.api.routes.wizard import ServiceError
from metis.wizard import GraderSummary, grader_catalogue

router = APIRouter(prefix="/api/v1", tags=["graders"])


@router.get(
    "/graders",
    summary="List installed grader summaries",
    response_model=list[GraderSummary],
    responses={500: {"model": ServiceError}},
)
def graders() -> JSONResponse:
    """Return read-only grader metadata for web presentation."""
    try:
        rows = grader_catalogue()
    except Exception:
        return JSONResponse(
            ServiceError(
                code="internal_error",
                message="The grader catalogue could not be loaded.",
                retryable=False,
            ).model_dump(),
            status_code=500,
        )
    return JSONResponse(
        [row.model_dump(mode="json") for row in rows],
        status_code=200,
    )


__all__ = ["router"]
