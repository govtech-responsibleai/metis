"""Find an experiment folder from its id.

An experiment id is the name of a folder under ``<project folder>/experiments/execute/``. The
lookup compares the id with the names in that folder, so an id can never name another path.

The project folder of a request is the project folder of the server when login is off, and the
project folder of the user account of the request when login is on. The report routes and the
engine routes use both functions, so a request reaches only the experiments of its own user
account.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from metis.api.errors import RouteError
from metis.api.store import user_project_dir
from metis.core import execution_layout

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import Request


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

    :raises ExperimentNotFound: When no folder under ``experiments/execute/`` has the name.
    """
    executions = project_dir / execution_layout.EXECUTIONS
    if executions.is_dir():
        for path in executions.iterdir():
            if path.name == experiment_id and path.is_dir():
                return path
    raise ExperimentNotFound(experiment_id)


__all__ = ["ExperimentNotFound", "find_experiment_dir", "request_project_dir"]
