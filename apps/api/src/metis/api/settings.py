"""Process-wide settings and the production composition of the wizard dependencies.

The app keeps immutable settings, model clients, and the store for the lifetime of the process.
The wizard routes keep no Interview state. Each lifecycle request carries the required state in
its body. The store routes keep the records of each Target in the database that
``METIS_DATABASE_URL`` names, and their files in `experiments/design/` of the project folder.
`metis-api --project-dir` names the project folder. `build_dependencies` is the one place that
constructs the real gateway-backed interviewer and matcher; tests inject a scripted pair instead
through the router's dependency override.

The API starts when model settings are missing. Then `GET /api/v1/models` reports the missing
roles, and each Interview route returns 503 `model_unavailable`.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeAlias

from metis.api.store import DATABASE
from metis.core.execution_layout import find_project_root
from metis.core.model_settings import (
    ModelRole,
    RoleSettings,
    find_env_file,
    format_missing_settings,
    missing_settings,
    resolve_role,
)
from metis.wizard import InterviewRequest, InterviewResult

if TYPE_CHECKING:
    from pathlib import Path

API_ROLES = (ModelRole.INTERVIEW,)
"""The roles that the API cannot run an Interview without."""


class SettingsError(RuntimeError):
    """A required setting is missing from the environment."""


CONNECTION_CHECK_ENV = "METIS_API_CONNECTION_CHECK"
"""`1` lets the connection-check route reach the target, and `0` stops it. When it is unset,
the check is on only for an API that listens on this computer."""

DEFAULT_HOST = "127.0.0.1"
"""The API listens for its own computer only, unless ``HOST`` names another address."""

_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

DATABASE_URL_ENV = "METIS_DATABASE_URL"
"""The SQLAlchemy URL of the store database. The default is
`sqlite:///<project>/metis.db`."""


def connection_check_from_env() -> bool:
    """Whether the connection check reads the environment and reaches the target.

    An API that listens only on this computer runs for one user, who owns its `.env`, so the
    check is on. A server that other people can reach keeps it off, because it would fetch any
    URL that a user types. ``METIS_API_CONNECTION_CHECK`` overrides both.

    The check never expands a `${NAME}` variable into a URL, so it cannot send a server secret
    to a client's host. It still sends requests to any other URL that a client gives, including
    an internal address that only the API host can reach. Turn it on for a shared server only
    when that is acceptable.
    """
    flag = os.environ.get(CONNECTION_CHECK_ENV, "").strip()
    if flag in ("0", "1"):
        return flag == "1"
    return os.environ.get("HOST", DEFAULT_HOST).strip() in _LOCAL_HOSTS


@dataclass(frozen=True)
class Settings:
    """The environment that the API reads its model settings and connection-check switch from.

    The connection check reads the environment and reaches the target only for an API that
    listens on this computer. See ``connection_check_from_env``.

    ``env`` is a copy of the process environment, so it holds keys. ``repr`` leaves it out.
    ``database_url`` can hold a password, so ``repr`` leaves it out too.
    """

    env: Mapping[str, str] = field(repr=False)
    env_file: Path | None = None
    connection_check: bool = False
    project_dir: Path = field(default_factory=find_project_root)
    database_url: str = field(default="", repr=False)

    @classmethod
    def from_env(
        cls, env_file: Path | None = None, project_dir: Path | None = None
    ) -> Settings:
        """Take a copy of the process environment.

        ``project_dir`` comes from `metis-api --project-dir`. Without it, the project folder is
        the one that ``find_project_root`` finds.
        """
        project_dir = (project_dir or find_project_root()).resolve()
        database_url = (
            os.environ.get(DATABASE_URL_ENV, "").strip()
            or f"sqlite:///{project_dir / DATABASE}"
        )
        return cls(
            env=dict(os.environ),
            env_file=env_file or find_env_file(),
            connection_check=connection_check_from_env(),
            project_dir=project_dir,
            database_url=database_url,
        )

    def role(self, role: ModelRole) -> RoleSettings:
        """The settings of ``role``. As in the engine, the runner agent defaults to the user
        agent model."""
        if role is ModelRole.RUNNER_AGENT:
            return resolve_role(
                role, self.env, default=self.role(ModelRole.USER_AGENT).model
            )
        return resolve_role(role, self.env)

    def missing_message(self) -> str | None:
        """The error text when the interview role has no key, else ``None``."""
        missing = missing_settings(API_ROLES, self.env)
        if not missing:
            return None
        return format_missing_settings("The METIS API", missing, self.env_file)


InterviewHandler: TypeAlias = Callable[[InterviewRequest], InterviewResult]


@dataclass(frozen=True)
class WizardDependencies:
    """The configured public Interview handler used by the Interview routes."""

    interview_handler: InterviewHandler


def build_dependencies(settings: Settings) -> WizardDependencies:
    """Compose the production interviewer and matcher from settings.

    The wizard package owns provider construction. The API passes only the resolved role settings
    to the public runtime configurator and keeps the public `handle_interview` function as its
    handler.

    Raises ``SettingsError`` when the interview role has no API key.
    """
    message = settings.missing_message()
    if message is not None:
        raise SettingsError(message)

    from metis.wizard import configure_interview_runtime, handle_interview

    configure_interview_runtime(interview=settings.role(ModelRole.INTERVIEW))
    return WizardDependencies(interview_handler=handle_interview)


__all__ = [
    "DEFAULT_HOST",
    "API_ROLES",
    "CONNECTION_CHECK_ENV",
    "DATABASE_URL_ENV",
    "InterviewHandler",
    "Settings",
    "SettingsError",
    "WizardDependencies",
    "build_dependencies",
    "connection_check_from_env",
]
