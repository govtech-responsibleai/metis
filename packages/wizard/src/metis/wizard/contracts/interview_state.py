"""The resumable control data of one interview — client-held, not package-owned.

`InterviewState` is a plain value. `handle_interview` (in the application layer) takes one
operation, applies it, and returns the next value. Nothing here reads or writes a file: a client
that wants to keep the interview between requests serializes this model to JSON and sends it back
on the next operation, so a CLI and a stateless HTTP server rehydrate mid-conversation the same way.

It carries only what the next operation needs: the Specification being built, the user-owned Interview
context, the two explicit user decisions (`behaviours_confirmed`, `confirmed`), the bounded
clarification history, the authorship bookkeeping, and at most one pending request. Where the
interview *is* — its stage — is not stored: it is derived from this evidence, or read from the
pending request's own `stage`. See `application.turn.derive_stage`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from metis.wizard.contracts.capabilities import CapabilityId
from metis.wizard.contracts.connection import TargetConnection
from metis.wizard.contracts.conversation import AnyRequest, FormRequest
from metis.wizard.contracts.documents import (
    InterviewDocument,
    validate_interview_documents,
)

# `specification` is a Pydantic field, so `Specification` must be a runtime import — Pydantic
# resolves the annotation at runtime and a TYPE_CHECKING-only import leaves InterviewState
# "not fully defined". See AGENTS.md — Coding Conventions.
from metis.wizard.domain.permissions import InterviewStep
from metis.wizard.domain.specification import Specification

# The most recent clarification messages kept for model context. Older messages are trimmed after each
# accepted operation: they are prose the model no longer needs, not a display transcript a door
# must keep. A door that wants the full transcript keeps its own record outside this state.
HISTORY_LIMIT = 12


class InterviewMessage(BaseModel):
    """One message of the clarification history, from the user or the interviewer.

    An Interview turn adds at most one user message and one assistant message.
    """

    role: Literal["user", "assistant"]
    text: str


class Perspective(StrEnum):
    """The point of view from which the user answers the Interview."""

    END_USER = "end_user"
    ENGINEER = "engineer"
    COMPLIANCE = "compliance"
    SECURITY = "security"


class CapabilityConfidence(StrEnum):
    """How complete the user's known-capability selection is."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CapabilityEvidence(BaseModel):
    """User-owned capability evidence that travels with an Interview."""

    model_config = ConfigDict(extra="forbid")

    known_capability_ids: list[CapabilityId]
    confidence: CapabilityConfidence

    @model_validator(mode="after")
    def _reject_duplicate_capabilities(self) -> CapabilityEvidence:
        if len(self.known_capability_ids) != len(set(self.known_capability_ids)):
            raise ValueError("known_capability_ids must not contain duplicates")
        return self


class InterviewContext(BaseModel):
    """User-owned context that travels with an Interview but is not Specification data."""

    # a rejected binding value can be a pasted secret, so validation errors never repeat input
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    perspective: Perspective = Perspective.END_USER
    capability_evidence: CapabilityEvidence | None = None
    opening_description: str = ""
    documents: list[InterviewDocument] = Field(default_factory=list)
    # How the engine reaches the target, in run mode. It is None in spec-only mode and is then
    # left out of the JSON, so a spec-only state is the same as before. Prompts never read it.
    connection: TargetConnection | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @property
    def document_names(self) -> list[str]:
        """Available originals, derived without adding a field to API state."""
        return [document.name for document in self.documents]

    @model_validator(mode="after")
    def _validate_documents(self) -> InterviewContext:
        validate_interview_documents(self.documents)
        return self


class InterviewState(BaseModel):
    """One client-held value, serialized to JSON between turns.

    There is no `id`, `step`, resolved-request transcript, or file method. The pending request is
    the only structured request, and it carries its own stage; the stage is not duplicated here.
    """

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    specification: Specification
    # The user's point of view for the opening interview steps. This is deliberately outside
    # Specification: it seeds the interview but is not part of the finished evaluation artifact.
    context: InterviewContext
    # The measurement-scope lock. The combined Behaviour screen asks the user to pick the
    # behaviours worth measuring; its Continue sets this true. It is not a "the user saw the
    # screen" receipt — Criteria generation reads the measured subset it locks in, and any later
    # change to the Behaviour list or its measured selection clears it. There is deliberately no
    # `criteria_confirmed` or `personas_confirmed`; only the measured scope needs an explicit lock.
    behaviours_confirmed: bool = False
    # The final lock, set only by Continue on a ready Test Case screen or a successful finish. Any
    # accepted Specification mutation clears it, so an earlier approval can never sign off new content.
    confirmed: bool = False
    history: list[InterviewMessage] = Field(
        default_factory=list, max_length=HISTORY_LIMIT
    )
    # The latest drafting or chat message for each review step. A screen shows it when the user
    # comes back to that step, in place of the neutral default prompt.
    step_messages: dict[InterviewStep, str] = Field(default_factory=dict)
    # These sets belong to the interview, not to the portable Specification artifact.
    user_typed: set[str] = Field(default_factory=set)
    # Test Cases that the user cleared on the Test Case review. They stay in the Specification
    # for editing, but readiness, the totals and the export ignore them. This is Interview
    # state, so the shared Specification schema does not change.
    excluded_tasks: set[str] = Field(default_factory=set)
    issued_ids: set[str] = Field(default_factory=set)
    # The one live screen, or None between the finish and a fresh start. It carries its own
    # `request_id` and `stage`; the state stores neither separately.
    pending: AnyRequest | None = None

    @field_validator("pending", mode="before")
    @classmethod
    def _load_older_review_shapes(cls, value: object) -> object:
        """Read a saved pending request from before the current component shapes.

        A `disclosure` component (a label and text items) is now a `details` component. The
        rule is the same as the browser storage upgrade, so a saved Interview resumes in both.
        """
        return _review_shape(value)

    @model_validator(mode="after")
    def _current_form_format(self) -> InterviewState:
        if isinstance(self.pending, FormRequest) and {"given", "when", "then"} <= {
            field.id for field in self.pending.fields
        }:
            raise ValueError(
                "This saved Interview uses an older Criterion format. Start a new Interview to continue."
            )
        return self

    @model_validator(mode="after")
    def _pending_has_turn_metadata(self) -> InterviewState:
        """Reject a client state that cannot bind its next response safely."""
        if self.pending is not None:
            if not self.pending.request_id:
                raise ValueError("pending.request_id is required")
            if self.pending.stage is None:
                raise ValueError("pending.stage is required")
        return self


def _review_shape(value: object) -> object:
    if isinstance(value, list):
        return [_review_shape(item) for item in value]
    if not isinstance(value, dict):
        return value
    if value.get("type") == "disclosure":
        label = value.get("label")
        items = value.get("items")
        return {
            "type": "details",
            "title": label if isinstance(label, str) else "Details",
            "muted": True,
            "expanded": False,
            "components": items if isinstance(items, list) else [],
        }
    # Free text and field values are content, not request shapes.
    return {
        key: entry if key in ("value", "text") else _review_shape(entry)
        for key, entry in value.items()
    }
