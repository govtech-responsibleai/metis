"""Web records and store requests for the store route tests."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from metis.wizard import InterviewState, derive_stage
from tests.fixtures.wizard.context import interview_context
from tests.fixtures.wizard.specifications import research_assistant

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from httpx import Response

FileParts = list[tuple[str, tuple[str, bytes, str]]]


def done_state() -> InterviewState:
    """A done Interview whose Specification refers to the fixture `policy.pdf`."""
    return InterviewState(
        specification=research_assistant(),
        context=interview_context(),
        behaviours_confirmed=True,
        confirmed=True,
    )


def web_record(
    target_id: str,
    state: InterviewState | dict[str, Any],
    *,
    fixtures: list[dict[str, Any]] | None = None,
    outbound: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The record that the web app saves, with one transcript entry."""
    parsed = InterviewState.model_validate(state)
    entry: dict[str, Any] = {
        "kind": "interaction",
        "request_id": "req-1",
        "request": {"type": "chat", "prompt": "Describe it"},
        "status": "pending",
    }
    if outbound is not None:
        entry["outbound"] = {"files": outbound, "removedFixtures": [], "attempt": 1}
    return {
        "id": target_id,
        "title": parsed.specification.target.name,
        "stage": derive_stage(parsed).value,
        "created_at": 1_760_000_000_000,
        "updated_at": 1_760_000_000_000,
        "state": parsed.model_dump(mode="json"),
        "transcript": [
            {"kind": "initial_description", "id": "opening", "description": "A tool"},
            entry,
        ],
        "fixtures": fixtures or [],
    }


def ref(name: str, content: bytes, media_type: str) -> dict[str, Any]:
    return {"name": name, "type": media_type, "size": len(content)}


def put_interview(
    client: TestClient, record: dict[str, Any], files: FileParts | None = None
) -> Response:
    return client.put(
        f"/api/v1/targets/{record['id']}/interview",
        files=[
            ("record", ("record.json", json.dumps(record), "application/json")),
            *(files or []),
        ],
    )
