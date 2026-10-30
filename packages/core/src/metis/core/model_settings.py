"""Model settings for each LLM role, and the one `.env` search that every command uses.

Each role reads ``<PREFIX>_MODEL``, ``<PREFIX>_API_KEY`` and ``<PREFIX>_BASE_URL``. The key and
the URL each fall back on their own to the shared ``OPENAI_API_KEY`` and ``OPENAI_BASE_URL``, so
a setup with one gateway needs only the shared pair. The runner agent first falls back to the
user agent variables. An empty value counts as unset.

The model resolves in this order: the value that the caller gives (from the Specification),
then ``<PREFIX>_MODEL``, then the default model. So one ``DEFAULT_MODEL`` line selects the model
of every chat role. The embeddings role needs an
embedding model, so it keeps its own default and skips ``DEFAULT_MODEL``. Keys and URLs come only
from the environment.
They never go in a Specification, and ``RoleSettings`` hides them from ``repr``.

``load_env`` reads one `.env` file: ``METIS_ENV_FILE`` when it is set, else the first `.env`
found from the working directory up to the project root. Exported values win over the file.

See ``docs/guide/models.md``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

MODEL_GUIDE = "docs/guide/models.md"
"""The guide that every missing-setting message names."""

ENV_FILE_VAR = "METIS_ENV_FILE"
"""Names one `.env` file. When it is set, the search does not run."""

SHARED_PREFIX = "OPENAI"

METIS_INTERNAL_LANGFUSE_VARS = (
    "METIS_INTERNAL_LANGFUSE_PUBLIC_KEY",
    "METIS_INTERNAL_LANGFUSE_SECRET_KEY",
    "METIS_INTERNAL_LANGFUSE_BASE_URL",
)
"""The METIS-internal Langfuse, where the wizard and the engine trace their own model calls.

Tracing is on only when all three are set. There is no fallback to ``LANGFUSE_*``, which names
the Langfuse of the system under test.
"""


def default_model(env: Mapping[str, str]) -> str:
    """The model of every chat role that has no model of its own: ``DEFAULT_MODEL``, else
    ``gpt-6-luna``.

    It reads ``env`` when a role resolves, not at import, because a command loads `.env` after
    this module is imported.
    """
    return env.get("DEFAULT_MODEL") or "gpt-6-luna"


class ModelRole(StrEnum):
    """One LLM role in the METIS flow."""

    INTERVIEW = "interview"
    EMBEDDINGS = "embeddings"
    USER_AGENT = "user_agent"
    RUNNER_AGENT = "runner_agent"
    JUDGE = "judge"


@dataclass(frozen=True)
class RoleSpec:
    """The variables, the default, and the score effect of one role."""

    role: ModelRole
    label: str
    prefix: str
    affects_scores: bool
    own_default: str | None = None
    """A model that replaces ``DEFAULT_MODEL`` for this role. Only embeddings need one."""
    fallback_prefixes: tuple[str, ...] = ()
    """Prefixes to try after ``prefix`` and before ``OPENAI``, for the key and the URL."""

    @property
    def model_var(self) -> str:
        return f"{self.prefix}_MODEL"

    @property
    def key_vars(self) -> tuple[str, ...]:
        return tuple(f"{p}_API_KEY" for p in self._prefixes)

    @property
    def url_vars(self) -> tuple[str, ...]:
        return tuple(f"{p}_BASE_URL" for p in self._prefixes)

    @property
    def _prefixes(self) -> tuple[str, ...]:
        return (self.prefix, *self.fallback_prefixes, SHARED_PREFIX)


ROLES: dict[ModelRole, RoleSpec] = {
    spec.role: spec
    for spec in (
        RoleSpec(ModelRole.INTERVIEW, "Interview", "INTERVIEW", False),
        RoleSpec(
            ModelRole.EMBEDDINGS,
            "Embeddings",
            "EMBEDDING",
            False,
            own_default="text-embedding-3-large",
        ),
        RoleSpec(ModelRole.USER_AGENT, "User agent", "USER_AGENT", True),
        RoleSpec(
            ModelRole.RUNNER_AGENT,
            "Runner agent",
            "RUNNER_AGENT",
            True,
            fallback_prefixes=("USER_AGENT",),
        ),
        RoleSpec(ModelRole.JUDGE, "Judge", "JUDGE", True),
    )
}
"""The one role table. The order is the order of the flow."""


@dataclass(frozen=True)
class RoleSettings:
    """The resolved model and gateway for one role. ``repr`` shows no key or URL."""

    role: ModelRole
    model: str
    api_key: str | None = field(default=None, repr=False)
    base_url: str | None = field(default=None, repr=False)
    source: str = ""
    """Where the model came from, for messages: ``specification.yaml``, a variable name, or
    ``built-in default``. It never holds a key or a URL."""

    @property
    def configured(self) -> bool:
        """True when the role has an API key. The URL is optional."""
        return self.api_key is not None


def _first(env: Mapping[str, str], names: Iterable[str]) -> str | None:
    for name in names:
        value = env.get(name)
        if value:
            return value
    return None


def resolve_role(
    role: ModelRole,
    env: Mapping[str, str],
    model: str | None = None,
    *,
    default: str | None = None,
) -> RoleSettings:
    """Resolve the settings of ``role``.

    ``model`` is the value from the Specification (the component, then the experiment
    default), which wins over ``<PREFIX>_MODEL``. ``default`` comes next. The runner agent
    needs it: its default is the user agent model of the Trial. Then a chat role uses
    ``default_model``. The embeddings role uses its own default.
    """
    spec = ROLES[role]
    # The runner agent follows the user agent model, so one run uses one simulation model.
    follows = tuple(f"{prefix}_MODEL" for prefix in spec.fallback_prefixes)
    resolved, source = _model_and_source(spec, env, model, default, follows)
    return RoleSettings(
        role=role,
        model=resolved,
        api_key=_first(env, spec.key_vars),
        base_url=_first(env, spec.url_vars),
        source=source,
    )


def _model_and_source(
    spec: RoleSpec,
    env: Mapping[str, str],
    model: str | None,
    default: str | None,
    follows: tuple[str, ...],
) -> tuple[str, str]:
    """The model of a role, and where it came from, in the order of ``resolve_role``."""
    if model:
        return model, "specification.yaml"
    if env.get(spec.model_var):
        return env[spec.model_var], spec.model_var
    if default:
        return default, "user agent model"
    for name in follows:
        if env.get(name):
            return env[name], name
    if spec.own_default:
        return spec.own_default, "built-in default"
    if env.get("DEFAULT_MODEL"):
        return env["DEFAULT_MODEL"], "DEFAULT_MODEL"
    return default_model(env), "built-in default"


def describe_models(settings: Iterable[RoleSettings]) -> str:
    """One line that names the model of each role and its source, for example
    ``Models: User agent gpt-6-luna (DEFAULT_MODEL) · Judge gpt-6-luna (built-in default)``.
    """
    parts = [f"{ROLES[s.role].label} {s.model} ({s.source})" for s in settings]
    return "Models: " + " · ".join(parts)


def missing_settings(
    roles: Iterable[ModelRole], env: Mapping[str, str]
) -> dict[ModelRole, tuple[str, ...]]:
    """The roles that have no API key, each with the variable names that can supply one.

    The result holds variable names only, never values.
    """
    return {
        role: ROLES[role].key_vars
        for role in roles
        if _first(env, ROLES[role].key_vars) is None
    }


class ModelSettingsError(RuntimeError):
    """A command cannot start, because a role that it calls has no settings."""


def format_missing_settings(
    command: str,
    missing: Mapping[ModelRole, tuple[str, ...]],
    env_file: Path | None,
) -> str:
    """The one error text: the command, the variables for each role, the `.env` path, the guide."""
    lines = [f"{command} needs model settings that are not set:"]
    lines += [
        f"  - {ROLES[role].label}: set {' or '.join(names)}"
        for role, names in missing.items()
    ]
    lines.append(
        f"Settings file read: {env_file}"
        if env_file is not None
        else "Settings file read: none. No .env file was found."
    )
    lines.append(f"See {MODEL_GUIDE}.")
    return "\n".join(lines)


def check_roles(
    command: str,
    roles: Iterable[ModelRole],
    env: Mapping[str, str],
    env_file: Path | None,
) -> None:
    """Raise ``ModelSettingsError`` when a role in ``roles`` has no API key."""
    missing = missing_settings(roles, env)
    if missing:
        raise ModelSettingsError(format_missing_settings(command, missing, env_file))


# ── the .env search ─────────────────────────────────────────────────────────


def _is_project_root(directory: Path) -> bool:
    if (directory / ".git").exists():
        return True
    pyproject = directory / "pyproject.toml"
    if not pyproject.is_file():
        return False
    try:
        return "[tool.uv.workspace]" in pyproject.read_text(encoding="utf-8")
    except OSError:
        return False


def find_env_file(
    cwd: Path | None = None, env: Mapping[str, str] | None = None
) -> Path | None:
    """The `.env` file that a command reads, or ``None``.

    ``METIS_ENV_FILE`` wins when it is set. Else the search starts at ``cwd`` and goes up. It
    stops at the project root (a directory with ``.git`` or the workspace ``pyproject.toml``).
    When no project root is above ``cwd``, only ``cwd/.env`` is read, so the search never
    reaches a home directory.
    """
    env = os.environ if env is None else env
    named = env.get(ENV_FILE_VAR)
    if named:
        return Path(named).expanduser()
    start = (cwd or Path.cwd()).resolve()
    chain = [start, *start.parents]
    root = next((d for d in chain if _is_project_root(d)), None)
    searched = chain[: chain.index(root) + 1] if root is not None else [start]
    return next((d / ".env" for d in searched if (d / ".env").is_file()), None)


def load_env(cwd: Path | None = None) -> Path | None:
    """Load the one `.env` file into ``os.environ``. Exported values win.

    Returns the file that was read, so a command can name it in an error.

    Raises ``ModelSettingsError`` when ``METIS_ENV_FILE`` names a file that does not exist.
    """
    from dotenv import load_dotenv

    path = find_env_file(cwd)
    if path is None:
        return None
    if not path.is_file():
        raise ModelSettingsError(
            f"{ENV_FILE_VAR} names {path}, but that file does not exist. See {MODEL_GUIDE}."
        )
    load_dotenv(path, override=False)
    return path


__all__ = [
    "ENV_FILE_VAR",
    "METIS_INTERNAL_LANGFUSE_VARS",
    "MODEL_GUIDE",
    "ROLES",
    "ModelRole",
    "ModelSettingsError",
    "RoleSettings",
    "RoleSpec",
    "check_roles",
    "default_model",
    "describe_models",
    "find_env_file",
    "format_missing_settings",
    "load_env",
    "missing_settings",
    "resolve_role",
]
