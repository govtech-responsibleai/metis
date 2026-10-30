"""The model settings of each LLM role, as the API process sees them.

The route returns the model name and the status of each role. It never returns a key or a URL.
The web client reads it to show a banner when a role is not configured.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from metis.api.routes.wizard import ServiceError
from metis.api.settings import Settings
from metis.core.model_settings import ROLES, ModelRole, missing_settings

router = APIRouter(prefix="/api/v1", tags=["models"])


class ModelStatus(BaseModel):
    """The status of one LLM role. It holds names only, never a key or a URL."""

    role: ModelRole
    label: str
    model: str
    source: str
    """Where the model came from: a variable name, ``user agent model``, or ``built-in
    default``. It never holds a key or a URL."""
    configured: bool
    affects_scores: bool
    missing_vars: list[str]
    """The variables that can supply the missing API key. Empty when ``configured``."""


def model_statuses(settings: Settings) -> list[ModelStatus]:
    """One status for each role, in the order of the flow."""
    missing = missing_settings(ROLES, settings.env)
    resolved = {role: settings.role(role) for role in ROLES}
    return [
        ModelStatus(
            role=role,
            label=spec.label,
            model=resolved[role].model,
            source=resolved[role].source,
            configured=role not in missing,
            affects_scores=spec.affects_scores,
            missing_vars=list(missing.get(role, ())),
        )
        for role, spec in ROLES.items()
    ]


@router.get(
    "/models",
    summary="List the model and status of each LLM role",
    response_model=list[ModelStatus],
    responses={500: {"model": ServiceError}},
)
def models(request: Request) -> list[ModelStatus]:
    """Return the model name and configured status of each role. No key or URL is returned."""
    settings = getattr(request.app.state, "model_settings", None) or Settings.from_env()
    return model_statuses(settings)


__all__ = ["ModelStatus", "model_statuses", "router"]
