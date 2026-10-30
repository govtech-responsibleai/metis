"""metis-insights depends on metis-core only (docs/architecture.md, Dependency Invariants)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

FORBIDDEN = ("metis.engine", "metis.library", "metis.wizard")


def test_workspace_dependencies_are_core_only(repo_root: Path) -> None:
    pyproject = tomllib.loads(
        (repo_root / "packages" / "insights" / "pyproject.toml").read_text()
    )
    workspace = {
        re.split(r"[<>=!~ \[]", dep, maxsplit=1)[0]
        for dep in pyproject["project"]["dependencies"]
        if dep.startswith("metis-")
    }
    assert workspace == {"metis-core"}


def test_source_imports_no_other_workspace_package(repo_root: Path) -> None:
    src = repo_root / "packages" / "insights" / "src"
    offenders = [
        f"{path.relative_to(repo_root)}: {name}"
        for path in src.rglob("*.py")
        for name in FORBIDDEN
        if name in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
