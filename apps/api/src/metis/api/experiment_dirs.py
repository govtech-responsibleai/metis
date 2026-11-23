"""Find an experiment folder from its id.

An experiment id is the name of a folder under ``<project folder>/evaluations/experiments/``. The
lookup compares the id with the names in that folder, so an id can never name another path.

The project folder of a request is the project folder of the server when login is off, and the
project folder of the user account of the request when login is on. The report routes and the
engine routes use both functions, so a request reaches only the experiments of its own user
account.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from metis.api.errors import RouteError
from metis.api.store import user_project_dir
from metis.core import project_layout

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import Request


_STARTED = re.compile(r"-(\d{8}-\d{6})$")
"""The end of an Experiment folder name: the local time at which the engine made the folder."""


class ExperimentNotFound(RouteError):
    """No experiment folder has the id. The routes give 404 ``experiment_not_found``."""

    def __init__(self, experiment_id: str) -> None:
        super().__init__(
            404,
            "experiment_not_found",
            f"No experiment folder is named {experiment_id!r}.",
        )


def request_project_dir(request: Request) -> Path:
    """The project folder that holds the experiment folders of the request.

    With login off, it is the project folder of the server. With login on, it is the project
    folder of the user account that the login guard found.
    """
    server: Path = request.app.state.project_dir
    if not getattr(request.app.state, "login", False):
        return server
    account = getattr(request.state, "user_account", None)
    if account is None:
        raise RuntimeError("The login guard did not find the user account.")
    return user_project_dir(server, account.id)


def find_experiment_dir(project_dir: Path, experiment_id: str) -> Path:
    """Return the experiment folder named ``experiment_id`` in ``project_dir``.

    :raises ExperimentNotFound: When no folder under ``evaluations/experiments/`` has the name.
    """
    experiments = project_dir / project_layout.EXPERIMENTS
    if experiments.is_dir():
        for path in experiments.iterdir():
            if path.name == experiment_id and path.is_dir():
                return path
    raise ExperimentNotFound(experiment_id)


def target_experiments(project_dir: Path, target_id: str) -> list[tuple[str, datetime]]:
    """The Experiment folders of a Target in ``project_dir``, newest first, each with its start time.

    The engine names an Experiment folder ``<Specification id>-<YYYYmmdd-HHMMSS>``, and the
    Specification id of a Target is the Target id. So the folders of a Target are the ones
    whose name is the Target id and one time.
    """
    experiments = project_dir / project_layout.EXPERIMENTS
    found: list[tuple[str, datetime]] = []
    for path in experiments.iterdir() if experiments.is_dir() else ():
        started = _STARTED.search(path.name)
        if (
            started is None
            or path.name[: started.start()] != target_id
            or not path.is_dir()
        ):
            continue
        try:
            at = datetime.strptime(started.group(1), "%Y%m%d-%H%M%S")
        except ValueError:
            continue
        # The engine writes the local time with no zone.
        found.append((path.name, at.astimezone()))
    return sorted(found, key=lambda item: (item[1], item[0]), reverse=True)


__all__ = [
    "ExperimentNotFound",
    "find_experiment_dir",
    "request_project_dir",
    "target_experiments",
]
