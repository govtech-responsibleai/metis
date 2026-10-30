"""Judge model and input limit resolution, and the shared, capped judge client."""

from __future__ import annotations

import asyncio
from typing import Any

import httpcore
import httpx
import pytest
from httpcore._backends.mock import AsyncMockBackend
from pydantic import Field

from metis.engine.evaluation.judge import (
    JudgeGateway,
    build_llm_settings,
    resolve_grader_args,
)
from metis.library.grader import DEFAULT_MAX_INPUT_TOKENS, GraderArgs, JudgeArgs


class CodeArgs(GraderArgs):
    limit: int = Field(default=3)


class ModelArgs(JudgeArgs):
    rubric: str = "be kind"


def _resolve(
    grader_args: dict[str, object],
    *,
    default: str | None = None,
    env: dict[str, str] | None = None,
    args_model: type[GraderArgs] = ModelArgs,
) -> dict[str, object]:
    return resolve_grader_args(
        args_model, grader_args, default_judge_model=default, env=env or {}
    )


class TestModelResolution:
    """The four steps, each tested with every later step also set, so order is pinned."""

    def test_1_criterion_model_wins(self) -> None:
        resolved = _resolve(
            {"model": "from-criterion"},
            default="from-spec",
            env={"JUDGE_MODEL": "from-env"},
        )
        assert resolved["model"] == "from-criterion"

    def test_2_experiment_default_beats_env(self) -> None:
        resolved = _resolve({}, default="from-spec", env={"JUDGE_MODEL": "from-env"})
        assert resolved["model"] == "from-spec"

    def test_3_env_beats_package_default(self) -> None:
        assert _resolve({}, env={"JUDGE_MODEL": "from-env"})["model"] == "from-env"

    def test_4_the_default_model_is_last(self) -> None:
        assert _resolve({}, env={"DEFAULT_MODEL": "team"})["model"] == "team"
        assert _resolve({})["model"] == "gpt-6-luna"

    def test_empty_env_var_counts_as_unset(self) -> None:
        assert _resolve({}, env={"JUDGE_MODEL": ""})["model"] == "gpt-6-luna"

    def test_explicit_empty_model_is_kept_for_validation_to_reject(self) -> None:
        assert _resolve({"model": ""}, default="from-spec")["model"] == ""

    def test_code_grader_args_get_no_model(self) -> None:
        resolved = _resolve(
            {"limit": 5},
            default="from-spec",
            env={"JUDGE_MODEL": "x"},
            args_model=CodeArgs,
        )
        assert resolved == {"limit": 5}

    def test_other_args_are_kept_and_the_input_is_not_mutated(self) -> None:
        raw: dict[str, object] = {"threshold": 0.8, "rubric": "strict"}
        resolved = _resolve(raw, default="m")
        assert resolved == {"threshold": 0.8, "rubric": "strict", "model": "m"}
        assert "model" not in raw

    def test_resolved_args_validate(self) -> None:
        args = ModelArgs.model_validate(_resolve({}, default="m"))
        assert args.model == "m"


@pytest.mark.parametrize(
    ("grader_args", "env", "expected"),
    [
        ({"max_input_tokens": 5_000}, {"JUDGE_MAX_INPUT_TOKENS": "9000"}, 5_000),
        ({}, {"JUDGE_MAX_INPUT_TOKENS": "9000"}, 9_000),
        ({}, {}, DEFAULT_MAX_INPUT_TOKENS),
        ({}, {"JUDGE_MAX_INPUT_TOKENS": "lots"}, DEFAULT_MAX_INPUT_TOKENS),
        ({"max_input_tokens": 0}, {}, DEFAULT_MAX_INPUT_TOKENS),
    ],
)
def test_input_limit_resolves_from_criterion_then_env_then_default(
    grader_args, env, expected
) -> None:
    args = ModelArgs.model_validate(_resolve(grader_args, default="m", env=env))
    assert args.max_input_tokens == expected


class TestGateway:
    def test_judge_vars_win(self) -> None:
        gateway = JudgeGateway.from_env(
            {
                "JUDGE_API_KEY": "jk",
                "JUDGE_BASE_URL": "https://judge/v1",
                "OPENAI_API_KEY": "ok",
                "OPENAI_BASE_URL": "https://openai/v1",
            }
        )
        assert gateway == JudgeGateway(api_key="jk", base_url="https://judge/v1")

    def test_falls_back_to_openai_vars(self) -> None:
        gateway = JudgeGateway.from_env(
            {"OPENAI_API_KEY": "ok", "OPENAI_BASE_URL": "https://openai/v1"}
        )
        assert gateway == JudgeGateway(api_key="ok", base_url="https://openai/v1")

    def test_falls_back_key_by_key(self) -> None:
        gateway = JudgeGateway.from_env(
            {"OPENAI_API_KEY": "ok", "JUDGE_BASE_URL": "https://judge/v1"}
        )
        assert gateway == JudgeGateway(api_key="ok", base_url="https://judge/v1")

    def test_no_base_url_means_the_default_endpoint(self) -> None:
        assert JudgeGateway.from_env({"OPENAI_API_KEY": "ok"}) == JudgeGateway(
            api_key="ok", base_url=None
        )

    @pytest.mark.parametrize(
        "env",
        [{}, {"JUDGE_API_KEY": "", "OPENAI_API_KEY": ""}, {"JUDGE_BASE_URL": "u"}],
    )
    def test_no_key_means_no_gateway(self, env: dict[str, str]) -> None:
        assert JudgeGateway.from_env(env) is None


class TestSharedClient:
    def test_client_is_capped_and_timed_without_a_pool_timeout(self) -> None:
        llm = build_llm_settings(
            JudgeGateway(api_key="k", base_url="https://judge/v1"),
            max_connections=7,
            timeout_seconds=30,
        )
        try:
            assert str(llm.client.base_url) == "https://judge/v1/"
            assert llm.client.api_key == "k"
            assert llm.client.timeout == httpx.Timeout(30, pool=None)
            pool = llm.client._client._transport._pool  # type: ignore[attr-defined]  # noqa: SLF001
            assert pool._max_connections == 7  # noqa: SLF001
        finally:
            asyncio.run(llm.client.close())

    def test_defaults(self) -> None:
        llm = build_llm_settings(JudgeGateway(api_key="k", base_url=None))
        try:
            assert llm.client.timeout == httpx.Timeout(300.0, pool=None)
            assert llm.client.max_retries == 2
        finally:
            asyncio.run(llm.client.close())

    @pytest.mark.parametrize(
        ("pool_timeout", "expected"),
        [
            (None, [200, 200, 200]),
            (0.01, [200, "PoolTimeout", "PoolTimeout"]),
        ],
    )
    def test_queued_calls_wait_for_a_connection_only_without_a_pool_timeout(
        self, pool_timeout: float | None, expected: list[object]
    ) -> None:
        """Why build_llm_settings sets pool=None (issue #428, "Grader LLM calls are capped").

        Three concurrent calls through one connection, each taking 0.1s to answer. With no
        pool timeout the queued calls wait their turn and succeed. With a short one, which is
        what a plain ``timeout=T`` would give when T is short, the queued calls fail before
        they are ever sent. The second case is the control that shows the test can tell them
        apart; build_llm_settings must produce the first.
        """

        class SlowBackend(AsyncMockBackend):
            async def connect_tcp(self, *args: Any, **kwargs: Any) -> Any:
                stream = await super().connect_tcp(*args, **kwargs)
                read = stream.read

                async def slow_read(
                    max_bytes: int, timeout: float | None = None
                ) -> bytes:
                    await asyncio.sleep(0.1)
                    return await read(max_bytes, timeout)

                stream.read = slow_read
                return stream

        reply = [b"HTTP/1.1 200 OK\r\n", b"Content-Length: 2\r\n", b"\r\n", b"ok"]

        async def scenario() -> list[object]:
            transport = httpx.AsyncHTTPTransport()
            transport._pool = httpcore.AsyncConnectionPool(  # noqa: SLF001
                max_connections=1, network_backend=SlowBackend(reply * 3)
            )
            async with httpx.AsyncClient(
                transport=transport, timeout=httpx.Timeout(5, pool=pool_timeout)
            ) as client:
                responses = await asyncio.gather(
                    *(client.get("http://judge/v1/x") for _ in range(3)),
                    return_exceptions=True,
                )
            return [
                r.status_code if isinstance(r, httpx.Response) else type(r).__name__
                for r in responses
            ]

        assert asyncio.run(scenario()) == expected
