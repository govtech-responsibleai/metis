"""Saved Interview bundles remain usable when workflow records are added."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from metis.api import input_folder
from metis.api.main import create_app
from metis.api.store import Store
from metis.api.tables import interviews, targets
from tests.fixtures.api._shared import database_url, scripted_interview_handler
from tests.fixtures.api.records import done_state, ref, web_record

POLICY = b"policy bytes"


@pytest.mark.parametrize("interrupted", [False, True])
def test_saved_interviews_keep_their_records_files_and_save_times(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    interrupted: bool,
) -> None:
    complete = web_record(
        "complete",
        done_state(),
        fixtures=[ref("policy.pdf", POLICY, "application/pdf")],
    )
    draft_state = done_state()
    draft_state.confirmed = False
    draft = web_record("draft", draft_state)
    unrunnable = web_record("unrunnable", done_state())
    broken = {"id": "broken", "state": {}}
    records = [complete, draft, unrunnable, broken]
    saved_at = datetime(2026, 11, 1, tzinfo=UTC)
    database = project_dir / "experiments" / "metis.db"
    database.parent.mkdir()
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE interviews (target_id VARCHAR(64) PRIMARY KEY, "
            "record JSON NOT NULL, updated_at DATETIME NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO interviews VALUES (?, ?, ?)",
            [
                (record["id"], json.dumps(record), saved_at.isoformat())
                for record in records
            ],
        )
    fixture = project_dir / "experiments/design/complete/inputs/fixtures/policy.pdf"
    fixture.parent.mkdir(parents=True)
    fixture.write_bytes(POLICY)
    specification = None

    for opening in range(2):
        store = Store(database_url(project_dir), project_dir)
        try:
            app = create_app(
                interview_handler=scripted_interview_handler(), store=store
            )
            with TestClient(app) as client:
                before = client.get("/api/v1/targets").json()
                assert {row["id"] for row in before["targets"]} == {
                    "complete",
                    "draft",
                    "unrunnable",
                }
                assert [problem["id"] for problem in before["problems"]] == ["broken"]
                for record in (complete, draft, unrunnable):
                    assert (
                        client.get(f"/api/v1/targets/{record['id']}/interview").json()
                        == record
                    )
                assert (
                    client.get(
                        "/api/v1/targets/complete/interview/files/policy.pdf"
                    ).content
                    == POLICY
                )
                if interrupted and opening == 0:

                    def fail_swap(*_args):
                        raise OSError("Input folder preparation interrupted")

                    with monkeypatch.context() as patch:
                        patch.setattr(input_folder, "swap", fail_swap)
                        with pytest.raises(OSError, match="preparation interrupted"):
                            store.read_specification("complete")
                prepared = client.get("/api/v1/targets/complete/specification")
                assert prepared.status_code == 200, prepared.text
                if specification is None:
                    specification = prepared.json()
                else:
                    assert prepared.json() == specification
                assert (
                    client.get("/api/v1/targets/draft/specification").status_code == 404
                )
                failed = client.get("/api/v1/targets/unrunnable/specification")
                assert failed.status_code == 400, failed.text
                assert failed.json()["code"] == "compilation_failed"
                assert client.get("/api/v1/targets/broken/interview").status_code == 409
                assert client.get("/api/v1/targets").json() == before
        finally:
            store.close()

    assert specification is not None
    input_dir = Path(specification["input_dir"])
    assert (input_dir / "specification.yaml").is_file()
    assert (input_dir / "fixtures/policy.pdf").read_bytes() == POLICY
    assert fixture.read_bytes() == POLICY
    from metis.engine.cli import _validate_inputs as engine_gate

    engine_gate(input_dir)
    engine = create_engine(database_url(project_dir))
    try:
        with engine.connect() as connection:
            stored = list(connection.execute(select(interviews)))
            assert {row.target_id: row.record for row in stored} == {
                record["id"]: record for record in records
            }
            assert all(row.updated_at == saved_at for row in stored)
            filled = list(connection.execute(select(targets)))
            assert {row.id for row in filled} == {"complete", "draft", "unrunnable"}
            assert all(row.updated_at.replace(tzinfo=UTC) == saved_at for row in filled)
    finally:
        engine.dispose()
