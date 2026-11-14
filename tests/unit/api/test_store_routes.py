"""The store routes: Interview files, path safety, and unreadable records."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import create_engine

from metis.api.settings import Settings
from metis.api.store import Store
from metis.api.tables import interviews
from tests.fixtures.api._shared import database_url
from tests.fixtures.api.records import done_state, put_interview, ref, web_record

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

    from metis.api.records import InterviewRecord

TARGET = "20261112-101500-interview"
POLICY = b"policy bytes"


def _files(folder: Path) -> set[Path]:
    return {path for path in folder.rglob("*") if path.is_file()}


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
    assert (
        settings.database_url == f"sqlite:///{tmp_path.resolve()}/experiments/metis.db"
    )

    Store(settings.database_url, settings.project_dir).close()
    assert (tmp_path / "experiments" / "metis.db").is_file()

    monkeypatch.setenv("METIS_DATABASE_URL", "postgresql://metis:secret@db/metis")
    named = Settings.from_env()
    assert named.database_url == "postgresql://metis:secret@db/metis"
    assert "secret" not in repr(named)


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
    folder = project_dir / "experiments" / "design" / TARGET / "inputs" / "fixtures"
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
        patch.setattr(Store, "_save_record", fail)
        failed = put_interview(client, record, parts)

    assert failed.status_code == 500
    assert _files(project_dir) == before
    base = f"/api/v1/targets/{TARGET}/interview/files"
    assert client.get(f"{base}/policy.pdf").content == POLICY

    assert put_interview(client, record, parts).status_code == 204
    assert client.get(f"{base}/policy.pdf").content == changed
    folder = project_dir / "experiments" / "design" / TARGET / "inputs" / "fixtures"
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
    folder = project_dir / "experiments" / "design" / TARGET / "inputs" / "fixtures"
    at_save: dict[str, bytes] = {}
    save_record = Store._save_record

    def save(store: Store, target_id: str, saved: InterviewRecord) -> None:
        for name in ("policy.pdf", "extra.txt"):
            at_save[name] = (folder / name).read_bytes()
        save_record(store, target_id, saved)

    monkeypatch.setattr(Store, "_save_record", save)
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
            ref("page.html", page, "text/html"),
            ref("odd.txt", b"odd", "text/plain\r\nSet-Cookie: a=b"),
        ],
    )
    saved = put_interview(
        client,
        record,
        [
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
    record = web_record(TARGET, done_state())
    record["transcript"][0]["description"] = "A tool. " * 200_000

    saved = put_interview(client, record)

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


def test_a_save_into_a_cli_folder_gets_409_and_changes_nothing(
    client: TestClient, project_dir: Path
) -> None:
    fixture = (
        project_dir
        / "experiments"
        / "design"
        / TARGET
        / "inputs"
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


def test_an_unsafe_target_id_gets_400_and_writes_nothing(
    client: TestClient, project_dir: Path
) -> None:
    _saved(client)
    before = _files(project_dir)
    record = web_record("bad.id", done_state())

    response = put_interview(client, record)

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"
    assert _files(project_dir) == before


def test_a_row_that_no_longer_validates_is_a_problem_in_the_list(
    client: TestClient, project_dir: Path
) -> None:
    _saved(client)
    broken = web_record("broken", done_state())
    broken["state"]["specification"]["target"] = {"product": "an older shape"}
    now = datetime.now(UTC)
    with create_engine(database_url(project_dir)).begin() as connection:
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


def test_a_deleted_interview_loses_its_record_and_uploaded_files(
    client: TestClient, project_dir: Path
) -> None:
    _saved(client)

    assert client.delete(f"/api/v1/targets/{TARGET}").status_code == 204

    assert client.get("/api/v1/targets").json() == {"targets": [], "problems": []}
    assert client.get(f"/api/v1/targets/{TARGET}/interview").status_code == 404
    assert not (project_dir / "experiments" / "design" / TARGET).exists()
