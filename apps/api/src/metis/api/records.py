"""The records that the store keeps, in the form that the store routes send and receive.

A Target has one Interview, one Specification, and many Experiments. The Interview record is
the web record. Its files are references (`FileRef`). The bytes of each file stay on disk in
the store.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from metis.wizard import InterviewState, InterviewStep

if TYPE_CHECKING:
    from collections.abc import Iterator

TARGET_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
"""A Target id is one path segment. The client makes it, and it is also the folder name."""

EXPERIMENT_ID = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]{0,199}$")
"""An Experiment id is the name of one Experiment folder under `experiments/execute/`."""


def file_name_identity(name: str) -> str:
    """The key that makes two file names the same name, as the web app compares them."""
    return unicodedata.normalize("NFC", name).upper().lower()


class FileRef(BaseModel):
    """One file of an Interview record. The store keeps the bytes on disk."""

    model_config = ConfigDict(extra="forbid")

    name: str
    type: str
    size: int = Field(ge=0)


class InterviewRecord(BaseModel):
    """The web record of one Interview. Its id is the Target id.

    The store validates `state` as an `InterviewState`. It keeps the transcript as opaque JSON
    and reads from it only the file references in `outbound.files`. These are the files of an
    answer that the wizard has not accepted yet. The store keeps all the files of the record in
    one folder, by name. Each file of the record has its own name. Two names that differ only
    by case are the same name.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    stage: InterviewStep
    created_at: float
    updated_at: float
    submission_revision: int | None = None
    state: InterviewState
    transcript: list[dict[str, JsonValue]]
    fixtures: list[FileRef]

    def to_json(self) -> dict[str, Any]:
        """The record as the web app sent it. An unset revision stays out."""
        unset = {"submission_revision"} if self.submission_revision is None else None
        return self.model_dump(mode="json", exclude=unset)

    def files(self) -> dict[str, FileRef]:
        """The file references of the record, by name.

        :raises ValueError: Two files of the record have the same name.
        """
        files: dict[str, FileRef] = {}
        identities: set[str] = set()
        for ref in [*self.fixtures, *self._outbound()]:
            identity = file_name_identity(ref.name)
            if identity in identities:
                raise ValueError(f"The record has two files named {ref.name}.")
            identities.add(identity)
            files[ref.name] = ref
        return files

    def _outbound(self) -> Iterator[FileRef]:
        for entry in self.transcript:
            message = entry.get("outbound")
            if isinstance(message, dict):
                yield from _FILE_REFS.validate_python(message.get("files", []))


_FILE_REFS: TypeAdapter[list[FileRef]] = TypeAdapter(list[FileRef])


class TargetSummary(BaseModel):
    """One row of the Target list."""

    id: str
    title: str
    updated_at: datetime


class TargetProblem(BaseModel):
    """A stored Interview that the store cannot read with the current version."""

    id: str
    message: str


class TargetList(BaseModel):
    """The Targets that the store can read, newest first, and the rows that it cannot read."""

    targets: list[TargetSummary]
    problems: list[TargetProblem]


class SpecificationRecord(BaseModel):
    """The Specification of a Target, and the input folder that the store writes for it."""

    target_id: str
    specification_yaml: str
    sha256: str
    input_dir: str
    """The absolute path of the folder that `metis engine simulate --input-dir` reads."""
    updated_at: datetime


class ExperimentStep(StrEnum):
    """The last engine step that the web app started for an Experiment."""

    SIMULATE = "simulate"
    EVALUATE = "evaluate"


class ExperimentSave(BaseModel):
    """The body of an Experiment save."""

    model_config = ConfigDict(extra="forbid")

    target_id: str
    step: ExperimentStep


class ExperimentRecord(BaseModel):
    """One Experiment of a Target. The phase and the progress come from the Experiment folder."""

    experiment_id: str
    target_id: str
    started_at: datetime
    step: ExperimentStep


class ExperimentList(BaseModel):
    """The Experiments of one Target, newest first."""

    experiments: list[ExperimentRecord]


def record_problem(raw: Any) -> str | None:
    """The reason that a stored record is not readable, or ``None`` when it is readable."""
    try:
        InterviewRecord.model_validate(raw).files()
    except ValueError:
        return (
            "This saved Interview cannot be read by this version of METIS. "
            "Delete it and start a new Interview."
        )
    return None


__all__ = [
    "EXPERIMENT_ID",
    "TARGET_ID",
    "ExperimentList",
    "ExperimentRecord",
    "ExperimentSave",
    "ExperimentStep",
    "FileRef",
    "InterviewRecord",
    "SpecificationRecord",
    "TargetList",
    "TargetProblem",
    "TargetSummary",
    "file_name_identity",
    "record_problem",
]
