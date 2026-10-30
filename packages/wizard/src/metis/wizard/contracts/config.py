"""Public configuration values needed by wizard doors."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from metis.wizard.contracts.capabilities import CapabilityCategoryDefinition
from metis.wizard.contracts.documents import InterviewConfigDocumentLimits
from metis.wizard.contracts.interview_state import Perspective


class PerspectiveDefinition(BaseModel):
    """The user-facing label and question for one Interview perspective."""

    model_config = ConfigDict(extra="forbid")

    id: Perspective
    label: str = Field(min_length=1)
    question: str = Field(min_length=1)


class InterviewConfig(BaseModel):
    """Package-owned values that a wizard door needs to render its opening screen."""

    model_config = ConfigDict(extra="forbid")

    opening_question: str = Field(min_length=1)
    working_status: str = Field(min_length=1)
    perspectives: list[PerspectiveDefinition]
    capability_categories: list[CapabilityCategoryDefinition]
    document_limits: InterviewConfigDocumentLimits = Field(
        default_factory=InterviewConfigDocumentLimits
    )


__all__ = [
    "InterviewConfig",
    "InterviewConfigDocumentLimits",
    "PerspectiveDefinition",
]
