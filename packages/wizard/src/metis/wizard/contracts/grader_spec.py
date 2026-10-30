"""What the wizard reads from the grader library.

Design-time metadata only. The wizard never instantiates a grader and never runs one — which
is also why the catalogue is built from class names and docstrings rather than from
instances: a grader's parameters are its `args_model` fields, which are read from the class.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from metis.library.taxonomy import Dimension, GraderTaxonomy


class GraderParam(BaseModel):
    name: str
    type: str
    default: Any = None
    required: bool = False


class GraderSettingKind(StrEnum):
    """How a client edits the value of a grader setting."""

    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    TEXT = "text"
    LIST = "list"
    CHOICE = "choice"
    OBJECT = "object"


class GraderSetting(BaseModel):
    """One key that a Criterion can set under ``grader_args``."""

    name: str
    kind: GraderSettingKind
    required: bool = False
    # The JSON value the grader uses when the key is not set. None when the setting is required
    # or has no default.
    default: Any = None
    # The allowed values of a CHOICE setting.
    choices: list[str] = Field(default_factory=list)
    # True when every grader has the setting, because ``GraderArgs`` declares it.
    base: bool
    description: str | None = None


class GraderSpec(BaseModel):
    fqn: str  # "metis.library.graders.demo.DemoTraceBudgetGrader"
    name: str  # "Turn budget" — what the user sees
    description: str
    # args_model fields seed the Criterion parameters for user review.
    params: list[GraderParam] = Field(default_factory=list)
    # The grader takes its instructions from the criterion description, so it fits any
    # criterion and the matcher never offers it.
    uses_criterion_description: bool = False
    # The taxonomy values the grader declares. None when the grader declares none.
    taxonomy: GraderTaxonomy | None = None
    # Every key a Criterion can set: the base settings, then the grader's own settings.
    settings: list[GraderSetting] = Field(default_factory=list)


class GraderSummary(BaseModel):
    """The small, stable grader shape exposed to presentation clients."""

    fqn: str
    name: str
    description: str
    uses_criterion_description: bool = False
    settings: list[GraderSetting] = Field(default_factory=list)
    taxonomy: GraderTaxonomy | None = None
    # The Dimension of the taxonomy measure. None when the grader has no fixed measure.
    dimension: Dimension | None = None
