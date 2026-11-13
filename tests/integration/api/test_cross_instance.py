"""The wizard routes across app instances: each request carries the Interview, and they keep nothing.

A wizard request carries the whole Interview state. This test starts an Interview on one app
object and continues it on a *different* app object that saw none of the first turn. If the
second turn advances correctly, the state on the wire is the only carrier. The test also proves
that the wizard routes write no file and save nothing in the store. The client saves an Interview
only through the store routes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from metis.api.store import Store
from metis.wizard.contracts import ChatResponse, InterviewStartRequest
from tests.fixtures.wizard.scripted import ScriptedInterviewer


def _start_body() -> dict[str, object]:
    return InterviewStartRequest(
        description="A policy assistant",
        known_capability_ids=["tool_use"],
        capability_confidence="medium",
    ).model_dump(mode="json")


def _files(folder: Path) -> set[Path]:
    return {path for path in folder.rglob("*") if path.is_file()}


def test_a_fresh_app_continues_an_interview_and_the_wizard_routes_keep_nothing(
    make_client,
    store: Store,
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    working = tmp_path / "working"
    working.mkdir()
    monkeypatch.chdir(working)  # any per-interview file would land here
    project_files = _files(project_dir)
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
    assert list(working.iterdir()) == []  # no server-owned interview file anywhere
    assert _files(project_dir) == project_files
    assert store.list_targets().targets == []
