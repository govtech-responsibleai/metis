"""Public typed Interview-operation and compilation contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from metis.wizard.contracts.capabilities import CapabilityId
from metis.wizard.contracts.connection import TargetConnection
from metis.wizard.contracts.conversation import AnyResponse
from metis.wizard.contracts.documents import (
    InterviewDocument,
    validate_interview_documents,
)
from metis.wizard.contracts.interview_state import (
    CapabilityConfidence,
    InterviewState,
    Perspective,
)
from metis.wizard.domain.permissions import InterviewStep
from metis.wizard.domain.specification import Specification


class InterviewStartRequest(BaseModel):
    """The first operation, containing all opening evidence."""

    # a rejected binding value can be a pasted secret, so validation errors never repeat input
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    description: str
    perspective: Perspective = Perspective.END_USER
    known_capability_ids: list[CapabilityId] | None = None
    capability_confidence: CapabilityConfidence | None = None
    documents: list[InterviewDocument] = Field(default_factory=list)
    # The target connection for run mode. Omit it for spec-only mode.
    connection: TargetConnection | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @field_validator("description")
    @classmethod
    def _require_description(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("description must not be blank")
        return value

    @field_validator("known_capability_ids")
    @classmethod
    def _reject_duplicate_capabilities(
        cls, value: list[CapabilityId] | None
    ) -> list[CapabilityId] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("known_capability_ids must not contain duplicates")
        return value

    @model_validator(mode="after")
    def _paired_capability_evidence(self) -> InterviewStartRequest:
        if (self.known_capability_ids is None) != (self.capability_confidence is None):
            raise ValueError(
                "Supply known_capability_ids and capability_confidence together, or omit both"
            )
        return self

    @field_validator("documents")
    @classmethod
    def _validate_documents(
        cls, value: list[InterviewDocument]
    ) -> list[InterviewDocument]:
        return validate_interview_documents(value)


class _InterviewStateRequest(BaseModel):
    """Shared required state for operations after start."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    state: InterviewState


class InterviewTurnRequest(_InterviewStateRequest):
    """Answer the one pending request with its typed response."""

    request_id: str
    response: AnyResponse


class InterviewEndRequest(_InterviewStateRequest):
    """Run best-effort completion for the supplied client-held state."""


class InterviewConnectionRequest(_InterviewStateRequest):
    """Set the target connection on client-held state, or remove it with `None`.

    This is not an Interview operation: it changes no Specification content and calls no model.
    """

    connection: TargetConnection | None = None


InterviewRequest: TypeAlias = (
    InterviewStartRequest | InterviewTurnRequest | InterviewEndRequest
)


class InterviewErrorCode(StrEnum):
    """Stable failure codes exposed by the in-process and HTTP interfaces."""

    NO_PENDING_REQUEST = "no_pending_request"
    REQUEST_ID_MISMATCH = "request_id_mismatch"
    RESPONSE_TYPE_MISMATCH = "response_type_mismatch"
    RESPONSE_NOT_OFFERED = "response_not_offered"
    MODEL_UNAVAILABLE = "model_unavailable"
    CONTEXT_BUDGET_EXCEEDED = "context_budget_exceeded"
    COMPLETION_FAILED = "completion_failed"
    INTERNAL_ERROR = "internal_error"


class MissingDataCode(StrEnum):
    """Stable codes for gaps that stop a Specification from being runnable."""

    TARGET_INCOMPLETE = "target_incomplete"
    BEHAVIOURS_INCOMPLETE = "behaviours_incomplete"
    NO_MEASURED_BEHAVIOUR = "no_measured_behaviour"
    CRITERIA_INCOMPLETE = "criteria_incomplete"
    NO_PERSONAS = "no_personas"
    NO_SCENARIOS = "no_scenarios"
    BEHAVIOUR_UNCOVERED = "behaviour_uncovered"
    SCENARIO_NO_SELECTED_BEHAVIOUR = "scenario_no_selected_behaviour"
    NO_SELECTED_TEST_CASE = "no_selected_test_case"
    SCENARIO_UNKNOWN_REFERENCE = "scenario_unknown_reference"
    SCENARIO_DUPLICATE_PAIR = "scenario_duplicate_pair"
    SCENARIO_INVALID_TRIALS = "scenario_invalid_trials"


class MissingData(BaseModel):
    """One structured reason a Specification is not yet runnable."""

    code: MissingDataCode
    stage: InterviewStep
    subject: str | None = None
    message: str


InterviewOutcome: TypeAlias = Literal["awaiting_response", "done"]


class InterviewSuccess(BaseModel):
    """A successful start, turn, or end operation."""

    type: Literal["success"] = "success"
    state: InterviewState
    stage: InterviewStep
    missing: list[MissingData] = Field(default_factory=list)
    outcome: InterviewOutcome


class InterviewFailure(BaseModel):
    """A typed failure with unchanged state when a safe retry state exists."""

    type: Literal["failure"] = "failure"
    code: InterviewErrorCode
    message: str
    retryable: bool
    state: InterviewState | None = None
    missing: list[MissingData] = Field(default_factory=list)
    diagnostic_state: InterviewState | None = None
    diagnostic_message: str | None = None


InterviewResult: TypeAlias = Annotated[
    InterviewSuccess | InterviewFailure,
    Field(discriminator="type"),
]


class CompileResult(BaseModel):
    """The compiled `specification.yaml` string and the Specification with assigned Task IDs."""

    model_config = ConfigDict(populate_by_name=True)

    specification_yaml: str = Field(alias="specification.yaml")
    specification: Specification


__all__ = [
    "CompileResult",
    "InterviewConnectionRequest",
    "InterviewEndRequest",
    "InterviewErrorCode",
    "InterviewFailure",
    "InterviewOutcome",
    "InterviewRequest",
    "InterviewResult",
    "InterviewStartRequest",
    "InterviewSuccess",
    "InterviewTurnRequest",
    "MissingData",
    "MissingDataCode",
]
