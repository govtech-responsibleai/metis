"""Pydantic models for the target evaluation report (report.json).

`metis insights report` validates report data through these models before writing
report.json. Only metis-insights reads them, so they stay private to this package.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from metis.core.reporting import GraderRecord

_REPORT_VERSION = 1


class ConversationTurn(BaseModel):
    turn: int
    user: str
    target: str
    errors: list[str] = Field(default_factory=list)


class Trial(BaseModel):
    task_id: str = ""
    trial_index: int = 1
    id: str
    session: str
    persona: str
    scenario: str
    stopReason: str
    message: str
    failureSource: str
    simulated_turns_completed: int
    duration: float | None = None
    attempt: int = 1
    conversation: list[ConversationTurn] = Field(default_factory=list)
    conversationProblem: str | None = None
    category: str
    features: list[str] = Field(default_factory=list)


class TrialsSummary(BaseModel):
    attempted: int
    successful: int
    rate: int | None = None
    items: list[Trial] = Field(default_factory=list)


class GraderPassRate(BaseModel):
    fail: int = 0
    rate: int | None = None
    mean_score: float | None = None
    pass_: int = Field(0, alias="pass")
    ran: int = 0
    skip: int = 0
    error: int = 0

    model_config = {"populate_by_name": True}


class TrialSuccess(BaseModel):
    rate: int | None = None
    successful: int = 0
    attempted: int = 0
    status: str | None = None


class Scores(BaseModel):
    graderPassRate: GraderPassRate
    trialSuccess: TrialSuccess


class PlanTask(BaseModel):
    scenario: str
    id: str
    personas: list[str]
    trials: int
    trialsPlanned: int
    trialsRun: int
    personasRun: list[str]
    gradersAsked: int
    gradersScored: int


class Plan(BaseModel):
    personas: list[str]
    tasks: list[PlanTask]


class AxisRow(BaseModel):
    id: str
    rate: int | None = None
    pass_: int = Field(0, alias="pass")
    fail: int = 0
    ran: int = 0
    skip: int = 0
    error: int = 0
    sessions: int = 0
    behaviours: int = 0
    graders: int = 0
    partners: int = 0
    partnerTotal: int = 0

    model_config = {"populate_by_name": True}


class CriterionBreakdownCell(BaseModel):
    rate: int | None
    n: int
    pass_: int = Field(alias="pass")
    fail: int
    skip: int
    error: int = 0

    model_config = {"populate_by_name": True}


class BlankCause(BaseModel):
    cause: str
    note: str


class EvidenceItem(BaseModel):
    task_id: str = ""
    trial_index: int = 1
    criterion_id: str = ""
    grader_fqn: str = ""
    grader_args: dict[str, Any] = Field(default_factory=dict)
    status: str
    message: str
    session: str
    run_score: float | None = None
    run_threshold: float | None = None
    run_outcome: Literal["passed", "failed", "skipped", "errored"]
    result_number: int
    outcome: Literal["passed", "failed", "skipped", "errored"]
    score: float | None = None
    persona: str | None = None
    scenario: str | None = None


class Criterion(BaseModel):
    name: str
    grader_args: dict[str, Any] = Field(default_factory=dict)
    description: str
    grader_name: str
    grader_fqn: str | None = None
    judge_models: list[str] = Field(default_factory=list)
    pass_: int = Field(0, alias="pass")
    fail: int = 0
    skip: int = 0
    error: int = 0
    rate: int | None = None
    mean_score: float | None = None
    status: str | None = None
    blank: BlankCause | None = None
    P: list[CriterionBreakdownCell | None] = Field(default_factory=list)
    S: list[CriterionBreakdownCell | None] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class Behaviour(BaseModel):
    pass_: int = Field(0, alias="pass")
    fail: int = 0
    skip: int = 0
    error: int = 0

    model_config = {"populate_by_name": True}

    label: str
    statement: str
    detail: str
    priority: bool
    criteria: list[str]
    rate: int | None = None
    mean_score: float | None = None
    status: str | None = None


class Feature(BaseModel):
    pass_: int = Field(0, alias="pass")
    fail: int = 0
    skip: int = 0
    error: int = 0

    model_config = {"populate_by_name": True}

    id: str
    name: str
    behaviours: list[str]
    rate: int | None = None
    mean_score: float | None = None
    status: str | None = None


class ResultTableColumn(BaseModel):
    grader_fqn: str | None = None
    criterion: str
    grader_name: str


class ResultTableFeature(BaseModel):
    id: str
    name: str
    columns: list[ResultTableColumn]


class TrialResult(BaseModel):
    pass_: int = Field(0, alias="pass")
    fail: int = 0
    skip: int = 0
    error: int = 0
    evaluated: int = 0
    rate: int | None = None
    mean_score: float | None = None
    status: str | None = None

    model_config = {"populate_by_name": True}


class WilsonConfidenceInterval(BaseModel):
    method: Literal["wilson"] = "wilson"
    confidence_level: float = Field(0.95, ge=0.95, le=0.95)
    lower: float = Field(ge=0, le=1)
    upper: float = Field(ge=0, le=1)


class CaseResult(TrialResult):
    confidence_interval: WilsonConfidenceInterval | None = None


class ResultTableTrial(Trial):
    results: dict[str, TrialResult] = Field(default_factory=dict)


class ResultTableRow(BaseModel):
    """One test case: the grader runs of all its trials, pooled per criterion."""

    task_id: str
    persona: str
    scenario: str
    results: dict[str, CaseResult] = Field(default_factory=dict)
    trials: list[ResultTableTrial] = Field(default_factory=list)


class ResultTable(BaseModel):
    features: list[ResultTableFeature]
    rows: list[ResultTableRow]


class UnmappedGrader(BaseModel):
    grader_fqn: str
    records: list[GraderRecord] = Field(default_factory=list)
    criterion_id: str
    grader_name: str
    pass_: int = Field(0, alias="pass")
    fail: int = 0
    skip: int = 0
    error: int = 0
    why: str = ""

    model_config = {"populate_by_name": True}


class Report(BaseModel):
    """Top-level model for report.json.

    This is the contract downstream consumers depend on.
    """

    schema_version: Literal[1] = _REPORT_VERSION
    target: str
    run: str
    date: str
    sessions: int
    results: int
    latency: float | None = None
    timings: dict[str, Any] = Field(default_factory=dict)
    trials: TrialsSummary
    scores: Scores
    plan: Plan
    personas: list[str]
    scenarios: list[str]
    passRateTarget: int
    names: dict[str, dict[str, str]]
    describe: dict[str, dict[str, str]]
    axes: dict[str, list[AxisRow]]
    behaviourTotal: int
    personasRun: list[str]
    scenariosRun: list[str]
    features: list[Feature]
    behaviours: dict[str, Behaviour]
    criteria: dict[str, Criterion]
    resultTable: ResultTable
    unmapped: list[UnmappedGrader]
    unresolved: list[str]

    model_config = {"populate_by_name": True}
