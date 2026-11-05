from __future__ import annotations

import time
from types import SimpleNamespace
from typing import cast

import pytest
from langfuse import Langfuse

from metis.core.traces import Observation
from metis.engine.extractor import langfuse


class _ApiError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"Langfuse returned {status_code}")
        self.status_code = status_code


def _client(script: list[object]) -> tuple[Langfuse, list[dict[str, object]]]:
    calls: list[dict[str, object]] = []

    def get_many(**kwargs: object) -> object:
        calls.append(kwargs)
        response = script.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    client = SimpleNamespace(
        api=SimpleNamespace(observations_v_2=SimpleNamespace(get_many=get_many))
    )
    return cast(Langfuse, client), calls


def _page(
    *, cursor: str | None, observations: list[Observation] | None = None
) -> object:
    return SimpleNamespace(data=observations or [], meta=SimpleNamespace(cursor=cursor))


def test_a_5xx_retries_the_same_page_without_losing_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, calls = _client(
        [
            _page(
                cursor="next",
                observations=[Observation(id="o1", trace_id="t1", output="one")],
            ),
            _ApiError(503),
            _page(
                cursor=None,
                observations=[Observation(id="o2", trace_id="t2", output="two")],
            ),
        ]
    )
    delays: list[float] = []
    monkeypatch.setattr(time, "sleep", delays.append)

    observations = langfuse._page_through_observations(client, "sessionId", "session-1")

    assert [observation.id for observation in observations] == ["o1", "o2"]
    assert [call["cursor"] for call in calls] == [None, "next", "next"]
    assert delays == [1.0]


def test_a_persistent_5xx_stops_after_the_bounded_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = _ApiError(500)
    client, calls = _client([error] * 5)
    delays: list[float] = []
    monkeypatch.setattr(time, "sleep", delays.append)

    with pytest.raises(_ApiError) as raised:
        langfuse._page_through_observations(client, "sessionId", "session-1")

    assert raised.value is error
    assert len(calls) == 5
    assert delays == [1.0, 2.0, 4.0, 8.0]


def test_a_non_5xx_error_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    error = _ApiError(429)
    client, calls = _client([error])
    delays: list[float] = []
    monkeypatch.setattr(time, "sleep", delays.append)

    with pytest.raises(_ApiError) as raised:
        langfuse._page_through_observations(client, "sessionId", "session-1")

    assert raised.value is error
    assert len(calls) == 1
    assert delays == []
