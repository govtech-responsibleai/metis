"""The store routes: Interview files, path safety, unreadable rows, and Experiment rows."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import create_engine

from metis.api.settings import Settings
from metis.api.store import STATE, Store
from metis.api.tables import interviews, targets
from metis.wizard import InterviewState
from metis.wizard.application import export_layout
from tests.fixtures.api._shared import database_url
from tests.fixtures.api.records import done_state, put_interview, ref, web_record

if TYPE_CHECKING:
    from collections.abc import Mapping

    from fastapi.testclient import TestClient

    from metis.api.records import InterviewRecord

TARGET = "20261112-101500-interview"
POLICY = b"policy bytes"


def _files(folder: Path) -> set[Path]:
    return {path for path in folder.rglob("*") if path.is_file()}


def _experiment_folder(project_dir: Path, experiment_id: str) -> Path:
    folder = project_dir / "experiments" / "execute" / experiment_id
    (folder / "inputs").mkdir(parents=True)
    (folder / "inputs" / "specification.yaml").write_text("id: research-assistant\n")
    return folder


def _saved(client: TestClient) -> None:
    record = web_record(
        TARGET, done_state(), fixtures=[ref("policy.pdf", POLICY, "application/pdf")]
    )
    response = put_interview(
        client, record, [("files", ("policy.pdf", POLICY, "application/pdf"))]
    )
    assert response.status_code == 204, response.text


def test_the_store_defaults_to_a_sqlite_file_in_the_experiments_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = Settings.from_env(project_dir=tmp_path)
    assert settings.project_dir == tmp_path.resolve()
    assert settings.database_url == f"sqlite:///{tmp_path.resolve()}/metis.db"

    Store(settings.database_url, settings.project_dir).close()
    assert (tmp_path / "metis.db").is_file()

    monkeypatch.setenv("METIS_DATABASE_URL", "postgresql://metis:secret@db/metis")
    named = Settings.from_env()
    assert named.database_url == "postgresql://metis:secret@db/metis"
    assert "secret" not in repr(named)


def test_the_state_of_an_interview_is_the_file_that_the_wizard_cli_uses(
    client: TestClient, project_dir: Path
) -> None:
    _saved(client)
    state_file = (
        project_dir / "experiments" / "design" / TARGET / export_layout.INTERVIEW_STATE
    )

    assert InterviewState.model_validate_json(state_file.read_text()) == done_state()

    reopened = done_state()
    reopened.confirmed = False
    state_file.write_text(reopened.model_dump_json())

    read = client.get(f"/api/v1/targets/{TARGET}/interview").json()
    assert InterviewState.model_validate(read["state"]) == reopened
    assert len(read["transcript"]) == 2


def test_a_save_keeps_only_the_files_that_the_record_refers_to(
    client: TestClient, project_dir: Path
) -> None:
    notes = b"reply notes"
    record = web_record(
        TARGET,
        done_state(),
        fixtures=[
            ref("policy.pdf", POLICY, "application/pdf"),
            ref("old.txt", b"old", "text/plain"),
        ],
        outbound=[ref("notes.txt", notes, "text/plain")],
    )
    first = put_interview(
        client,
        record,
        [
            ("files", ("policy.pdf", POLICY, "application/pdf")),
            ("files", ("old.txt", b"old", "text/plain")),
            ("files", ("notes.txt", notes, "text/plain")),
        ],
    )
    assert first.status_code == 204, first.text
    base = f"/api/v1/targets/{TARGET}/interview/files"
    reply = client.get(f"{base}/notes.txt")
    assert reply.content == notes
    assert reply.headers["content-type"].startswith("text/plain")

    record["fixtures"] = [ref("policy.pdf", POLICY, "application/pdf")]
    second = put_interview(client, record)

    assert second.status_code == 204, second.text
    assert client.get(f"{base}/policy.pdf").content == POLICY
    assert client.get(f"{base}/old.txt").status_code == 404
    folder = project_dir / "experiments" / "design" / TARGET / "inputs" / "documents"
    assert sorted(path.name for path in folder.iterdir()) == ["notes.txt", "policy.pdf"]


def test_a_save_that_fails_changes_no_file_of_the_saved_record(
    make_client, project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = make_client(raise_server_exceptions=False)
    _saved(client)
    before = _files(project_dir)
    changed = b"changed policy bytes"
    record = web_record(
        TARGET,
        done_state(),
        fixtures=[
            ref("policy.pdf", changed, "application/pdf"),
            ref("extra.txt", b"extra", "text/plain"),
        ],
    )
    parts = [
        ("files", ("policy.pdf", changed, "application/pdf")),
        ("files", ("extra.txt", b"extra", "text/plain")),
    ]

    def fail(*_: object) -> None:
        raise OSError("The database is not available.")

    with monkeypatch.context() as patch:
        patch.setattr(Store, "_save_rows", fail)
        failed = put_interview(client, record, parts)

    assert failed.status_code == 500
    assert _files(project_dir) == before
    base = f"/api/v1/targets/{TARGET}/interview/files"
    assert client.get(f"{base}/policy.pdf").content == POLICY

    assert put_interview(client, record, parts).status_code == 204
    assert client.get(f"{base}/policy.pdf").content == changed
    folder = project_dir / "experiments" / "design" / TARGET / "inputs" / "documents"
    assert sorted(path.name for path in folder.iterdir()) == ["extra.txt", "policy.pdf"]


def test_every_file_is_in_place_when_the_record_is_saved(
    client: TestClient, project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _saved(client)
    changed = b"changed policy bytes"
    record = web_record(
        TARGET,
        done_state(),
        fixtures=[
            ref("policy.pdf", changed, "application/pdf"),
            ref("extra.txt", b"extra", "text/plain"),
        ],
    )
    folder = project_dir / "experiments" / "design" / TARGET / "inputs" / "documents"
    at_save: dict[str, bytes] = {}
    save_rows = Store._save_rows

    def save(
        store: Store,
        target_id: str,
        saved: InterviewRecord,
        specification: Mapping[str, bytes] | None,
    ) -> None:
        for name in ("policy.pdf", "extra.txt"):
            at_save[name] = (folder / name).read_bytes()
        save_rows(store, target_id, saved, specification)

    monkeypatch.setattr(Store, "_save_rows", save)
    response = put_interview(
        client,
        record,
        [
            ("files", ("policy.pdf", changed, "application/pdf")),
            ("files", ("extra.txt", b"extra", "text/plain")),
        ],
    )

    assert response.status_code == 204, response.text
    assert at_save == {"policy.pdf": changed, "extra.txt": b"extra"}
    assert sorted(path.name for path in folder.iterdir()) == ["extra.txt", "policy.pdf"]


def test_a_file_is_a_download_that_a_browser_does_not_show_as_a_page(
    client: TestClient,
) -> None:
    page = b"<script>fetch('/api/v1/targets')</script>"
    record = web_record(
        TARGET,
        done_state(),
        fixtures=[
            ref("policy.pdf", POLICY, "application/pdf"),
            ref("page.html", page, "text/html"),
            ref("odd.txt", b"odd", "text/plain\r\nSet-Cookie: a=b"),
        ],
    )
    saved = put_interview(
        client,
        record,
        [
            ("files", ("policy.pdf", POLICY, "application/pdf")),
            ("files", ("page.html", page, "text/html")),
            ("files", ("odd.txt", b"odd", "text/plain")),
        ],
    )
    assert saved.status_code == 204, saved.text
    base = f"/api/v1/targets/{TARGET}/interview/files"

    read = client.get(f"{base}/page.html")

    assert read.content == page
    assert read.headers["content-disposition"] == 'attachment; filename="page.html"'
    assert read.headers["x-content-type-options"] == "nosniff"
    assert read.headers["cache-control"] == "no-store"
    odd = client.get(f"{base}/odd.txt")
    assert odd.content == b"odd"
    assert odd.headers["content-type"] == "application/octet-stream"
    assert "set-cookie" not in odd.headers


def test_a_save_accepts_a_record_larger_than_a_megabyte(client: TestClient) -> None:
    record = web_record(
        TARGET, done_state(), fixtures=[ref("policy.pdf", POLICY, "application/pdf")]
    )
    record["transcript"][0]["description"] = "A tool. " * 200_000

    saved = put_interview(
        client, record, [("files", ("policy.pdf", POLICY, "application/pdf"))]
    )

    assert saved.status_code == 204, saved.text
    read = client.get(f"/api/v1/targets/{TARGET}/interview").json()
    assert (
        read["transcript"][0]["description"] == record["transcript"][0]["description"]
    )


def test_a_reference_to_a_file_that_was_never_uploaded_gets_400_and_changes_nothing(
    client: TestClient, project_dir: Path
) -> None:
    record = web_record(
        TARGET, done_state(), fixtures=[ref("policy.pdf", POLICY, "application/pdf")]
    )
    before = _files(project_dir)

    response = put_interview(client, record)

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"
    assert _files(project_dir) == before
    assert client.get("/api/v1/targets").json()["targets"] == []


def test_a_save_with_the_id_of_another_interview_gets_409_and_changes_nothing(
    client: TestClient, project_dir: Path
) -> None:
    _saved(client)
    stored = client.get(f"/api/v1/targets/{TARGET}/interview").json()
    listed = client.get("/api/v1/targets").json()
    before = _files(project_dir)
    other = web_record(
        TARGET, done_state(), fixtures=[ref("other.txt", b"other", "text/plain")]
    )
    other["created_at"] = stored["created_at"] + 1

    response = put_interview(
        client, other, [("files", ("other.txt", b"other", "text/plain"))]
    )

    assert response.status_code == 409
    assert response.json()["code"] == "target_exists"
    assert _files(project_dir) == before
    assert client.get(f"/api/v1/targets/{TARGET}/interview").json() == stored
    assert client.get("/api/v1/targets").json() == listed
    assert put_interview(client, stored).status_code == 204


def test_two_files_whose_names_differ_only_by_case_get_400_and_change_nothing(
    client: TestClient, project_dir: Path
) -> None:
    _saved(client)
    stored = client.get(f"/api/v1/targets/{TARGET}/interview").json()
    before = _files(project_dir)
    record = web_record(
        TARGET,
        done_state(),
        fixtures=[ref("policy.pdf", POLICY, "application/pdf")],
        outbound=[ref("POLICY.pdf", b"answer", "application/pdf")],
    )

    response = put_interview(
        client, record, [("files", ("POLICY.pdf", b"answer", "application/pdf"))]
    )

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"
    assert "two files named POLICY.pdf" in response.json()["message"]
    assert _files(project_dir) == before
    assert client.get(f"/api/v1/targets/{TARGET}/interview").json() == stored


def test_an_interview_folder_of_the_wizard_cli_is_a_target_of_the_store(
    client: TestClient, project_dir: Path
) -> None:
    folder = project_dir / "experiments" / "design" / TARGET
    state = done_state()
    state_file = folder / export_layout.INTERVIEW_STATE
    state_file.parent.mkdir(parents=True)
    state_file.write_text(state.model_dump_json())
    document = folder / export_layout.DOCUMENTS / "policy.pdf"
    document.parent.mkdir()
    document.write_bytes(POLICY)

    listed = client.get("/api/v1/targets").json()

    assert [(row["id"], row["title"]) for row in listed["targets"]] == [
        (TARGET, "Research assistant")
    ]
    record = client.get(f"/api/v1/targets/{TARGET}/interview").json()
    assert InterviewState.model_validate(record["state"]) == state
    assert record["transcript"] == []
    assert record["fixtures"] == [ref("policy.pdf", POLICY, "application/pdf")]
    base = f"/api/v1/targets/{TARGET}"
    assert client.get(f"{base}/interview/files/policy.pdf").content == POLICY
    assert client.get(f"{base}/specification").status_code == 200
    assert put_interview(client, record).status_code == 204


def test_a_save_into_a_folder_with_no_interview_state_gets_409_and_changes_nothing(
    client: TestClient, project_dir: Path
) -> None:
    fixture = (
        project_dir
        / "experiments"
        / "design"
        / TARGET
        / "outputs"
        / "fixtures"
        / "a.txt"
    )
    fixture.parent.mkdir(parents=True)
    fixture.write_bytes(b"cli file")
    before = _files(project_dir)

    response = put_interview(client, web_record(TARGET, done_state()))

    assert response.status_code == 409
    assert response.json()["code"] == "target_exists"
    assert _files(project_dir) == before
    assert client.delete(f"/api/v1/targets/{TARGET}").status_code == 404
    assert fixture.read_bytes() == b"cli file"


@pytest.mark.parametrize(
    "name",
    [
        "../escape.txt",
        "sub/escape.txt",
        "..",
        "a\\b.txt",
        'report "final".pdf',
        "two\nlines.txt",
        "a<b>.txt",
        "what?.txt",
        "notes.",
        "notes ",
        "CON",
        "com1.csv",
    ],
)
def test_a_file_name_that_is_not_portable_gets_400_and_writes_nothing(
    client: TestClient, project_dir: Path, name: str
) -> None:
    record = web_record(TARGET, done_state(), fixtures=[ref(name, b"x", "text/plain")])
    before = _files(project_dir)

    response = put_interview(client, record, [("files", (name, b"x", "text/plain"))])

    assert response.status_code == 400
    assert _files(project_dir) == before
    assert not (project_dir / "experiments" / "design" / "escape.txt").exists()


def test_an_unsafe_target_id_or_experiment_id_gets_400_and_writes_nothing(
    client: TestClient, project_dir: Path
) -> None:
    _saved(client)
    before = _files(project_dir)

    record = web_record("bad.id", done_state())
    assert put_interview(client, record).status_code == 400
    response = client.put(
        "/api/v1/experiments/..", json={"target_id": TARGET, "step": "simulate"}
    )
    assert response.status_code in (400, 404)
    response = client.put(
        "/api/v1/experiments/.hidden", json={"target_id": TARGET, "step": "simulate"}
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"
    assert _files(project_dir) == before


def test_a_specification_that_does_not_compile_gets_400_and_keeps_the_store(
    client: TestClient, project_dir: Path
) -> None:
    _saved(client)
    specification = client.get(f"/api/v1/targets/{TARGET}/specification").json()
    before = _files(project_dir)
    record = web_record(TARGET, done_state())  # the done state needs policy.pdf

    response = put_interview(client, record)

    assert response.status_code == 400
    assert response.json()["code"] == "compilation_failed"
    assert _files(project_dir) == before
    assert client.get(f"/api/v1/targets/{TARGET}/specification").json() == specification
    stored = client.get(f"/api/v1/targets/{TARGET}/interview").json()
    assert [fixture["name"] for fixture in stored["fixtures"]] == ["policy.pdf"]


def test_a_row_that_no_longer_validates_is_a_problem_in_the_list(
    client: TestClient, project_dir: Path
) -> None:
    _saved(client)
    broken = web_record("broken", done_state())
    state = broken.pop("state")
    state["specification"]["target"] = {"product": "an older shape"}
    state_file = project_dir / "experiments" / "design" / "broken" / STATE
    state_file.parent.mkdir(parents=True)
    state_file.write_text(json.dumps(state))
    now = datetime.now(UTC)
    with create_engine(database_url(project_dir)).begin() as connection:
        connection.execute(
            targets.insert().values(
                id="broken", name="old", created_at=now, updated_at=now
            )
        )
        connection.execute(
            interviews.insert().values(
                target_id="broken", record=broken, updated_at=now
            )
        )

    listed = client.get("/api/v1/targets").json()

    assert [row["id"] for row in listed["targets"]] == [TARGET]
    assert listed["targets"][0]["title"] == "Research assistant"
    assert [problem["id"] for problem in listed["problems"]] == ["broken"]
    assert client.get("/api/v1/targets/broken/interview").status_code == 409
    assert client.delete("/api/v1/targets/broken").status_code == 204
    assert client.get("/api/v1/targets").json()["problems"] == []


def test_an_experiment_row_keeps_its_step_and_needs_its_folder(
    client: TestClient, project_dir: Path
) -> None:
    _saved(client)
    experiment_id = "research-assistant-20261110-101500"
    _experiment_folder(project_dir, experiment_id)

    missing = client.put(
        "/api/v1/experiments/no-such-experiment",
        json={"target_id": TARGET, "step": "simulate"},
    )
    started = client.put(
        f"/api/v1/experiments/{experiment_id}",
        json={"target_id": TARGET, "step": "simulate"},
    )
    evaluated = client.put(
        f"/api/v1/experiments/{experiment_id}",
        json={"target_id": TARGET, "step": "evaluate"},
    )

    assert missing.status_code == 400
    assert missing.json()["code"] == "validation_error"
    assert "experiments/execute/no-such-experiment" in missing.json()["message"]
    assert started.status_code == 200, started.text
    assert evaluated.json() == {**started.json(), "step": "evaluate"}
    assert client.get(f"/api/v1/experiments/{experiment_id}").json() == evaluated.json()
    listed = client.get(f"/api/v1/targets/{TARGET}/experiments").json()["experiments"]
    assert [row["experiment_id"] for row in listed] == [experiment_id]


def test_a_deleted_experiment_has_no_row_and_its_folder_stays(
    client: TestClient, project_dir: Path
) -> None:
    _saved(client)
    experiment_id = "research-assistant-20261110-101500"
    folder = _experiment_folder(project_dir, experiment_id)
    client.put(
        f"/api/v1/experiments/{experiment_id}",
        json={"target_id": TARGET, "step": "simulate"},
    )

    assert client.delete(f"/api/v1/experiments/{experiment_id}").status_code == 204

    assert client.get(f"/api/v1/experiments/{experiment_id}").status_code == 404
    assert (
        client.get(f"/api/v1/targets/{TARGET}/experiments").json()["experiments"] == []
    )
    assert (folder / "inputs" / "specification.yaml").is_file()


def test_a_deleted_target_loses_its_rows_and_design_folder_and_keeps_its_experiments(
    client: TestClient, project_dir: Path
) -> None:
    _saved(client)
    experiment_id = "research-assistant-20261110-101500"
    folder = _experiment_folder(project_dir, experiment_id)
    client.put(
        f"/api/v1/experiments/{experiment_id}",
        json={"target_id": TARGET, "step": "simulate"},
    )

    assert client.delete(f"/api/v1/targets/{TARGET}").status_code == 204

    assert client.get("/api/v1/targets").json() == {"targets": [], "problems": []}
    assert client.get(f"/api/v1/targets/{TARGET}/interview").status_code == 404
    assert client.get(f"/api/v1/targets/{TARGET}/specification").status_code == 404
    assert client.get(f"/api/v1/experiments/{experiment_id}").status_code == 404
    assert not (project_dir / "experiments" / "design" / TARGET).exists()
    assert (folder / "inputs" / "specification.yaml").is_file()
