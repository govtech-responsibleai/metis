"""The simulation model roles: the user agent and the runner agent.

Both roles resolve through ``metis.core.model_settings`` when a trial is built, never at import
time, so a value set after import is used.

- The user agent: ``Task.user_agent_model``, then
  ``defaults.user_agent_model``, then ``USER_AGENT_MODEL``, then ``DEFAULT_MODEL``. Its
  gateway is ``USER_AGENT_API_KEY`` / ``USER_AGENT_BASE_URL``, then ``OPENAI_*``.
- The runner agent (the generic runners): ``defaults.runner_agent_model``, then
  ``RUNNER_AGENT_MODEL``, then the user agent model of the trial. Its gateway is
  ``RUNNER_AGENT_*``, then ``USER_AGENT_*``, then ``OPENAI_*``.

``USER_AGENT_MAX_TOKENS`` and ``USER_AGENT_TEMPERATURE`` are left out of the request when they
are unset or empty. See ``docs/guide/models.md``.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from langfuse.openai import AsyncOpenAI

from metis.core.model_settings import ModelRole, RoleSettings, resolve_role

if TYPE_CHECKING:
    from collections.abc import Mapping


def user_agent_settings(
    model: str | None = None, env: Mapping[str, str] | None = None
) -> RoleSettings:
    """The user agent role. ``model`` is the value from the Specification."""
    return resolve_role(ModelRole.USER_AGENT, os.environ if env is None else env, model)


def runner_agent_settings(
    model: str | None = None,
    *,
    user_agent_model: str | None = None,
    env: Mapping[str, str] | None = None,
) -> RoleSettings:
    """The runner agent role. Its default is the user agent model of the trial."""
    env = os.environ if env is None else env
    return resolve_role(
        ModelRole.RUNNER_AGENT,
        env,
        model,
        default=user_agent_model or user_agent_settings(env=env).model,
    )


def sampling_options(env: Mapping[str, str] | None = None) -> dict[str, object]:
    """``max_tokens`` and ``temperature`` for a user agent call, when they are set."""
    env = os.environ if env is None else env
    options: dict[str, object] = {}
    if env.get("USER_AGENT_MAX_TOKENS"):
        options["max_tokens"] = int(env["USER_AGENT_MAX_TOKENS"])
    if env.get("USER_AGENT_TEMPERATURE"):
        options["temperature"] = float(env["USER_AGENT_TEMPERATURE"])
    return options


def llm_client(settings: RoleSettings) -> AsyncOpenAI:
    """A client for the gateway of ``settings``.

    ``max_retries=0``: retries happen in ``parse_completion`` / ``create_completion``, where
    each attempt is logged. The client is Langfuse's drop-in, which traces each attempt to the
    METIS-internal Langfuse.
    """
    return AsyncOpenAI(
        api_key=settings.api_key, base_url=settings.base_url, max_retries=0
    )


__all__ = [
    "llm_client",
    "runner_agent_settings",
    "sampling_options",
    "user_agent_settings",
]
