"""The folders of a project, relative to the project folder.

Everything that METIS writes in a project is in one folder, ``evaluations/``. The engine, the
reports and the API store add ``evaluations/…`` to the project folder that they get.
``execution_layout`` gives the paths inside one Experiment folder.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

EVALUATIONS = PurePosixPath("evaluations")
INTERVIEWS = EVALUATIONS / "interviews"
"""Folder of the Interviews, one folder each, named by its ``<id>``."""
SPECIFICATIONS = EVALUATIONS / "specifications"
"""Folder of the Specifications, one folder each. An Interview and the Specification that it
makes have the same ``<id>``."""
EXPERIMENTS = EVALUATIONS / "experiments"
"""Folder of the Experiments, one folder each, named ``<specification id>-YYYYMMDD-HHMMSS``."""
DATABASE = EVALUATIONS / "metis.db"
"""The default SQLite file of the API store. The CLI does not use it."""

ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
"""The ``<id>`` of an Interview and a Specification: 1 to 64 letters, digits, ``-`` or ``_``.

It is one folder name. The wizard CLI and the store of the API use this rule."""


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
