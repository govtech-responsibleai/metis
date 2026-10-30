"""Checks for published schema ownership and generated content."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def schema_repo(tmp_path: Path, repo_root: Path) -> Path:
    core = tmp_path / "packages" / "core"
    core.mkdir(parents=True)
    shutil.copytree(repo_root / "packages/core/scripts", core / "scripts")
    shutil.copytree(repo_root / "packages/core/schemas", core / "schemas")
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    return tmp_path


def _check(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(root / "packages/core/scripts/generate_schema.py"),
            "--check",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def test_registered_schemas_pass_with_ignored_dependencies(schema_repo: Path) -> None:
    (schema_repo / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    dependency = schema_repo / "node_modules" / "external.schema.json"
    dependency.parent.mkdir()
    dependency.write_text("{}", encoding="utf-8")

    result = _check(schema_repo)

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "filename",
    [
        "packages/core/schemas/extra.schema.json",
        "packages/engine/schemas/extra.schema.json",
    ],
)
@pytest.mark.parametrize("tracked", [False, True])
def test_unregistered_schemas_fail(
    schema_repo: Path, filename: str, tracked: bool
) -> None:
    schema = schema_repo / filename
    schema.parent.mkdir(parents=True, exist_ok=True)
    schema.write_text("{}", encoding="utf-8")
    if tracked:
        subprocess.run(["git", "add", filename], cwd=schema_repo, check=True)

    result = _check(schema_repo)

    assert result.returncode == 1
    assert "Unregistered schema" in result.stdout
    assert filename in result.stdout.replace("\n", "")
    assert schema.read_text(encoding="utf-8") == "{}"


@pytest.mark.parametrize("missing", [False, True])
def test_missing_or_stale_schema_fails(schema_repo: Path, missing: bool) -> None:
    schema = schema_repo / "packages/core/schemas/specification.schema.json"
    if missing:
        schema.unlink()
    else:
        schema.write_text("{}", encoding="utf-8")

    result = _check(schema_repo)

    assert result.returncode == 1
    assert "Schema missing or stale: specification.schema.json" in result.stdout
    assert (
        (not schema.exists()) if missing else schema.read_text(encoding="utf-8") == "{}"
    )
