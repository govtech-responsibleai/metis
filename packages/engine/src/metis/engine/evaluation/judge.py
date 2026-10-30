"""Judge settings: which model each grader uses, and the one client every grader run shares.

The judge model is a grader argument, so the spec records it and a run can be reproduced from
its spec. For each criterion whose grader takes ``JudgeArgs``, the model is resolved before the
run, in this order:

1. ``grader_args.model`` on the criterion
2. the experiment's ``defaults.judge_model``
3. the ``JUDGE_MODEL`` environment variable
4. ``DEFAULT_MODEL``, else ``gpt-6-luna`` (``metis.core.model_settings.default_model``)

and written into the args before they are validated, so ``self.args.model`` is always a ``str``
inside ``grade()`` and every ``GraderRecord`` names the model that produced its results.
``max_input_tokens`` resolves the same way from ``grader_args.max_input_tokens``, then
``JUDGE_MAX_INPUT_TOKENS``, then the ``JudgeArgs`` default. A ``CriterionJudgeArgs`` grader also gets
``criterion`` from the criterion description.

The gateway is not a grader argument: it is the same for every judge in a run, and it stays in
the environment (``JUDGE_API_KEY`` / ``JUDGE_BASE_URL``, falling back to ``OPENAI_API_KEY`` /
``OPENAI_BASE_URL``). One ``AsyncOpenAI`` client is built for it per evaluation. Its connection
pool caps how many grader LLM calls are in flight across every grader run, however a grader
fans out internally. ``pool=None`` matters: a plain timeout would also limit the wait for a free
connection, so a call queued behind others under the cap would time out before it was ever
sent and be recorded as errored. With ``pool=None`` only the request itself is timed.

The client is Langfuse's ``langfuse.openai`` drop-in. Graders call it without a Langfuse key,
so the orchestrator runs each grader inside ``metis.engine.tracing.traced``, which names the
METIS-internal client for every call nested inside.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
from langfuse.openai import AsyncOpenAI

from metis.core.model_settings import ModelRole, resolve_role
from metis.library.grader import JudgeArgs, LLMSettings, criterion_judge_args

if TYPE_CHECKING:
    from collections.abc import Mapping

    from metis.library.grader import GraderArgs

MAX_JUDGE_CONNECTIONS = 50
"""Grader LLM calls in flight at once, across every grader run. Matches the old per-grader
semaphore of 50."""
JUDGE_REQUEST_TIMEOUT_SECONDS = 300.0
"""How long one grader LLM call may take once sent. Matches the 300s DeepEval used."""


def resolve_grader_args(
    args_model: type[GraderArgs],
    grader_args: Mapping[str, Any],
    *,
    default_judge_model: str | None,
    env: Mapping[str, str],
    description: str | None = None,
) -> dict[str, Any]:
    """The criterion's ``grader_args`` with the judge model filled in, ready to validate.

    Only args models that extend ``JudgeArgs`` get a model; a code-based grader's args are
    returned unchanged, so a stray ``model`` key there is still rejected as unknown. An explicit
    ``model`` on the criterion always wins, even an empty string, which validation then
    reports, rather than being silently replaced.

    Raises ``ValueError`` from ``criterion_judge_args`` when a ``CriterionJudgeArgs`` grader's settings
    or description are invalid.
    """
    resolved = criterion_judge_args(args_model, grader_args, description)
    if issubclass(args_model, JudgeArgs):
        if "model" not in resolved:
            resolved["model"] = resolve_role(
                ModelRole.JUDGE, env, default_judge_model
            ).model
        if "max_input_tokens" not in resolved and "JUDGE_MAX_INPUT_TOKENS" in env:
            resolved["max_input_tokens"] = env["JUDGE_MAX_INPUT_TOKENS"]
    return resolved


@dataclass(frozen=True)
class JudgeGateway:
    """Where grader LLM calls go. Read from the environment, never from the spec."""

    api_key: str
    base_url: str | None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> JudgeGateway | None:
        """The gateway, or ``None`` when no API key is set.

        The judge role resolves through ``resolve_role``: ``JUDGE_*`` wins over ``OPENAI_*`` key
        by key, so a judge-only base URL can sit beside a shared ``OPENAI_API_KEY``. Empty values
        count as unset.
        """
        settings = resolve_role(ModelRole.JUDGE, env)
        if settings.api_key is None:
            return None
        return cls(api_key=settings.api_key, base_url=settings.base_url)


def build_llm_settings(
    gateway: JudgeGateway,
    *,
    max_connections: int = MAX_JUDGE_CONNECTIONS,
    timeout_seconds: float = JUDGE_REQUEST_TIMEOUT_SECONDS,
) -> LLMSettings:
    """The one client every grader run in an evaluation shares.

    The caller owns the client and must close it (``await llm.client.close()``) when the
    evaluation ends. ``AsyncOpenAI`` already retries transient errors (``max_retries``, default
    2), so there is no METIS retry wrapper.
    """
    http_client = httpx.AsyncClient(
        limits=httpx.Limits(max_connections=max_connections),
        timeout=httpx.Timeout(timeout_seconds, pool=None),
    )
    client = AsyncOpenAI(
        api_key=gateway.api_key, base_url=gateway.base_url, http_client=http_client
    )
    return LLMSettings(client=client)
