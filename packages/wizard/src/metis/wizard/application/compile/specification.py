"""Build an engine-ready ZIP from compiled YAML and a fixture directory."""

from __future__ import annotations

import io
import tempfile
import zipfile
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

from metis.wizard.application import export_layout
from metis.wizard.application.fixtures import (
    FixtureCandidate,
    FixtureError,
    normalize_fixture_name,
    normalize_upload_name,
    validate_batch,
)
from metis.wizard.domain.documents import MAX_DOCUMENT_BYTES, MAX_DOCUMENTS

from .experiment import to_yaml

if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import BinaryIO


class SpecificationArchive(BaseModel):
    """A portable export and its download filename."""

    model_config = ConfigDict(frozen=True)

    content: bytes
    filename: str


class SpecificationError(ValueError):
    """The YAML and fixture directory cannot form a runnable specification."""


@dataclass(frozen=True)
class SpecificationFixture:
    """One request-scoped fixture stream supplied to the in-memory packager."""

    name: str
    stream: BinaryIO


def _referenced_names(document: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for scenario in document.get("tasks", []):
        for raw_name in scenario.get("fixtures", []) or []:
            try:
                names.add(normalize_fixture_name(raw_name))
            except FixtureError as exc:
                raise SpecificationError(str(exc)) from exc
    return names


def write_specification(
    document: dict[str, Any],
    fixture_dir: Path,
    target: Path,
) -> Path:
    """Write the shared export layout into a ZIP archive."""

    fixture_root = Path(fixture_dir)
    destination = Path(target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with ExitStack() as stack:
            fixtures: list[SpecificationFixture] = []
            if fixture_root.exists():
                if not fixture_root.is_dir():
                    raise SpecificationError("The fixture library is not a directory.")
                for path in fixture_root.iterdir():
                    if path.is_symlink() or not path.is_file():
                        continue
                    fixtures.append(
                        SpecificationFixture(
                            path.name,
                            stack.enter_context(path.open("rb")),
                        )
                    )
            destination.write_bytes(
                build_specification_archive(document, fixtures).content
            )
    except OSError as exc:
        raise SpecificationError(f"Could not create specification.zip: {exc}") from exc
    return destination


def build_specification_archive(
    document: dict[str, Any],
    fixtures: Iterable[SpecificationFixture],
    *,
    interview_state_json: str | None = None,
    target_binding_yaml: str | None = None,
) -> SpecificationArchive:
    """Build a complete specification ZIP from request-scoped fixture streams.

    `target_binding_yaml` is written next to `specification.yaml` when the export has a target
    connection.

    The caller owns the input streams. This function validates every filename before it reads any
    body, reads at most one bounded chunk beyond the total fixture limit, and never writes a fixture
    or archive to the filesystem.
    """

    items = _bounded_fixture_list(fixtures)
    names = _validate_fixture_names(items)
    normalized: dict[str, bytes] = {}
    candidates: list[FixtureCandidate] = []
    total_size = 0
    for fixture, name in zip(items, names, strict=True):
        content, total_size = _read_fixture_stream(fixture.stream, total_size)
        normalized[name] = content
        candidates.append(FixtureCandidate(name=name, size=len(content)))

    try:
        validate_batch(candidates)
    except FixtureError as exc:
        raise SpecificationError(str(exc)) from exc

    missing = sorted(_referenced_names(document) - normalized.keys())
    if missing:
        joined = ", ".join(missing)
        raise SpecificationError(f"Missing fixture file(s): {joined}.")

    root = export_layout.experiment_name(
        "interview" if interview_state_json is not None else "manual"
    )
    output = io.BytesIO()
    try:
        with zipfile.ZipFile(
            output, mode="w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
        ) as archive:
            archive.writestr(f"{root}/{export_layout.INPUTS}/", b"")
            if interview_state_json is not None:
                archive.writestr(
                    f"{root}/{export_layout.INTERVIEW_STATE}", interview_state_json
                )
            archive.writestr(f"{root}/{export_layout.SPECIFICATION}", to_yaml(document))
            if target_binding_yaml is not None:
                archive.writestr(
                    f"{root}/{export_layout.TARGET_BINDING}", target_binding_yaml
                )
            archive.writestr(f"{root}/{export_layout.FIXTURES}/", b"")
            for name in sorted(normalized):
                archive.writestr(
                    f"{root}/{export_layout.FIXTURES / name}", normalized[name]
                )
    except (OSError, zipfile.BadZipFile) as exc:
        raise SpecificationError(f"Could not create specification.zip: {exc}") from exc
    return SpecificationArchive(content=output.getvalue(), filename=f"{root}.zip")


def _bounded_fixture_list(
    fixtures: Iterable[SpecificationFixture],
) -> list[SpecificationFixture]:
    """Copy fixture descriptors and reject excess parts before reading their streams."""

    items: list[SpecificationFixture] = []
    for fixture in fixtures:
        if len(items) >= MAX_DOCUMENTS:
            raise SpecificationError(
                f"An experiment can contain at most {MAX_DOCUMENTS} fixture files."
            )
        items.append(fixture)
    return items


def _validate_fixture_names(
    fixtures: list[SpecificationFixture],
) -> list[str]:
    """Validate names and duplicate identities before consuming any fixture body."""

    names: list[str] = []
    identities: set[str] = set()
    for fixture in fixtures:
        try:
            name = normalize_upload_name(fixture.name)
        except FixtureError as exc:
            raise SpecificationError(str(exc)) from exc
        identity = name.casefold()
        if identity in identities:
            raise SpecificationError(f"A fixture named '{name}' already exists.")
        identities.add(identity)
        names.append(name)
    return names


def _read_fixture_stream(
    stream: BinaryIO,
    total_size: int,
) -> tuple[bytes, int]:
    """Read one fixture in bounded chunks and enforce the wizard total-size limit."""

    output = io.BytesIO()
    read = getattr(stream, "read", None)
    if not callable(read):
        raise SpecificationError("Fixture content must be a binary stream.")
    while True:
        remaining = MAX_DOCUMENT_BYTES - total_size
        try:
            chunk = read(min(1024 * 1024, remaining + 1))
        except OSError as exc:
            raise SpecificationError("Could not read fixture content.") from exc
        if not isinstance(chunk, bytes):
            raise SpecificationError("Fixture content must be binary bytes.")
        if len(chunk) > remaining:
            raise SpecificationError(
                f"Fixture files can use at most {MAX_DOCUMENT_BYTES:,} bytes in total."
            )
        if not chunk:
            return output.getvalue(), total_size
        output.write(chunk)
        total_size += len(chunk)


def temporary_specification_directory(prefix: str = "metis-specification-") -> Path:
    """Create a caller-owned temporary directory for a response-scoped specification."""

    return Path(tempfile.mkdtemp(prefix=prefix))
