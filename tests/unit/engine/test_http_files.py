"""The generic HTTP runner's fetch_files tool (#525)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import pytest

from metis.core.trials import TrialConfig
from metis.engine.simulation._fixture_artifacts import build_fixture_artifacts
from metis.engine.simulation.artifacts import ArtifactLedger
from metis.engine.simulation.binding import load_target_binding
from metis.engine.simulation.evidence import Pointer, PointerError
from metis.engine.simulation.runners.http import (
    MAX_FILES_PER_LISTING,
    HttpRunner,
    HttpRunnerFactory,
)
from metis.engine.simulation.runners.rules import ToolRefused

if TYPE_CHECKING:
    from pathlib import Path

SPEC_URL = "https://app.example/openapi.json"
_BINDING = f"schema_version: 1\nidentity: {{name: App}}\ntransport: http\nspec_url: {SPEC_URL}\n"
PDF = b"%PDF-1.7\n"
DOWNLOAD = "/files/{id}/content"


class Target:
    """A fake app: a chat, an upload, a session's file listing, an account-wide one."""

    def __init__(self) -> None:
        self.listing: list[dict[str, Any]] = []
        self.blobs: dict[str, httpx.Response] = {}
        self.downloads: list[str] = []
        self.uploads: list[bytes] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/openapi.json":
            return httpx.Response(200, json={"servers": [{"url": "/api/v1"}]})
        if path == "/api/v1/chat":
            return httpx.Response(201, json={"sessionId": "s-1", "reply": "see a.pdf"})
        if path == "/api/v1/upload":
            self.uploads.append(request.read())
            return httpx.Response(200, json={"fileId": "up-1"})
        if path in ("/api/v1/sessions/s-1/files", "/api/v1/files"):
            return httpx.Response(200, json={"files": self.listing})
        if path.startswith("/api/v1/files/") and path.endswith("/content"):
            file_id = path.split("/")[4]
            self.downloads.append(file_id)
            return self.blobs.get(file_id, httpx.Response(404, json={"error": "no"}))
        return httpx.Response(404)


def _file(file_id: str | None, name: str = "a.pdf", **more: Any) -> dict[str, Any]:
    return {"id": file_id, "name": name, **more}


async def _ready(tmp_path: Path, extra: str = "") -> tuple[HttpRunner, Target]:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "app.yaml").write_text(_BINDING + extra, encoding="utf-8")
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "fixtures" / "notes.txt").write_text("hello", encoding="utf-8")
    held = build_fixture_artifacts(["notes.txt"], tmp_path / "fixtures", tmp_path)
    target = Target()
    factory = HttpRunnerFactory(
        load_target_binding(inputs, "app.yaml"), transport=httpx.MockTransport(target)
    )
    await factory.start()
    runner = await factory.create(tmp_path / "trial", tmp_path / "fixtures", tmp_path)
    runner.use_ledger(ArtifactLedger(tmp_path, tmp_path / "trial", held))
    await runner.setup(TrialConfig(persona="p", scenario="s"))
    return runner, target


async def _session_listing(runner: HttpRunner, target: Target, *files: Any) -> Pointer:
    """Open the conversation, learn its session ID and list its files."""
    target.listing = list(files)
    runner.begin_action("Say ⟦hi⟧")
    chat = await runner.http_request("POST", "/chat", json={"text": "{{1}}"})
    runner.record_session_id(Pointer(chat["response_entry"], "$.sessionId"))
    listed = await runner.http_request("GET", "/sessions/s-1/files")
    return Pointer(listed["response_entry"], "$.files")


async def _fetch(runner: HttpRunner, listing: Pointer, **more: Any) -> dict[str, Any]:
    args = {"id_key": "id", "name_key": "name", "download_path": DOWNLOAD, **more}
    return await runner.fetch_files(listing, **args)


def _states(runner: HttpRunner) -> list[tuple[str, str]]:
    return [
        (a.name, a.state) for a in runner.ledger.artifacts() if a.source == "target"
    ]


@pytest.mark.asyncio
async def test_each_listed_file_is_one_real_download_recorded_with_its_turn(
    tmp_path: Path,
) -> None:
    runner, target = await _ready(tmp_path)
    target.blobs = {
        "1": httpx.Response(200, content=PDF),
        "2": httpx.Response(200, content=b"a,b\n1,2\n"),
    }
    listing = await _session_listing(runner, target, _file("1"), _file("2", "d.csv"))

    result = await _fetch(runner, listing)

    assert target.downloads == ["1", "2"]
    assert [(f["name"], f["outcome"]) for f in result["files"]] == [
        ("a.pdf", "received"),
        ("d.csv", "received"),
    ]
    assert result["listing"] == listing.entry
    first, _ = (a for a in runner.ledger.artifacts() if a.source == "target")
    assert (first.external_id, first.at_simulated_turn, first.state) == (
        "1",
        1,
        "received",
    )
    entry = runner._log.get(result["files"][0]["entry"])
    assert entry.summary == "GET /api/v1/files/1/content -> 200"


@pytest.mark.asyncio
async def test_bytes_of_the_wrong_type_are_refused_and_recorded_unfetched(
    tmp_path: Path,
) -> None:
    runner, target = await _ready(tmp_path)
    target.blobs = {"1": httpx.Response(200, content=b"just a chat reply")}
    listing = await _session_listing(runner, target, _file("1"))

    result = await _fetch(runner, listing)

    assert result["files"][0]["outcome"] == "unfetched"
    (entry,) = (a for a in runner.ledger.artifacts() if a.source == "target")
    assert entry.state == "unfetched"
    assert entry.path is None
    assert "not a .pdf file" in (entry.state_description or "")


@pytest.mark.asyncio
async def test_a_404_is_recorded_unfetched_with_the_reason(tmp_path: Path) -> None:
    runner, target = await _ready(tmp_path)
    listing = await _session_listing(runner, target, _file("9"))

    result = await _fetch(runner, listing)

    assert result["files"][0]["outcome"] == "unfetched"
    (entry,) = (a for a in runner.ledger.artifacts() if a.source == "target")
    assert (entry.state, entry.external_id) == ("unfetched", "9")
    assert "404" in (entry.state_description or "")


@pytest.mark.asyncio
async def test_a_file_listed_without_an_id_is_unavailable_once(tmp_path: Path) -> None:
    runner, target = await _ready(tmp_path)
    listing = await _session_listing(runner, target, _file(None))

    first = await _fetch(runner, listing)
    await _fetch(runner, listing)

    assert first["files"][0]["outcome"] == "unavailable"
    assert target.downloads == []
    assert _states(runner) == [("a.pdf", "unavailable")]


@pytest.mark.asyncio
async def test_an_account_wide_listing_is_refused(tmp_path: Path) -> None:
    runner, target = await _ready(tmp_path)
    await _session_listing(runner, target, _file("1"))
    wide = await runner.http_request("GET", "/files")

    with pytest.raises(ToolRefused, match="list the session's own files"):
        await _fetch(runner, Pointer(wide["response_entry"], "$.files"))

    assert target.downloads == []
    assert _states(runner) == []


@pytest.mark.asyncio
async def test_a_short_session_id_does_not_match_inside_another_path_segment(
    tmp_path: Path,
) -> None:
    runner, target = await _ready(tmp_path)
    await _session_listing(runner, target, _file("1"))
    runner._session_id = "1"  # would match "/api/v1/files" as a substring
    wide = await runner.http_request("GET", "/files")

    with pytest.raises(ToolRefused, match="list the session's own files"):
        await _fetch(runner, Pointer(wide["response_entry"], "$.files"))


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["$.reply", "$"])
async def test_a_reply_cited_as_a_listing_is_refused(tmp_path: Path, path: str) -> None:
    runner, target = await _ready(tmp_path)
    runner.begin_action("Say ⟦hi⟧")
    chat = await runner.http_request("POST", "/chat", json={"text": "{{1}}"})

    with pytest.raises(ToolRefused, match="array of files"):
        await _fetch(runner, Pointer(chat["response_entry"], path))

    assert _states(runner) == []
    assert target.downloads == []


@pytest.mark.asyncio
async def test_an_entry_the_agent_may_not_cite_is_a_pointer_error(
    tmp_path: Path,
) -> None:
    runner, _ = await _ready(tmp_path)

    with pytest.raises(PointerError):
        await _fetch(runner, Pointer(runner.spec_entry, "$.servers"))


@pytest.mark.asyncio
async def test_a_listing_over_the_cap_is_refused_whole(tmp_path: Path) -> None:
    runner, target = await _ready(tmp_path)
    files = [_file(str(i), f"f{i}.txt") for i in range(MAX_FILES_PER_LISTING + 1)]
    listing = await _session_listing(runner, target, *files)

    with pytest.raises(ToolRefused, match=str(MAX_FILES_PER_LISTING)):
        await _fetch(runner, listing)

    assert target.downloads == []
    assert _states(runner) == []


@pytest.mark.asyncio
async def test_a_file_already_held_is_not_downloaded_again(tmp_path: Path) -> None:
    runner, target = await _ready(tmp_path)
    target.blobs = {"1": httpx.Response(200, content=PDF)}
    listing = await _session_listing(runner, target, _file("1"))
    await _fetch(runner, listing)

    again = await _fetch(runner, listing)

    assert target.downloads == ["1"]
    assert again["files"] == [
        {"name": "a.pdf", "outcome": "skipped", "why": "already held"}
    ]


@pytest.mark.asyncio
async def test_the_users_own_upload_is_skipped_once_its_id_is_captured(
    tmp_path: Path,
) -> None:
    runner, target = await _ready(tmp_path)
    target.blobs = {"1": httpx.Response(200, content=PDF)}
    runner.begin_action("Send ⟦notes⟧")
    upload = await runner.http_request(
        "POST", "/upload", multipart={"file": "@notes.txt"}, file_id_from="$.fileId"
    )
    listing = await _session_listing(
        runner, target, _file("up-1", "notes.txt"), _file("1")
    )

    result = await _fetch(runner, listing)

    assert upload["file_id"] == "up-1"
    assert target.downloads == ["1"]
    assert result["files"][0] == {
        "name": "notes.txt",
        "outcome": "skipped",
        "why": "the user's own upload",
    }
    assert _states(runner) == [("a.pdf", "received")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "media_type"),
    [
        ("report.md", "text/markdown"),
        ("report.MARKDOWN", "text/markdown"),
        ("notes.txt", "text/plain"),
        ("blob.unknownext", "application/octet-stream"),
    ],
)
async def test_an_upload_is_typed_from_its_extension(
    tmp_path: Path, name: str, media_type: str
) -> None:
    runner, target = await _ready(tmp_path)
    (tmp_path / "fixtures" / name).write_text("x", encoding="utf-8")
    held = build_fixture_artifacts([name], tmp_path / "fixtures", tmp_path)
    runner.use_ledger(ArtifactLedger(tmp_path, tmp_path / "trial", held))
    runner.begin_action("Send ⟦notes⟧")

    await runner.http_request("POST", "/upload", multipart={"file": f"@{name}"})

    assert f"Content-Type: {media_type}".encode() in target.uploads[-1]


@pytest.mark.asyncio
async def test_a_non_text_multipart_value_is_refused_and_nothing_is_sent(
    tmp_path: Path,
) -> None:
    runner, target = await _ready(tmp_path)

    with pytest.raises(ToolRefused, match="multipart part 'file' must be text"):
        await runner.http_request(
            "POST",
            "/upload",
            multipart={"file": {"media_type": "text/markdown"}},  # type: ignore[dict-item]
        )

    assert target.uploads == []


@pytest.mark.asyncio
async def test_a_plain_text_multipart_value_is_still_sent(tmp_path: Path) -> None:
    runner, target = await _ready(tmp_path)
    runner.begin_action("Send ⟦notes⟧")

    await runner.http_request("POST", "/upload", multipart={"note": "hello"})

    assert b"hello" in target.uploads[-1]


@pytest.mark.asyncio
async def test_file_id_from_needs_exactly_one_held_file(tmp_path: Path) -> None:
    runner, _ = await _ready(tmp_path)

    with pytest.raises(ToolRefused, match="file_id_from"):
        await runner.http_request("POST", "/upload", json={}, file_id_from="$.fileId")


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_id", ["a/b", "..", "x/../y"])
async def test_an_id_that_is_not_one_path_segment_is_skipped(
    tmp_path: Path, bad_id: str
) -> None:
    runner, target = await _ready(tmp_path)
    listing = await _session_listing(runner, target, _file(bad_id))

    result = await _fetch(runner, listing)

    assert result["files"][0]["outcome"] == "skipped"
    assert target.downloads == []
    assert _states(runner) == []


@pytest.mark.asyncio
async def test_only_items_with_the_given_values_are_fetched(tmp_path: Path) -> None:
    runner, target = await _ready(tmp_path)
    target.blobs = {"2": httpx.Response(200, content=PDF)}
    listing = await _session_listing(
        runner,
        target,
        _file("1", "u.pdf", kind="upload"),
        _file("2", "r.pdf", kind="output"),
    )

    result = await _fetch(runner, listing, where={"kind": "output"})

    assert target.downloads == ["2"]
    assert [f["name"] for f in result["files"]] == ["r.pdf"]


@pytest.mark.asyncio
async def test_a_forbidden_download_path_is_refused(tmp_path: Path) -> None:
    runner, target = await _ready(
        tmp_path, "forbidden_calls: ['GET /files/*/content']\n"
    )
    listing = await _session_listing(runner, target, _file("1"))

    with pytest.raises(ToolRefused, match="forbidden by the target binding"):
        await _fetch(runner, listing)

    assert target.downloads == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/files/content", "/files/{id}/x/{id}"])
async def test_the_download_path_needs_exactly_one_id(
    tmp_path: Path, path: str
) -> None:
    runner, target = await _ready(tmp_path)
    listing = await _session_listing(runner, target, _file("1"))

    with pytest.raises(ToolRefused, match=r"exactly one \{id\}"):
        await _fetch(runner, listing, download_path=path)
