"""Links from a METIS result to the target's own Langfuse.

Each trial of a simulate run talks to the target in one Langfuse session. The report links
every trial to that session, so a reader can go from a result to its raw traces:

    <base URL>/project/<project id>/sessions/<session id>

The project ID is not in any setting. ``target_langfuse_project`` asks Langfuse for it with
the target's keys (``LANGFUSE_*``), never with the keys of the METIS-internal Langfuse
(``METIS_INTERNAL_LANGFUSE_*``). A key pair belongs to exactly one project.

A link is a convenience. A failed lookup gives no link and a warning, never an error, so it
cannot fail a simulate run or a report build. The code lives in metis-core because the engine
saves the link and ``metis-insights``, which may depend only on core, falls back to building
it for old records.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import quote

import httpx

from metis.core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Mapping


def _warn(reason: str) -> None:
    # The logger is fetched for each warning, not once at import. A logger cached on first
    # use keeps the stream of that moment, which a CLI run in the same process may close.
    get_logger(__name__).warning("target_langfuse_project_unavailable", reason=reason)


DEFAULT_BASE_URL = "https://cloud.langfuse.com"
"""Langfuse Cloud, which the Langfuse SDK uses when no base URL is set."""

DEFAULT_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class TargetProject:
    """The Langfuse project that holds the target's traces."""

    base_url: str
    """The Langfuse base URL, with any path prefix and without a trailing ``/``."""
    project_id: str

    def session_url(self, session_id: str) -> str:
        """The page of one session in this project."""
        return session_url(self.base_url, self.project_id, session_id)


def session_url(base_url: str, project_id: str, session_id: str) -> str:
    """The Langfuse page of a session.

    It keeps a path prefix of the base URL, such as ``/langfuse``, and percent-encodes the
    session ID so that it stays one path segment.
    """
    return (
        f"{base_url.rstrip('/')}/project/{quote(project_id, safe='')}"
        f"/sessions/{quote(session_id, safe='')}"
    )


def _timeout(env: Mapping[str, str]) -> float:
    try:
        return float(env.get("LANGFUSE_TIMEOUT") or DEFAULT_TIMEOUT_SECONDS)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def target_langfuse_project(
    env: Mapping[str, str] | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
) -> TargetProject | None:
    """Find the target's Langfuse project from ``LANGFUSE_*`` in ``env`` (default ``os.environ``).

    The base URL is ``LANGFUSE_BASE_URL``, then ``LANGFUSE_HOST``, then Langfuse Cloud, as the
    engine's trace reader reads it. The timeout is ``LANGFUSE_TIMEOUT`` seconds, 5 when it is
    not set or not a number. It returns ``None`` and logs a warning when a key is missing, the
    request fails, or Langfuse lists no project. The warning names the reason, never a key.
    """
    env = os.environ if env is None else env
    public, secret = env.get("LANGFUSE_PUBLIC_KEY"), env.get("LANGFUSE_SECRET_KEY")
    if not (public and secret):
        _warn("LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY is not set")
        return None
    base_url = (
        env.get("LANGFUSE_BASE_URL") or env.get("LANGFUSE_HOST") or DEFAULT_BASE_URL
    ).rstrip("/")
    try:
        with httpx.Client(
            transport=transport, timeout=_timeout(env), follow_redirects=True
        ) as client:
            response = client.get(
                f"{base_url}/api/public/projects", auth=(public, secret)
            )
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPStatusError as exc:
        _warn(f"HTTP {exc.response.status_code}")
        return None
    except (httpx.HTTPError, ValueError) as exc:
        _warn(type(exc).__name__)
        return None
    projects = body.get("data") if isinstance(body, dict) else None
    first = projects[0] if isinstance(projects, list) and projects else None
    project_id = first.get("id") if isinstance(first, dict) else None
    if not isinstance(project_id, str) or not project_id:
        _warn("Langfuse listed no project")
        return None
    return TargetProject(base_url=base_url, project_id=project_id)


__all__ = ["TargetProject", "session_url", "target_langfuse_project"]
