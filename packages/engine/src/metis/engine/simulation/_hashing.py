"""SHA-256 hashing of files on disk (shared by the summarizer and fixtures)."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of ``path``'s bytes."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
