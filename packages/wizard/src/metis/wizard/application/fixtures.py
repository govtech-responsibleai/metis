"""Validation and filesystem storage for experiment fixture files.

The wizard specification stores fixture *names*. This module owns the bytes that those names resolve to
at the web boundary, together with the small policy that keeps names portable and uploads bounded.
"""

from __future__ import annotations

import filecmp
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

from pydantic import BaseModel, Field

from metis.wizard.domain.documents import (
    FIXTURE_DOCUMENT_EXTENSIONS,
    MAX_DOCUMENT_BYTES,
    MAX_DOCUMENTS,
)
from metis.wizard.domain.documents import (
    fixture_name_identity as _identity,
)
from metis.wizard.domain.documents import (
    normalize_fixture_name as _normalize_fixture_name,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence


class FixtureError(ValueError):
    """A user-correctable fixture policy or storage error."""


def normalize_fixture_name(name: str) -> str:
    """Keep domain validation errors inside the application error contract."""
    try:
        return _normalize_fixture_name(name)
    except ValueError as exc:
        raise FixtureError(str(exc)) from exc


class FixtureMetadata(BaseModel):
    """Metadata exposed to a door; file bytes never cross this boundary."""

    name: str
    size: int = Field(ge=0)


@dataclass(frozen=True)
class FixtureCandidate:
    """A streamed upload's name and measured size."""

    name: str
    size: int


def normalize_upload_name(name: str) -> str:
    """Normalize and validate an uploaded file name, including its extension."""

    normalized = normalize_fixture_name(name)
    extension = Path(normalized).suffix.lower().removeprefix(".")
    if extension not in FIXTURE_DOCUMENT_EXTENSIONS:
        accepted = ", ".join(sorted(FIXTURE_DOCUMENT_EXTENSIONS))
        raise FixtureError(
            f"Unsupported fixture type; accepted extensions: {accepted}."
        )
    return normalized


def validate_batch(
    candidates: Sequence[FixtureCandidate],
    existing: Iterable[FixtureMetadata] = (),
) -> list[FixtureCandidate]:
    """Validate an upload batch against an existing library without mutating it."""

    existing_items = list(existing)
    existing_keys = {
        _identity(normalize_fixture_name(item.name)) for item in existing_items
    }
    incoming: list[FixtureCandidate] = []
    incoming_keys: set[str] = set()

    for candidate in candidates:
        if candidate.size < 0:
            raise FixtureError("Fixture sizes cannot be negative.")
        name = normalize_upload_name(candidate.name)
        key = _identity(name)
        if key in existing_keys or key in incoming_keys:
            raise FixtureError(f"A fixture named '{name}' already exists.")
        incoming_keys.add(key)
        incoming.append(FixtureCandidate(name=name, size=candidate.size))

    if len(existing_items) + len(incoming) > MAX_DOCUMENTS:
        raise FixtureError(
            f"An experiment can contain at most {MAX_DOCUMENTS} fixture files."
        )
    total = sum(item.size for item in existing_items) + sum(
        item.size for item in incoming
    )
    if total > MAX_DOCUMENT_BYTES:
        raise FixtureError(
            f"Fixture files can use at most {MAX_DOCUMENT_BYTES:,} bytes in total."
        )
    return incoming


class FixtureLibrary:
    """A directory of fixture bytes with metadata derived from its files."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def list(self) -> list[FixtureMetadata]:
        if not self.root.is_dir():
            return []
        entries: list[FixtureMetadata] = []
        for path in sorted(self.root.iterdir(), key=lambda item: item.name):
            if path.is_symlink() or not path.is_file():
                continue
            name = normalize_upload_name(path.name)
            entries.append(FixtureMetadata(name=name, size=path.stat().st_size))
        return entries

    def path_for(self, name: str) -> Path:
        normalized = normalize_fixture_name(name)
        path = self.root / normalized
        try:
            path.resolve().relative_to(self.root.resolve())
        except ValueError as exc:
            raise FixtureError("Fixture path escapes its library.") from exc
        if not path.is_file() or path.is_symlink():
            raise FixtureError(f"Fixture '{normalized}' is missing.")
        return path

    def upload(self, streams: Sequence[tuple[str, BinaryIO]]) -> list[FixtureMetadata]:
        """Add a batch atomically, streaming each source to a staging directory."""

        self.root.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".fixtures-", dir=self.root.parent))
        try:
            existing_items = self.list()
            existing_by_key = {_identity(item.name): item for item in existing_items}
            staged: list[FixtureCandidate] = []
            incoming_keys: set[str] = set()
            for raw_name, source in streams:
                # Validate the name before creating its staging file. The normalized name is the
                # only name that can reach either the staging directory or the durable library.
                name = normalize_upload_name(raw_name)
                key = _identity(name)
                if key in incoming_keys:
                    raise FixtureError(f"A fixture named '{name}' already exists.")
                incoming_keys.add(key)
                destination = staging / name
                size = 0
                with destination.open("wb") as target:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        if not isinstance(chunk, bytes):
                            raise FixtureError(
                                "Fixture uploads must provide binary content."
                            )
                        size += len(chunk)
                        if size > MAX_DOCUMENT_BYTES:
                            raise FixtureError(
                                f"Fixture files can use at most {MAX_DOCUMENT_BYTES:,} bytes in total."
                            )
                        target.write(chunk)
                staged.append(FixtureCandidate(name=name, size=size))

            # Uploading the same bytes again is idempotent. This matters when several scenarios
            # use one fixture and the user uploads it from each scenario's shared control. A
            # different payload under the same normalized name remains a hard collision.
            reusable: dict[str, FixtureMetadata] = {}
            new_staged: list[FixtureCandidate] = []
            for item in staged:
                key = _identity(item.name)
                existing = existing_by_key.get(key)
                if existing is None:
                    new_staged.append(item)
                    continue
                if not filecmp.cmp(
                    staging / item.name,
                    self.root / existing.name,
                    shallow=False,
                ):
                    raise FixtureError(
                        f"A fixture named '{item.name}' already exists with different content."
                    )
                reusable[key] = existing

            accepted = validate_batch(new_staged, existing_items)
            self.root.mkdir(parents=True, exist_ok=True)
            # Re-check immediately before the moves. This keeps a concurrent upload from being
            # silently overwritten even though the normal web path is single-process.
            current = {_identity(item.name): item for item in self.list()}
            for item in accepted:
                existing = current.get(_identity(item.name))
                if existing is not None:
                    if filecmp.cmp(
                        staging / item.name,
                        self.root / existing.name,
                        shallow=False,
                    ):
                        reusable[_identity(item.name)] = existing
                        continue
                    raise FixtureError(
                        f"A fixture named '{item.name}' already exists with different content."
                    )
            for item in accepted:
                if _identity(item.name) in reusable:
                    continue
                os.replace(staging / item.name, self.root / item.name)
            return [
                reusable.get(
                    _identity(item.name),
                    FixtureMetadata(name=item.name, size=item.size),
                )
                for item in staged
            ]
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def delete(self, name: str, *, referenced: Iterable[str] = ()) -> None:
        normalized = normalize_fixture_name(name)
        references = {normalize_fixture_name(value) for value in referenced}
        if normalized in references:
            raise FixtureError(
                f"Fixture '{normalized}' is still referenced by a scenario."
            )
        path = self.path_for(normalized)
        path.unlink()
