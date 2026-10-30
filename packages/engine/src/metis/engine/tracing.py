"""Tracing the engine's own model calls to the METIS-internal Langfuse.

The simulated user, the artifact summarizer, the runner agent, and every judge call made by a
grader go to the Langfuse that the three ``METIS_INTERNAL_LANGFUSE_*`` variables name. Tracing
is off unless all three are set.

The ``LANGFUSE_*`` variables name the Langfuse of the system under test, which the extractor
reads. The ``langfuse.openai`` drop-in picks its client by public key, and a call that names no
key falls back to the only registered client, which in ``evaluate`` is the target's. So every
engine model call names :func:`tracing_key`: the simulation helpers pass it on each request,
and :func:`traced` sets it for every call nested inside, such as a library grader's judge calls.
When tracing is off, the key names a disabled client, so nothing is sent anywhere.

The client exports on a background thread and flushes at exit, so an unreachable Langfuse never
blocks or fails a run.
"""

from __future__ import annotations

import functools
import os
from typing import TYPE_CHECKING, TypeVar

from langfuse import Langfuse, get_client, observe

from metis.core.model_settings import METIS_INTERNAL_LANGFUSE_VARS

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from metis.core.trials import TrialConfig

_TRACING_OFF_KEY = "metis-internal-tracing-off"

_T = TypeVar("_T")


def trial_session_id(experiment: str, config: TrialConfig) -> str:
    """The Langfuse session of one trial: its simulation attempts and its grading.

    ``experiment`` is the name of the experiment folder, so two runs of one Specification
    stay apart, and a later evaluation of the same run joins the same session.
    """
    return f"{experiment}/{config.task_id}/{config.persona}/{config.trial_index}"


def register_tracing(env: Mapping[str, str]) -> str:
    """Register the METIS-internal Langfuse client from ``env`` and return its public key.

    A client built without keys reads ``LANGFUSE_*``, the target's project. So when an internal
    variable is missing, the client is a disabled one under a placeholder key.
    """
    public_key, secret_key, base_url = (
        env.get(name) for name in METIS_INTERNAL_LANGFUSE_VARS
    )
    if public_key and secret_key and base_url:
        Langfuse(public_key=public_key, secret_key=secret_key, base_url=base_url)
        return public_key
    Langfuse(
        public_key=_TRACING_OFF_KEY, secret_key=_TRACING_OFF_KEY, tracing_enabled=False
    )
    return _TRACING_OFF_KEY


@functools.cache
def tracing_key() -> str:
    """The public key that every engine model call names, registered on first use.

    A command calls this once after it loads `.env`, before it builds any Langfuse client of
    its own.
    """
    return register_tracing(os.environ)


async def traced(
    run: Callable[[], Awaitable[_T]],
    *,
    name: str,
    session_id: str | None,
    metadata: Mapping[str, object],
    output: Callable[[_T], object] | None = None,
) -> _T:
    """Await ``run()`` as one trace, so every model call inside it is grouped and internal.

    ``session_id`` groups the trace with the others of the same trial in Langfuse. ``output``
    turns the result into the trace's output, so the trace shows what the run decided. Without
    it the trace has no output. An exception from ``run()`` marks the trace as an error and is
    re-raised unchanged.
    """
    return await _observed(
        run,
        name,
        session_id,
        dict(metadata),
        output,
        # `@observe` takes this keyword at run time, but its type hints do not show it.
        langfuse_public_key=tracing_key(),  # type: ignore[call-arg]
    )


@observe(capture_input=False, capture_output=False)
async def _observed(
    run: Callable[[], Awaitable[_T]],
    name: str,
    session_id: str | None,
    metadata: dict[str, object],
    output: Callable[[_T], object] | None,
) -> _T:
    # `@observe` takes `langfuse_public_key=` from the call and sets it for the calls nested
    # here, which is how a grader's judge calls reach the internal client.
    client = get_client(public_key=tracing_key())
    client.update_current_span(name=name)
    client.update_current_trace(name=name, session_id=session_id, metadata=metadata)
    result = await run()
    if output is not None:
        summary = output(result)
        client.update_current_span(output=summary)
        client.update_current_trace(output=summary)
    return result


__all__ = ["register_tracing", "traced", "tracing_key", "trial_session_id"]
