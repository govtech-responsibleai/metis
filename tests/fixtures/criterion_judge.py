"""An offline OpenAI transport for criterion judge contract checks."""

import json
from typing import Any

import httpx
from openai import AsyncOpenAI

from metis.core.traces import GradingInput, Observation, Trace


def recorded_session() -> GradingInput:
    return GradingInput(
        traces=(
            Trace(
                id="trace-1",
                session_id="session-1",
                observations=(
                    Observation(
                        id="root",
                        trace_id="trace-1",
                        input="Find a source",
                        output="The source is example.org",
                    ),
                    Observation(
                        id="tool",
                        trace_id="trace-1",
                        parent_observation_id="root",
                        type="TOOL",
                        name="search",
                        output={"url": "example.org"},
                    ),
                ),
            ),
        )
    )


def judge_client(
    content: str | list[str],
    requests: list[dict[str, Any]],
    *,
    status_code: int = 200,
    status: str = "completed",
    refusal: str | None = None,
) -> AsyncOpenAI:
    """An offline client whose Responses API calls return ``content``.

    A list gives one reply for each call, in order. A string is the reply to every call.
    """
    replies = content if isinstance(content, list) else None

    def respond(request: httpx.Request) -> httpx.Response:
        text = replies[len(requests)] if replies is not None else content
        requests.append(json.loads(request.content))
        part = (
            {"type": "refusal", "refusal": refusal}
            if refusal is not None
            else {"type": "output_text", "text": text, "annotations": []}
        )
        return httpx.Response(
            status_code,
            json={
                "id": "response-1",
                "object": "response",
                "created_at": 1,
                "model": "test-judge",
                "status": status,
                "parallel_tool_calls": False,
                "tool_choice": "none",
                "tools": [],
                "output": [
                    {
                        "id": "message-1",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [part],
                    }
                ],
            },
        )

    return AsyncOpenAI(
        api_key="test-only",
        base_url="https://judge.invalid/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
