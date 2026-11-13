"""The project folder that the engine and the API find from a working directory."""

from __future__ import annotations

from typing import TYPE_CHECKING

from metis.core.execution_layout import find_project_root

if TYPE_CHECKING:
    from pathlib import Path


def test_the_project_folder_is_the_nearest_folder_with_a_pyproject(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    nested = project / "experiments" / "design"
    nested.mkdir(parents=True)
    (project / "pyproject.toml").write_text('[project]\nname = "project"\n')
    loose = tmp_path / "loose"
    loose.mkdir()

    assert find_project_root(project) == project
    assert find_project_root(nested) == project
    assert find_project_root(loose) == loose
