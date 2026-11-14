"""The input folder of a Specification, in the layout that `metis engine simulate` reads.

The folder holds `specification.yaml`, `fixtures/`, and `target-binding.yaml` when the Interview
has a target connection. The wizard packager builds these files. This module takes the files
under `outputs/` in the package archive, the same files that `metis wizard init` writes.

A new folder replaces the old one in two renames. The staged folder and the old folder are next
to the input folder. Their names add `.tmp-` or `.old-` and an id to its name. After a crash
between the renames, `recover` keeps the input folder, or puts the old folder back when the
input folder is missing.
"""

from __future__ import annotations

import io
import shutil
import uuid
import zipfile
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from metis.wizard import SpecificationFixture, package_specification

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

    from metis.wizard import InterviewState

SPECIFICATION = "specification.yaml"
_PACKAGE_FILES = "outputs"


def build(
    state: InterviewState, fixtures: Iterable[tuple[str, bytes]]
) -> dict[str, bytes]:
    """Package a done Interview and return the files of its input folder, by relative path.

    :raises CompilationError: The Specification is not runnable.
    :raises SpecificationError: A fixture is missing or not valid.
    """
    archive = package_specification(
        state,
        [
            SpecificationFixture(name=name, stream=io.BytesIO(content))
            for name, content in fixtures
        ],
    )
    files: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
        for member in bundle.infolist():
            parts = PurePosixPath(member.filename).parts
            if member.is_dir() or len(parts) < 3 or parts[1] != _PACKAGE_FILES:
                continue
            files[PurePosixPath(*parts[2:]).as_posix()] = bundle.read(member)
    return files


def stage(current: Path, files: Mapping[str, bytes]) -> Path:
    """Write ``files`` to a new folder next to the input folder ``current``. Return its path."""
    staged = current.with_name(f"{current.name}.tmp-{uuid.uuid4().hex}")
    (staged / "fixtures").mkdir(parents=True)
    for relative, content in files.items():
        path = staged / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return staged


def swap(current: Path, staged: Path) -> None:
    """Put the staged folder in place of the input folder ``current``."""
    previous = current.with_name(f"{current.name}.old-{uuid.uuid4().hex}")
    if current.exists():
        current.rename(previous)
    staged.rename(current)
    shutil.rmtree(previous, ignore_errors=True)


def recover(current: Path) -> None:
    """Remove what a crashed save left, and keep one complete input folder at ``current``."""
    directory = current.parent
    if not directory.is_dir():
        return
    for path in sorted(directory.glob(f"{current.name}.old-*")):
        if current.exists():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.rename(current)
    for path in directory.glob(f"{current.name}.tmp-*"):
        shutil.rmtree(path, ignore_errors=True)


__all__ = ["SPECIFICATION", "build", "recover", "stage", "swap"]
