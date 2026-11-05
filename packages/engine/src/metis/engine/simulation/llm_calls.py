"""One log row per simulation LLM request, retries included.

Every LLM call the simulator makes goes through :func:`parse_completion` or, for
tool-calling requests, :func:`create_completion`. Each an :class:`LLMCallRecord` to an :class:`LLMCallLog` for each attempt. A
trial's calls go to ``outputs/trials/<id>/evidence/llm_calls.jsonl``; calls made
once per experiment, such as the summarizer's fixture descriptions, go to
``logs/llm_calls.jsonl``. The log answers what a simulation cost and which model
actually answered it.

Retries happen here rather than inside the OpenAI SDK, so callers must build
their client with ``max_retries=0``. The SDK's own retries would be invisible to
the log, and turning them off without retrying here would end a trial as
``system_error`` on every transient gateway error.

Each request also names the METIS-internal Langfuse client
(:func:`metis.engine.tracing.tracing_key`) and is traced there as a generation named by its
``component``. It is never traced to the target's Langfuse.

The row model is private to ``metis-engine``: nothing outside the engine reads the
file yet.
"""

from __future__ import annotations

import asyncio
import os
import random
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any, TypeVar

# Patches the OpenAI client so it accepts the `langfuse_public_key=` that every request sends.
import langfuse.openai  # noqa: F401
from openai import APIConnectionError, APIStatusError
from pydantic import BaseModel

from metis.core import execution_layout
from metis.core.logging import get_logger
from metis.engine.tracing import tracing_key

from ._superseded import superseded_path

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from openai import AsyncOpenAI
    from openai.types.chat import (
        ChatCompletion,
        ChatCompletionMessageParam,
        ChatCompletionToolParam,
        ParsedChatCompletion,
    )

logger = get_logger()

TRIAL_EVIDENCE = "evidence"
"""A trial's evidence folder, inside its folder under ``outputs/trials/``."""
LLM_CALLS_FILE = "llm_calls.jsonl"

MAX_RETRIES = 8
"""Default retries after the first attempt; configurable with ``METIS_LLM_MAX_RETRIES``."""
_INITIAL_RETRY_DELAY = 0.5
_MAX_RETRY_DELAY = 8.0
_DEFAULT_RETRY_BUDGET_SECONDS = 120.0
_MAX_CONFIGURED_RETRIES = 20
_MAX_RETRY_BUDGET_SECONDS = 600.0

_T = TypeVar("_T", bound=BaseModel)
_R = TypeVar("_R")


class LLMCallRecord(BaseModel):
    """One request to an LLM endpoint.

    A count the endpoint did not report is ``None``, never ``0``, so a missing
    figure cannot pass for a free call.
    """

    at: datetime
    """When the request was sent (UTC)."""
    component: str
    """Which part of the simulator made the call, e.g. ``"user_agent"``."""
    requested_model: str
    returned_model: str | None
    tokens_in: int | None
    tokens_out: int | None
    latency_ms: int
    error: str | None
    """``"<ExceptionType>: <message>"`` when the request failed, else ``None``."""


@dataclass(frozen=True)
class LLMCallLog:
    """Appends :class:`LLMCallRecord` rows to one JSONL file."""

    path: Path

    @classmethod
    def for_trial(cls, run_dir: Path) -> LLMCallLog:
        """The log for the trial whose folder is ``run_dir``."""
        return cls(run_dir / TRIAL_EVIDENCE / LLM_CALLS_FILE)

    @classmethod
    def for_experiment(cls, experiment_root: Path) -> LLMCallLog:
        """The log for calls made once per experiment rather than per trial."""
        return cls(experiment_root / execution_layout.LOGS / LLM_CALLS_FILE)

    def supersede(self, *, now: datetime | None = None) -> Path | None:
        """Move an earlier attempt's file aside so this attempt starts a new one.

        Mirrors ``quarantine_stale_artifacts``: an attempt's record describes that
        attempt only, so its log must too, but the earlier attempt's calls were
        still spent and are kept. The destination is
        ``llm_calls-superseded-<UTC timestamp>.jsonl`` beside the file.

        :param now: Timestamp for the destination name. Defaults to the current
            UTC time; injected by tests for a deterministic name.
        :returns: Where the file was moved, or ``None`` when there was none.
        """
        if not self.path.is_file():
            return None
        dest = superseded_path(self.path, now=now)
        self.path.rename(dest)
        return dest

    def append(self, record: LLMCallRecord) -> None:
        """Write one row, creating the file and its folder on first use."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(record.model_dump_json() + "\n")


def is_retryable(exc: Exception) -> bool:
    """The OpenAI SDK's retry rule: connection errors, timeouts, 408, 409, 429, 5xx."""
    if isinstance(exc, APIConnectionError):  # includes APITimeoutError
        return True
    if isinstance(exc, APIStatusError):
        status = exc.status_code
        return status in (408, 409, 429) or status >= 500
    return False


def _retry_policy() -> tuple[int, float]:
    """Read the bounded retry count and cumulative wait budget from the environment."""
    retries_text = os.environ.get("METIS_LLM_MAX_RETRIES")
    try:
        retries = MAX_RETRIES if retries_text is None else int(retries_text)
    except ValueError as exc:
        raise ValueError("METIS_LLM_MAX_RETRIES must be an integer") from exc
    if not 0 <= retries <= _MAX_CONFIGURED_RETRIES:
        raise ValueError(
            f"METIS_LLM_MAX_RETRIES must be between 0 and {_MAX_CONFIGURED_RETRIES}"
        )

    budget_text = os.environ.get("METIS_LLM_RETRY_BUDGET_SECONDS")
    try:
        budget = (
            _DEFAULT_RETRY_BUDGET_SECONDS if budget_text is None else float(budget_text)
        )
    except ValueError as exc:
        raise ValueError("METIS_LLM_RETRY_BUDGET_SECONDS must be a number") from exc
    if not 0 <= budget <= _MAX_RETRY_BUDGET_SECONDS:
        raise ValueError(
            "METIS_LLM_RETRY_BUDGET_SECONDS must be between 0 and "
            f"{_MAX_RETRY_BUDGET_SECONDS:g}"
        )
    return retries, budget


def _duration_seconds(value: str) -> float | None:
    """Parse a provider reset duration such as ``250ms``, ``1m30s`` or ``2h``."""
    if not re.fullmatch(r"\s*(?:(?:\d+(?:\.\d+)?)(?:ms|s|m|h))+\s*", value):
        return None
    units = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
    parts = re.findall(r"(\d+(?:\.\d+)?)(ms|s|m|h)", value)
    return sum(float(amount) * units[unit] for amount, unit in parts)


def _date_seconds(value: str, now: datetime) -> float | None:
    """Parse an HTTP date and return the seconds until it, or ``None`` if invalid."""
    try:
        target = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=UTC)
    return max(0.0, (target.astimezone(UTC) - now).total_seconds())


def _provider_retry_after(
    exc: Exception, *, now: datetime | None = None
) -> float | None:
    """Return the provider's retry delay from headers or a rate-limit reset message."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    else:
        current = current.astimezone(UTC)

    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is not None:
        retry_after_ms = headers.get("retry-after-ms")
        if retry_after_ms is not None:
            try:
                return max(0.0, float(retry_after_ms) / 1000.0)
            except (TypeError, ValueError):
                pass

        retry_after = headers.get("retry-after")
        if retry_after is not None:
            try:
                return max(0.0, float(retry_after))
            except (TypeError, ValueError):
                date_delay = _date_seconds(str(retry_after), current)
                if date_delay is not None:
                    return date_delay

        for name in (
            "x-ratelimit-reset-requests",
            "x-ratelimit-reset-tokens",
        ):
            value = headers.get(name)
            if value is not None:
                delay = _duration_seconds(str(value))
                if delay is not None:
                    return delay

    reset = re.search(
        r"Limit resets at:\s*(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)? UTC)",
        str(exc),
        re.IGNORECASE,
    )
    if reset is not None:
        reset_text = reset.group(1).removesuffix(" UTC") + "+00:00"
        try:
            target = datetime.fromisoformat(reset_text)
        except ValueError:
            return None
        return max(0.0, (target - current).total_seconds())
    return None


def _retry_delay(retry: int) -> float:
    """Exponential backoff with jitter when the provider supplies no reset time."""
    delay = min(_INITIAL_RETRY_DELAY * 2.0**retry, _MAX_RETRY_DELAY)
    return delay * (1 - 0.25 * random.random())


def _usage_counts(completion: object) -> tuple[int | None, int | None]:
    """``(tokens_in, tokens_out)`` as reported, ``None`` for whatever is missing."""
    usage = getattr(completion, "usage", None)
    if usage is None:
        return None, None
    return (
        getattr(usage, "prompt_tokens", None),
        getattr(usage, "completion_tokens", None),
    )


async def parse_completion(
    client: AsyncOpenAI,
    log: LLMCallLog,
    *,
    component: str,
    model: str,
    messages: list[ChatCompletionMessageParam],
    response_format: type[_T],
    **options: Any,
) -> ParsedChatCompletion[_T]:
    """Call ``client.beta.chat.completions.parse``, logging and retrying each attempt.

    A retryable failure is retried up to :data:`MAX_RETRIES` times. Every attempt,
    successful or not, appends one row to ``log``. The last attempt's exception is
    re-raised unchanged, so callers handle failures as they did before.

    :param client: A client built with ``max_retries=0``.
    :param log: Where this call's rows go.
    :param component: The row's ``component``.
    :param options: Further ``parse`` arguments, e.g. ``max_tokens``.
    """
    return await _logged_attempts(
        log,
        component=component,
        model=model,
        send=lambda: client.beta.chat.completions.parse(
            model=model,
            messages=messages,
            response_format=response_format,
            **options,
            **_tracing(component),
        ),
    )


async def create_completion(
    client: AsyncOpenAI,
    log: LLMCallLog,
    *,
    component: str,
    model: str,
    messages: list[ChatCompletionMessageParam],
    tools: list[ChatCompletionToolParam],
    **options: Any,
) -> ChatCompletion:
    """Call ``client.chat.completions.create`` with ``tools``, logging and retrying each
    attempt as :func:`parse_completion` does.

    :param client: A client built with ``max_retries=0``.
    :param log: Where this call's rows go.
    :param component: The row's ``component``, e.g. ``"runner_agent"``.
    :param options: Further ``create`` arguments, e.g. ``tool_choice``.
    """
    return await _logged_attempts(
        log,
        component=component,
        model=model,
        send=lambda: client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            **options,
            **_tracing(component),
        ),
    )


def _tracing(component: str) -> dict[str, Any]:
    """The arguments that the ``langfuse.openai`` client takes off the request.

    The key keeps the trace out of the target's Langfuse; see ``metis.engine.tracing``.
    """
    return {"langfuse_public_key": tracing_key(), "name": component}


async def _logged_attempts(
    log: LLMCallLog,
    *,
    component: str,
    model: str,
    send: Callable[[], Awaitable[_R]],
) -> _R:
    """Run ``send`` until it succeeds, retrying a retryable failure up to
    :data:`MAX_RETRIES` times. Every attempt appends one row to ``log``, and the last
    attempt's exception is re-raised unchanged."""
    max_retries, retry_budget = _retry_policy()
    waited = 0.0
    for retry in range(max_retries + 1):
        at = datetime.now(tz=UTC)
        start = time.monotonic()
        try:
            completion = await send()
        except Exception as exc:
            # A finish-reason error carries the completion, and so its usage.
            failed = getattr(exc, "completion", None)
            tokens_in, tokens_out = _usage_counts(failed)
            log.append(
                LLMCallRecord(
                    at=at,
                    component=component,
                    requested_model=model,
                    returned_model=getattr(failed, "model", None) or None,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    latency_ms=round((time.monotonic() - start) * 1000),
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            if retry == max_retries or not is_retryable(exc):
                raise
            provider_delay = _provider_retry_after(exc)
            delay = (
                provider_delay if provider_delay is not None else _retry_delay(retry)
            )
            if waited + delay > retry_budget:
                logger.warning(
                    "[llm_calls] %s call retry budget exhausted before retry: "
                    "%.1fs requested, %.1fs remaining: %s",
                    component,
                    delay,
                    max(0.0, retry_budget - waited),
                    exc,
                )
                raise
            waited += delay
            logger.warning(
                "[llm_calls] %s call failed, retrying in %.1fs (%d/%d): %s",
                component,
                delay,
                retry + 1,
                max_retries,
                exc,
            )
            await asyncio.sleep(delay)
            continue

        tokens_in, tokens_out = _usage_counts(completion)
        log.append(
            LLMCallRecord(
                at=at,
                component=component,
                requested_model=model,
                returned_model=getattr(completion, "model", None) or None,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                latency_ms=round((time.monotonic() - start) * 1000),
                error=None,
            )
        )
        return completion
    raise AssertionError("unreachable: the last attempt returns or raises")
