"""Target context and the Feature, Behaviour, and Criterion hierarchy."""

from __future__ import annotations

from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, BeforeValidator, Field, StringConstraints

DescriptionT = TypeVar("DescriptionT")


class NamedNode(BaseModel, Generic[DescriptionT]):
    """A repeated specification entity with separate identity, label, and content."""

    id: str
    name: str
    description: DescriptionT


class Target(BaseModel):
    name: str
    users: str  # prose — who the target serves
    description: str  # prose — the short description of the target
    detail: str = ""  # prose — useful depth, including how the target works


def _criterion_text(value: object) -> object:
    if isinstance(value, dict) and {"given", "when", "then"} <= value.keys():
        raise ValueError(
            "This Criterion uses an older format. Replace its description with one non-empty assessment sentence. Start a new Interview for saved Interview data."
        )
    return value


CriterionDescription = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1),
    BeforeValidator(_criterion_text),
]


class Criterion(NamedNode[CriterionDescription]):
    # The id is scoped to its behaviour: AC-1-1, AC-1-2.
    # resolved by the matcher, never by the model. `None` means matching has not run yet.
    grader_fqn: str | None = None
    grader_args: dict[str, Any] = Field(default_factory=dict)


class Behaviour(NamedNode[str]):
    # the user's tick, and the only real decision in the interview. The model never writes
    # it — the path is absent from StepPermissions entirely.
    measured: bool = False
    # Keep dormant Criteria in the document when their Behaviour is not measured.
    criteria: list[Criterion] = Field(default_factory=list)


class Feature(NamedNode[str]):
    behaviours: list[Behaviour] = Field(default_factory=list)
