"""Shared definitions for judgment forms: what the judge returns for one assessment.

The judge replies with the form's ``response_model``: a status, a score and a reason. A
``not_applicable`` reply means the event that the criterion looks for did not happen, and the
grader records it as an errored result with the judge's reason.
"""

from dataclasses import dataclass
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from metis.library.taxonomy import JudgmentForm
from metis.library.text import NonEmptyText


class BinaryJudgment(BaseModel):
    """A binary assessment, or ``not_applicable`` when the criterion does not apply."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["scored", "not_applicable"]
    score: float | None = Field(strict=True)
    reason: NonEmptyText

    @model_validator(mode="after")
    def _check_score(self) -> Self:
        if self.status == "scored" and self.score not in (0.0, 1.0):
            raise ValueError("A scored result needs a binary score of 0 or 1.")
        if self.status == "not_applicable" and self.score is not None:
            raise ValueError("A not_applicable result needs a null score.")
        return self


@dataclass(frozen=True)
class JudgmentFormDefinition:
    """Shared instructions and validation for one judgment form."""

    output_instructions: str
    response_model: type[BaseModel]


class ScalarJudgment(BaseModel):
    """A score from zero to one, or an assessment that does not apply."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["scored", "not_applicable"]
    score: float | None = Field(strict=True, ge=0, le=1, allow_inf_nan=False)
    reason: NonEmptyText

    @model_validator(mode="after")
    def _check_score(self) -> Self:
        if (self.status == "scored") != (self.score is not None):
            raise ValueError("Only a scored result can have a score.")
        return self


JUDGMENT_FORM_DEFINITIONS: dict[JudgmentForm, JudgmentFormDefinition] = {
    JudgmentForm.SCALAR: JudgmentFormDefinition(
        output_instructions=(
            "Return status scored and a score from 0 to 1. A higher score means the "
            "evidence satisfies more of the criterion. Return status not_applicable "
            "and score null if the event that the criterion requires did not occur. "
            "Give a non-empty reason."
        ),
        response_model=ScalarJudgment,
    ),
    JudgmentForm.BINARY: JudgmentFormDefinition(
        output_instructions=(
            "Return status scored and score 1 if the evidence satisfies the criterion, "
            "or score 0 if it does not. Return status not_applicable and score null only "
            "if the event that the criterion looks for did not happen in the evidence. "
            "Give a non-empty reason grounded in the observations."
        ),
        response_model=BinaryJudgment,
    ),
}
