"""The folders of a project, relative to the project folder.

Everything that METIS writes in a project is in one folder, ``evaluations/``. The engine, the
reports and the API store add ``evaluations/…`` to the project folder that they get.
``execution_layout`` gives the paths inside one Experiment folder.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

EVALUATIONS = PurePosixPath("evaluations")
EXPERIMENTS = EVALUATIONS / "experiments"
"""Folder of the Experiments, one folder each, named ``<specification id>-YYYYMMDD-HHMMSS``."""


def find_project_root(cwd: Path | None = None) -> Path:
    """Find the default project folder, which holds ``evaluations/``.

    It is the nearest folder at or above ``cwd`` that has a `pyproject.toml`, else ``cwd``.
    ``cwd`` defaults to the working directory.
    """
    current = cwd or Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    return current
