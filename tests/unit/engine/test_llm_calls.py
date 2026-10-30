"""The simulation's LLM-call log: one row per request, retries included (#476)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest
from pydantic import BaseModel

from metis.engine.simulation import llm_calls
from metis.engine.simulation.llm_calls import (
    LLMCallLog,
    create_completion,
    parse_completion,
)

_REQUEST = httpx.Request("POST", "https://llm.example/v1/chat/completions")


class _Out(BaseModel):
    answer: str


def _completion(
    *, model: str | None = "served-model", usage: object | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        model=model,
        usage=usage,
        choices=[SimpleNamespace(message=SimpleNamespace(parsed=_Out(answer="hi")))],
    )


def _usage(prompt: int | None, completion: int | None) -> SimpleNamespace:
    return SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion)


def _server_error() -> openai.InternalServerError:
    return openai.InternalServerError(
        "bad gateway", response=httpx.Response(502, request=_REQUEST), body=None
    )


class _FakeClient:
    """Answers ``beta.chat.completions.parse`` and ``chat.completions.create`` from one
    script, one entry per call."""

    def __init__(self, *script: object) -> None:
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []
        self.beta = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(parse=self._parse))
        )
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._parse))

    async def _parse(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        step = self._script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


def _rows(log: LLMCallLog) -> list[dict[str, Any]]:
    return [json.loads(line) for line in log.path.read_text().splitlines()]


async def _call(client: _FakeClient, log: LLMCallLog, **options: Any) -> object:
    return await parse_completion(
        client,  # type: ignore[arg-type]
        log,
        component="user_agent",
        model="requested-model",
        messages=[{"role": "user", "content": "hello"}],
        response_format=_Out,
        **options,
    )


_TOOLS: list[Any] = [
    {"type": "function", "function": {"name": "note", "parameters": {"type": "object"}}}
]


async def _tool_call(client: _FakeClient, log: LLMCallLog, **options: Any) -> object:
    return await create_completion(
        client,  # type: ignore[arg-type]
        log,
        component="runner_agent",
        model="requested-model",
        messages=[{"role": "user", "content": "hello"}],
        tools=_TOOLS,
        **options,
    )


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_calls, "_retry_delay", lambda _: 0.0)


@pytest.mark.asyncio
async def test_a_successful_call_writes_one_row(tmp_path: Path) -> None:
    log = LLMCallLog.for_trial(tmp_path)
    client = _FakeClient(_completion(usage=_usage(120, 30)))

    result = await _call(client, log, max_tokens=50)

    assert result is not None
    assert client.calls[0]["max_tokens"] == 50
    assert log.path == tmp_path / "evidence" / "llm_calls.jsonl"
    [row] = _rows(log)
    assert row["component"] == "user_agent"
    assert row["requested_model"] == "requested-model"
    assert row["returned_model"] == "served-model"
    assert row["tokens_in"] == 120
    assert row["tokens_out"] == 30
    assert row["error"] is None
    assert row["latency_ms"] >= 0
    assert datetime.fromisoformat(row["at"]).tzinfo is not None


@pytest.mark.asyncio
async def test_a_failed_call_writes_its_row_and_reraises(tmp_path: Path) -> None:
    """A non-retryable error is logged once, then raised to the caller unchanged."""
    log = LLMCallLog.for_trial(tmp_path)
    error = openai.BadRequestError(
        "bad schema", response=httpx.Response(400, request=_REQUEST), body=None
    )
    client = _FakeClient(error)

    with pytest.raises(openai.BadRequestError):
        await _call(client, log)

    assert len(client.calls) == 1
    [row] = _rows(log)
    assert row["error"].startswith("BadRequestError: ")
    assert row["returned_model"] is None
    assert row["tokens_in"] is None
    assert row["tokens_out"] is None


@pytest.mark.asyncio
async def test_each_retry_is_its_own_row(tmp_path: Path) -> None:
    log = LLMCallLog.for_trial(tmp_path)
    client = _FakeClient(
        _server_error(),
        openai.APIConnectionError(request=_REQUEST),
        _completion(usage=_usage(10, 2)),
    )

    await _call(client, log)

    rows = _rows(log)
    assert [r["error"] is None for r in rows] == [False, False, True]
    assert rows[0]["error"].startswith("InternalServerError: ")
    assert rows[1]["error"].startswith("APIConnectionError: ")
    assert rows[2]["tokens_in"] == 10


@pytest.mark.asyncio
async def test_retries_stop_after_the_last_attempt(tmp_path: Path) -> None:
    log = LLMCallLog.for_trial(tmp_path)
    attempts = llm_calls.MAX_RETRIES + 1
    client = _FakeClient(*(_server_error() for _ in range(attempts)))

    with pytest.raises(openai.InternalServerError):
        await _call(client, log)

    assert len(client.calls) == attempts
    assert len(_rows(log)) == attempts


@pytest.mark.asyncio
async def test_unreported_counts_are_null_not_zero(tmp_path: Path) -> None:
    log = LLMCallLog.for_trial(tmp_path)
    client = _FakeClient(_completion(model="", usage=None))

    await _call(client, log)

    [row] = _rows(log)
    assert row["tokens_in"] is None
    assert row["tokens_out"] is None
    assert row["returned_model"] is None


@pytest.mark.asyncio
async def test_a_partly_reported_usage_keeps_the_missing_count_null(
    tmp_path: Path,
) -> None:
    log = LLMCallLog.for_trial(tmp_path)
    client = _FakeClient(_completion(usage=_usage(40, None)))

    await _call(client, log)

    [row] = _rows(log)
    assert row["tokens_in"] == 40
    assert row["tokens_out"] is None


@pytest.mark.asyncio
async def test_a_truncated_completion_logs_the_usage_it_carries(
    tmp_path: Path,
) -> None:
    """The SDK raises on ``finish_reason == "length"`` but the tokens were spent."""
    log = LLMCallLog.for_trial(tmp_path)
    truncated = _completion(usage=_usage(500, 64))
    client = _FakeClient(
        openai.LengthFinishReasonError(completion=truncated)  # type: ignore[arg-type]
    )

    with pytest.raises(openai.LengthFinishReasonError):
        await _call(client, log)

    assert len(client.calls) == 1  # not retryable
    [row] = _rows(log)
    assert row["error"].startswith("LengthFinishReasonError: ")
    assert row["returned_model"] == "served-model"
    assert (row["tokens_in"], row["tokens_out"]) == (500, 64)


@pytest.mark.asyncio
async def test_a_tool_call_writes_one_row_under_its_component(tmp_path: Path) -> None:
    log = LLMCallLog.for_trial(tmp_path)
    client = _FakeClient(_completion(usage=_usage(40, 5)))

    await _tool_call(client, log, tool_choice="auto")

    assert client.calls[0]["tools"] == _TOOLS
    assert client.calls[0]["tool_choice"] == "auto"
    [row] = _rows(log)
    assert row["component"] == "runner_agent"
    assert row["returned_model"] == "served-model"
    assert (row["tokens_in"], row["tokens_out"], row["error"]) == (40, 5, None)


@pytest.mark.asyncio
async def test_a_retried_tool_call_writes_a_row_per_attempt(tmp_path: Path) -> None:
    log = LLMCallLog.for_trial(tmp_path)
    client = _FakeClient(_server_error(), _completion())

    await _tool_call(client, log)

    rows = _rows(log)
    assert rows[0]["error"].startswith("InternalServerError: ")
    assert rows[1]["error"] is None
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_a_failed_tool_call_writes_its_row_and_reraises(tmp_path: Path) -> None:
    log = LLMCallLog.for_trial(tmp_path)
    error = openai.BadRequestError(
        "bad tools", response=httpx.Response(400, request=_REQUEST), body=None
    )
    client = _FakeClient(error)

    with pytest.raises(openai.BadRequestError):
        await _tool_call(client, log)

    assert len(client.calls) == 1
    [row] = _rows(log)
    assert row["error"].startswith("BadRequestError: ")


@pytest.mark.asyncio
async def test_tool_call_retries_stop_after_the_last_attempt(tmp_path: Path) -> None:
    log = LLMCallLog.for_trial(tmp_path)
    attempts = llm_calls.MAX_RETRIES + 1
    client = _FakeClient(*(_server_error() for _ in range(attempts)))

    with pytest.raises(openai.InternalServerError):
        await _tool_call(client, log)

    assert len(_rows(log)) == attempts


def test_the_experiment_log_lives_under_logs(tmp_path: Path) -> None:
    assert LLMCallLog.for_experiment(tmp_path).path == (
        tmp_path / "logs" / "llm_calls.jsonl"
    )


_STAMP = datetime(2026, 10, 21, 6, 15, 0, tzinfo=UTC)


def test_supersede_without_a_file_does_nothing(tmp_path: Path) -> None:
    assert LLMCallLog.for_trial(tmp_path).supersede(now=_STAMP) is None


def test_supersede_keeps_an_earlier_attempts_file(tmp_path: Path) -> None:
    log = LLMCallLog.for_trial(tmp_path)
    log.path.parent.mkdir(parents=True)
    log.path.write_text("attempt 1\n")

    dest = log.supersede(now=_STAMP)

    assert dest == tmp_path / "evidence" / "llm_calls-superseded-20261021T061500Z.jsonl"
    assert dest is not None and dest.read_text() == "attempt 1\n"
    assert not log.path.exists()


def test_supersede_twice_in_one_second_keeps_both(tmp_path: Path) -> None:
    log = LLMCallLog.for_trial(tmp_path)
    log.path.parent.mkdir(parents=True)
    for text in ("first", "second"):
        log.path.write_text(text)
        log.supersede(now=_STAMP)

    names = sorted(p.name for p in log.path.parent.iterdir())
    assert names == [
        "llm_calls-superseded-20261021T061500Z-2.jsonl",
        "llm_calls-superseded-20261021T061500Z.jsonl",
    ]
