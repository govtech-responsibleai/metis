"""The store over HTTP: two browsers share a complete Interview and its files."""

from __future__ import annotations

from tests.fixtures.api.records import done_state, put_interview, ref, web_record
from tests.fixtures.wizard.scripted import ScriptedInterviewer

TARGET = "8d2f6e10-41b7-4c3a-a5e9-0f1e2d3c4b5a"
POLICY = b"%PDF-1.4 policy bytes"


def test_an_interview_saved_in_one_browser_opens_in_another(make_client) -> None:
    browser_a = make_client(ScriptedInterviewer())
    browser_b = make_client(ScriptedInterviewer())
    record = web_record(
        TARGET,
        done_state(),
        fixtures=[ref("policy.pdf", POLICY, "application/pdf")],
    )

    saved = put_interview(
        browser_a, record, [("files", ("policy.pdf", POLICY, "application/pdf"))]
    )

    assert saved.status_code == 204, saved.text
    listed = browser_b.get("/api/v1/targets").json()
    assert [row["id"] for row in listed["targets"]] == [TARGET]
    opened = browser_b.get(f"/api/v1/targets/{TARGET}/interview")
    assert opened.status_code == 200
    assert opened.json() == record
    file = browser_b.get(f"/api/v1/targets/{TARGET}/interview/files/policy.pdf")
    assert file.content == POLICY
    assert file.headers["content-type"] == "application/pdf"
