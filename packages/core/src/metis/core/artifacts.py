"""The ``Artifact`` domain model and its path resolver.

An ``Artifact`` is a file crossing the persona<->target boundary — uploaded
by the persona (``source="fixture"``) or produced by the target
(``source="target"``). ``state`` (#351) says what METIS actually knows about
it: ``"received"`` means the bytes are on disk at ``path``; ``"unfetched"``
means the target has this file (an ``external_id`` was observed) but METIS
failed to download it, which is retryable; ``"unavailable"`` means there is
nothing to retry.

Its ``path`` is a POSIX-style path relative to the experiment root — the
directory created by ``metis engine simulate`` (or resumed into), containing
``inputs/`` and ``outputs/trials/``. Storing a relative path keeps experiment output
directories portable: they can be copied, zipped, or moved without breaking
artifact references baked into ``record.json``.
"""

from __future__ import annotations

import mimetypes
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Literal, Self
from uuid import uuid4

from pydantic import BaseModel, Field, computed_field, model_validator

if TYPE_CHECKING:
    from pathlib import Path

_MEDIA_TYPES = {".md": "text/markdown", ".markdown": "text/markdown"}
"""Extensions that the standard library's table lacks before Python 3.12."""


def _media_type_from_extension(name: str) -> str | None:
    """The MIME type that the extension of ``name`` maps to, or None for an unknown one."""
    suffix = PurePosixPath(name).suffix.lower()
    return _MEDIA_TYPES.get(suffix) or mimetypes.guess_type(name)[0]


def media_type(name: str) -> str:
    """The MIME type a file is sent with: the type of its extension, or octet-stream."""
    return _media_type_from_extension(name) or "application/octet-stream"


class Artifact(BaseModel):
    """A file crossing the persona<->target boundary.

    ``state`` is required, with no default: a construction site that
    forgets to set it fails loudly instead of silently claiming the file
    was received. The validator below is one-directional — a path-bearing
    artifact is not required to be ``"received"`` (the Playwright runner
    legitimately holds a ``path`` mid-capture before state is decided) —
    but ``"received"`` always requires a ``path``.

    ``id`` identifies this record; ``external_id`` identifies the *file* on the
    target's side, which is what makes a completed run re-checkable against the
    target and what lets a collector dedupe by identity rather than filename.

    ``at_simulated_turn`` is a simulated turn, never a recorded turn.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    source: Literal["fixture", "target"] = "target"
    state: Literal["received", "unfetched", "unavailable"]
    #: The target's own identifier for this file (a ``fileId``, for example).
    #: Target-agnostic by name because ``metis-core`` must not know about any one target.
    #: ``None`` for runners with no such identifier, such as the browser runner.
    #:
    #: **Must name exactly one file within its ``source``, or leave it**
    #: ``None``. Consumers treat two records that share a ``source`` and a
    #: non-``None`` ``external_id`` as one file and keep only one of them, so an
    #: id a target reuses across genuinely different files makes those files
    #: collapse into a single record: they vanish from the run, and from the list
    #: the simulated user is told is every file it received. Nothing enforces
    #: this — uniqueness is a property of the set, not of any one record a
    #: validator can see — so it is a promise each runner makes. A runner that
    #: cannot make it must leave this ``None``, which is always safe: an absent
    #: id costs deduplication, never a file. Reusing one id across a target's
    #: *revisions* of a file is equally a violation; a revision is a different
    #: file and needs its own id, or the run cannot show that anything changed.
    external_id: str | None = None
    path: str | None = None
    #: The **simulated turn** (counted from 1 by METIS's own simulation loop) in
    #: which the file was uploaded or received. It is not a recorded turn: METIS
    #: does not know which of the target's traces produced a file, so this
    #: number must not be used to index into the session's traces or to match a
    #: grader's ``turn:N`` label. See ``GLOSSARY.md``.
    at_simulated_turn: int | None = None
    content_description: str | None = None
    state_description: str | None = None
    digest: str | None = None
    hash_algorithm: str | None = None

    @model_validator(mode="after")
    def _received_requires_path(self) -> Self:
        if self.state == "received" and self.path is None:
            raise ValueError(
                "an Artifact with state='received' MUST carry a non-None `path`"
            )
        return self

    @computed_field
    @property
    def media_type(self) -> str | None:
        """The MIME type of the filename's extension, or of the path's when the name has none.

        None unless state=="received": a file METIS never got has no bytes,
        so a MIME type would misrepresent it as one that exists.
        """
        if self.state != "received":
            return None
        return _media_type_from_extension(self.name) or (
            _media_type_from_extension(self.path) if self.path else None
        )


def resolve_artifact_path(experiment_root: Path, path: str | None) -> Path | None:
    """Resolve an ``Artifact.path`` against the experiment root.

    Returns None for a falsy path (covers both the unset and empty-string
    cases) rather than joining onto an empty relative path.
    """
    if not path:
        return None
    return experiment_root / path
