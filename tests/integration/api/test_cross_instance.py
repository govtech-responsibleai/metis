"""Statelessness across app instances: the client holds the interview, the server holds nothing.

The Interview is safe on a stateless wire only if a request carries the whole state. This test
starts an Interview on one app object and continues it on a *different* app object that saw none of
the first turn — if the second turn advances correctly, the state on the wire is the only carrier.
It also proves that the service writes no per-Interview state file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from metis.wizard.contracts import ChatResponse, InterviewStartRequest
from tests.fixtures.wizard.scripted import ScriptedInterviewer


def _start_body() -> dict[str, object]:
    return InterviewStartRequest(
        description="A policy assistant",
        known_capability_ids=["tool_use"],
        capability_confidence="medium",
    ).model_dump(mode="json")


def test_a_fresh_app_continues_an_interview_and_neither_writes_a_state_file(
    make_client,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)  # any per-interview file would land here
    client_a = make_client(ScriptedInterviewer())
    client_b = make_client(ScriptedInterviewer())
    client_c = make_client(ScriptedInterviewer())

    opening = client_a.post("/api/v1/wizard/interview/start", json=_start_body()).json()
    state = opening["state"]
    request_id = state["pending"]["request_id"]

    respond = {
        "state": state,
        "request_id": request_id,
        "response": ChatResponse(text="a research tool").model_dump(mode="json"),
    }

    # The second app object held none of the first turn's state; it can only work from the body.
    result = client_b.post("/api/v1/wizard/interview/turn", json=respond)

    assert result.status_code == 200
    forwarded = result.json()
    assert forwarded["type"] == "success"
    assert forwarded["state"] != state  # the Interview moved forward

    ended = client_c.post(
        "/api/v1/wizard/interview/end", json={"state": forwarded["state"]}
    )

    assert ended.status_code == 200
    assert ended.json()["outcome"] == "done"
    assert list(tmp_path.iterdir()) == []  # no server-owned interview file anywhere
