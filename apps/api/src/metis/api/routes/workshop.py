"""`GET /api/v1/workshop/env`: the `.env` lines that the operator gives to each participant.

`METIS_WORKSHOP_ENV` names the variables. The app reads their values at startup. Each user
account with a login session can read them, so they must be values for participants only.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from metis.api.errors import RouteError
from metis.api.routes.wizard import ServiceError

router = APIRouter(prefix="/api/v1/workshop", tags=["workshop"])


class WorkshopVariable(BaseModel):
    """One variable for the `.env` file of a participant."""

    name: str
    value: str


class WorkshopEnv(BaseModel):
    """The workshop variables, in the order of `METIS_WORKSHOP_ENV`."""

    variables: list[WorkshopVariable]


@router.get(
    "/env",
    summary="Read the workshop variables for the METIS CLI",
    response_model=WorkshopEnv,
    responses={404: {"model": ServiceError}},
)
def read_workshop_env(request: Request) -> WorkshopEnv:
    """Return each variable in `METIS_WORKSHOP_ENV` that has a value.

    A name with no value or an empty value is not in the list. A server with no
    `METIS_WORKSHOP_ENV` gets 404 `not_found`.
    """
    variables: tuple[WorkshopVariable, ...] | None = request.app.state.workshop_env
    if variables is None:
        raise RouteError(
            404, "not_found", "This METIS server gives no workshop variables."
        )
    return WorkshopEnv(variables=list(variables))


__all__ = ["WorkshopEnv", "WorkshopVariable", "router"]
