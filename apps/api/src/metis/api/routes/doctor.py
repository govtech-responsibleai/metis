"""`GET /api/v1/doctor`: the checks of `metis doctor`, from `metis.core.doctor`.

The route returns each `DoctorResult` in a response shape that the API owns. It holds no
check rule, and a client finds a failure from the status of each check. Two checks call a
service with a short timeout, so the route is a plain function that FastAPI runs on its
thread pool.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from metis.core import doctor

router = APIRouter(prefix="/api/v1", tags=["doctor"])


class DoctorCheck(BaseModel):
    """The result of one check."""

    name: str
    status: Literal["pass", "fail", "warn", "skip"] = Field(
        description="A warning or a skip does not stop a run. A failure does."
    )
    detail: str
    fix: str | None = Field(description="A one-line fix for a failure or a warning.")


@router.get(
    "/doctor",
    summary="Check the environment before a run",
    response_model=list[DoctorCheck],
)
def run_doctor() -> list[DoctorCheck]:
    """Run every check of `metis doctor` and return the results in display order.

    The checks report variable and service names, never values.
    """
    return [
        DoctorCheck(
            name=result.name,
            status=result.status.value,
            detail=result.detail,
            fix=result.fix,
        )
        for result in doctor.run_doctor()
    ]


__all__ = ["router"]
