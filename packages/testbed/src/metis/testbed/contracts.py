"""Saved contracts for Wizard specification evaluations."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from metis.core.specification import Specification


class InteractionMode(StrEnum):
    """How a user or agent moves through a Wizard Interview."""

    ONE_SHOT = "one-shot"


class CaseStatus(StrEnum):
    """The outcome of one configured Test Case."""

    SCORED = "scored"
    INCOMPLETE = "incomplete"
    INPUT_MISSING = "input_missing"
    FAILED = "failed"


class EvaluationProgress(BaseModel):
    """One progress update from a running evaluation."""

    case_id: str
    completed: int
    total: int
    phase: str


class EvaluationConfig(BaseModel):
    """The configured Wizard Test Cases that one command evaluates."""

    model_config = ConfigDict(extra="forbid")

    id: str
    version: int
    component: Literal["wizard"]
    cases: list[str] = Field(min_length=1)


class CaseConfig(BaseModel):
    """The files needed to evaluate one Wizard use case."""

    model_config = ConfigDict(extra="allow")

    id: str
    component: Literal["wizard"]
    inputs: list[str]
    expected_output: str


class WizardInput(BaseModel):
    """The opening evidence supplied to a Wizard Target."""

    case_id: str
    description: str
    documents: list[tuple[str, str]] = Field(default_factory=list)


class WizardState(BaseModel):
    """One system-neutral observation from a Wizard Target."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    raw: Any = Field(exclude=True)
    specification: Specification
    outcome: str
    stage: str
    pending: dict[str, JsonValue] | None = None
    raw_output: JsonValue | None = None


class InteractionEvent(BaseModel):
    """One operation retained from an interaction with a Wizard Target."""

    operation: str
    outcome: str
    stage: str
    request: dict[str, JsonValue] | None = None
    response: JsonValue | None = None


class Candidate(BaseModel):
    """A generated Specification and the interaction that produced it."""

    specification: Specification
    outcome: str
    events: list[InteractionEvent]
    raw_output: JsonValue | None = None


class WizardTarget(Protocol):
    """A Wizard implementation that an interaction driver can operate."""

    name: str

    def start(self, evidence: WizardInput) -> WizardState: ...

    def respond(self, state: WizardState, response: object) -> WizardState: ...

    def end(self, state: WizardState) -> WizardState: ...


class InteractionDriver(Protocol):
    """A policy for moving through a Wizard Target."""

    mode: InteractionMode

    def run(self, target: WizardTarget, evidence: WizardInput) -> Candidate: ...


class Similarity(Protocol):
    """Calculate pairwise text similarity on a zero-to-one scale."""

    def matrix(self, left: list[str], right: list[str]) -> list[list[float]]: ...


class ItemMatch(BaseModel):
    """One generated item aligned with one reference item."""

    reference_id: str
    generated_id: str
    similarity: float = Field(ge=0.0, le=1.0)
    details: dict[str, float | None] = Field(default_factory=dict)


class LevelScore(BaseModel):
    """Similarity and structural differences for one curation level."""

    similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    precision: float | None = Field(default=None, ge=0.0, le=1.0)
    reference_count: int = Field(ge=0)
    generated_count: int = Field(ge=0)
    matches: list[ItemMatch] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    additional: list[str] = Field(default_factory=list)


class SpecificationScores(BaseModel):
    """The four curation levels required by the Wizard evaluation issue."""

    features: LevelScore
    behaviours: LevelScore
    criteria: LevelScore
    graders: LevelScore
    tasks: LevelScore


class BehaviourNNSummary(BaseModel):
    """Experimental overlap scores for the two sets, with their sizes."""

    reference_count: int = Field(ge=0)
    generated_count: int = Field(ge=0)
    reference_mean_nn: float | None = Field(default=None, ge=0.0, le=1.0)
    generated_mean_nn: float | None = Field(default=None, ge=0.0, le=1.0)


class CaseResult(BaseModel):
    """The retained result for one configured Test Case."""

    case_id: str
    status: CaseStatus
    lifecycle_outcome: str | None = None
    completed: bool = False
    failure: dict[str, JsonValue] | None = None
    error: str | None = None
    scores: SpecificationScores | None = None
    behaviour_nn: dict[str, BehaviourNNSummary] = Field(default_factory=dict)
    generated_specification: str | None = None
    score_report: str | None = None
    events: list[InteractionEvent] = Field(default_factory=list)
    raw_output: JsonValue | None = None


class AggregateLevel(BaseModel):
    """Equal-case and item-weighted similarity across scored Test Cases."""

    case_average: float | None = Field(default=None, ge=0.0, le=1.0)
    item_weighted: float | None = Field(default=None, ge=0.0, le=1.0)
    scored_cases: int = Field(ge=0)


class AggregateScores(BaseModel):
    features: AggregateLevel
    behaviours: AggregateLevel
    criteria: AggregateLevel
    graders: AggregateLevel
    tasks: AggregateLevel


class EvaluationRecord(BaseModel):
    """One immutable execution of the configured Wizard evaluation."""

    id: str
    created_at: datetime
    target: str
    target_version: str
    interaction: InteractionMode
    config: str
    config_version: int
    cases: list[CaseResult]
    aggregate: AggregateScores


class EvaluationRequest(BaseModel):
    """The small external interface for running the full evaluation."""

    config_path: Path
    results_root: Path
    target_version: str


class VersionComparison(BaseModel):
    """Score changes between two saved Target versions."""

    target: str
    older_version: str
    newer_version: str
    older_id: str
    newer_id: str
    changes: dict[str, float | None]
    case_changes: dict[str, dict[str, float | None]]


__all__ = [
    "AggregateLevel",
    "AggregateScores",
    "BehaviourNNSummary",
    "Candidate",
    "CaseConfig",
    "CaseResult",
    "CaseStatus",
    "EvaluationConfig",
    "EvaluationRecord",
    "EvaluationRequest",
    "InteractionDriver",
    "InteractionEvent",
    "InteractionMode",
    "ItemMatch",
    "LevelScore",
    "Similarity",
    "SpecificationScores",
    "VersionComparison",
    "WizardInput",
    "WizardState",
    "WizardTarget",
]
