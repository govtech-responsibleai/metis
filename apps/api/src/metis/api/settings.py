"""Process-wide settings and the production composition of the wizard dependencies.

The app keeps immutable settings, model clients, and the store for the lifetime of the process.
The wizard routes keep no Interview state. Each lifecycle request carries the required state in
its body. The store routes keep the records of each Target in the database that
``METIS_DATABASE_URL`` names, and their files in `evaluations/` of the project folder.
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
from metis.core.model_settings import (
    ModelRole,
    RoleSettings,
    find_env_file,
    format_missing_settings,
    missing_settings,
    resolve_role,
)
from metis.core.project_layout import find_project_root
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

LOGIN_ENV = "METIS_LOGIN"
"""`1` turns login on. Then each `/api` route needs a login session, except the login route, the
logout route, and the user routes that the admin token protects. Login is off when the variable is unset or `0`."""

ADMIN_TOKEN_ENV = "METIS_ADMIN_TOKEN"
"""The token of the routes that make and list user accounts. Those routes are off when it is
unset. It can do nothing else: it reads no record of a user account and starts no login session."""

DATABASE_URL_ENV = "METIS_DATABASE_URL"
"""The SQLAlchemy URL of the store database. The default is
`sqlite:///<project>/evaluations/metis.db`."""


class InvalidSettingError(ValueError):
    """An engine setting in the environment is not valid. The API does not start."""


@dataclass(frozen=True)
class EngineSettings:
    """The settings of the engine routes.

    ``concurrency`` and ``langfuse_timeout`` are the values of a request that gives none, as
    ``--concurrency`` and ``--langfuse-timeout`` of the engine CLI. A request cannot give more
    than the maximum. ``stop_timeout`` is the number of seconds that the shutdown waits for
    the runs to stop, in all. ``max_runs`` is the number of jobs that run at the same time;
    a start beyond it waits in the queue.

    ``langfuse_timeout`` is 180 seconds, longer than the 90 of the CLI. The server starts the
    evaluate as soon as the simulation ends, while the last traces still reach Langfuse.
    A session whose traces have settled is graded after its first check, so the longer limit
    costs time only when traces are late or missing.
    """

    concurrency: int = 1
    max_concurrency: int = 8
    langfuse_timeout: int = 180
    max_langfuse_timeout: int = 600
    stop_timeout: int = 30
    max_runs: int = 4

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> EngineSettings:
        """Read each setting from its variable, or use its default.

        :raises InvalidSettingError: When a value is not a whole number of 1 or more, or a
            default is more than its maximum.
        """
        values = {
            name: _whole_number(env, variable, getattr(cls, name))
            for name, variable in _ENGINE_VARIABLES.items()
        }
        settings = cls(**values)
        for name, maximum in (
            ("concurrency", "max_concurrency"),
            ("langfuse_timeout", "max_langfuse_timeout"),
        ):
            if getattr(settings, name) > getattr(settings, maximum):
                raise InvalidSettingError(
                    f"{_ENGINE_VARIABLES[name]} is {getattr(settings, name)}, which is more "
                    f"than {_ENGINE_VARIABLES[maximum]} ({getattr(settings, maximum)})."
                )
        return settings


_ENGINE_VARIABLES = {
    "concurrency": "METIS_API_ENGINE_CONCURRENCY",
    "max_concurrency": "METIS_API_ENGINE_MAX_CONCURRENCY",
    "langfuse_timeout": "METIS_API_LANGFUSE_TIMEOUT",
    "max_langfuse_timeout": "METIS_API_MAX_LANGFUSE_TIMEOUT",
    "stop_timeout": "METIS_API_STOP_TIMEOUT",
    "max_runs": "METIS_API_ENGINE_MAX_RUNS",
}


def _whole_number(env: Mapping[str, str], variable: str, default: int) -> int:
    if variable not in env:
        return default
    text = env[variable].strip()
    if not text.isdigit() or int(text) < 1:
        raise InvalidSettingError(
            f"{variable} must be a whole number of 1 or more, got {env[variable]!r}."
        )
    return int(text)


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
    return is_local_host()


def is_local_host() -> bool:
    """Whether the API listens only on this computer, from ``HOST``."""
    return os.environ.get("HOST", DEFAULT_HOST).strip() in _LOCAL_HOSTS


def login_from_env() -> tuple[bool, str]:
    """Whether login is on, and the admin token. An unset token is the empty text.

    Raises ``SettingsError`` for an admin token with login off. The token makes user accounts,
    and a user account has a purpose only when login is on. A server in that state is open to
    all, which the person who set the token did not intend.
    """
    flag = os.environ.get(LOGIN_ENV, "").strip()
    if flag not in ("", "0", "1"):
        raise SettingsError(f"{LOGIN_ENV} must be 1 or 0, but it is '{flag}'.")
    login = flag == "1"
    admin_token = os.environ.get(ADMIN_TOKEN_ENV, "").strip()
    if admin_token and not login:
        raise SettingsError(
            f"{ADMIN_TOKEN_ENV} is set, but login is off. Set {LOGIN_ENV}=1 to turn login on, "
            f"or remove {ADMIN_TOKEN_ENV}."
        )
    return login, admin_token


@dataclass(frozen=True)
class Settings:
    """The environment that the API reads its model settings and connection-check switch from.

    The connection check reads the environment and reaches the target only for an API that
    listens on this computer. See ``connection_check_from_env``.

    ``env`` is a copy of the process environment, so it holds keys. ``repr`` leaves it out.
    ``database_url`` can hold a password, so ``repr`` leaves it out too. ``repr`` also leaves
    out ``admin_token``.

    ``login`` and ``admin_token`` come from ``login_from_env``. ``secure_cookie`` is on for an
    API that other computers can reach, so the browser sends the login cookie only over HTTPS.
    """

    env: Mapping[str, str] = field(repr=False)
    env_file: Path | None = None
    connection_check: bool = False
    project_dir: Path = field(default_factory=find_project_root)
    database_url: str = field(default="", repr=False)
    engine: EngineSettings = field(default_factory=EngineSettings)
    login: bool = False
    admin_token: str = field(default="", repr=False)
    secure_cookie: bool = False

    @classmethod
    def from_env(
        cls, env_file: Path | None = None, project_dir: Path | None = None
    ) -> Settings:
        """Take a copy of the process environment.

        ``project_dir`` comes from `metis-api --project-dir`. Without it, the project folder is
        the one that ``find_project_root`` finds.

        Raises ``SettingsError`` when the login settings disagree. See ``login_from_env``.
        :raises InvalidSettingError: When an engine setting is not valid.
        """
        login, admin_token = login_from_env()
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
            engine=EngineSettings.from_env(os.environ),
            login=login,
            admin_token=admin_token,
            secure_cookie=not is_local_host(),
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
    "ADMIN_TOKEN_ENV",
    "DEFAULT_HOST",
    "LOGIN_ENV",
    "API_ROLES",
    "CONNECTION_CHECK_ENV",
    "DATABASE_URL_ENV",
    "EngineSettings",
    "InterviewHandler",
    "InvalidSettingError",
    "Settings",
    "SettingsError",
    "WizardDependencies",
    "build_dependencies",
    "connection_check_from_env",
    "is_local_host",
    "login_from_env",
]
