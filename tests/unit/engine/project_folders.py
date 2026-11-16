"""A project folder for CLI tests that patch ``find_project_root``."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def existing_folder(path: Path) -> Path:
    """Create ``path`` and return it, as ``find_project_root`` returns an existing folder."""
    path.mkdir(parents=True, exist_ok=True)
    return path
