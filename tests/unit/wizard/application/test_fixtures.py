from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from metis.wizard.application.fixtures import (
    FixtureError,
    FixtureLibrary,
    normalize_upload_name,
)
from metis.wizard.domain.documents import (
    FIXTURE_DOCUMENT_EXTENSIONS,
    MAX_DOCUMENT_BYTES,
)


@pytest.mark.parametrize("extension", sorted(FIXTURE_DOCUMENT_EXTENSIONS))
def test_every_accepted_extension_is_case_insensitive(extension: str) -> None:
    assert (
        normalize_upload_name(f"sample.{extension.upper()}")
        == f"sample.{extension.upper()}"
    )


@pytest.mark.parametrize(
    "name",
    [
        "",
        ".",
        "..",
        "folder/file.txt",
        r"folder\file.txt",
        "/tmp/file.txt",
        "file?.txt",
    ],
)
def test_unsafe_fixture_names_are_rejected(name: str) -> None:
    with pytest.raises(FixtureError):
        normalize_upload_name(name)


def test_library_uploads_are_atomic(tmp_path: Path) -> None:
    library = FixtureLibrary(tmp_path / "fixtures")
    library.upload([("good.txt", BytesIO(b"ok"))])

    with pytest.raises(FixtureError):
        library.upload([("new.txt", BytesIO(b"new")), ("bad.exe", BytesIO(b"bad"))])

    assert [item.name for item in library.list()] == ["good.txt"]


def test_markdown_and_html_are_stored_as_opaque_fixture_bytes(tmp_path: Path) -> None:
    library = FixtureLibrary(tmp_path / "fixtures")
    library.upload(
        [
            ("notes.md", BytesIO(b"# notes")),
            ("page.html", BytesIO(b"<script>opaque</script>")),
        ]
    )

    assert library.path_for("notes.md").read_bytes() == b"# notes"
    assert library.path_for("page.html").read_bytes() == b"<script>opaque</script>"


def test_library_rejects_case_folded_collisions(tmp_path: Path) -> None:
    library = FixtureLibrary(tmp_path / "fixtures")
    library.upload([("Report.TXT", BytesIO(b"one"))])

    with pytest.raises(FixtureError, match="already exists"):
        library.upload([("report.txt", BytesIO(b"two"))])


def test_library_reuses_identical_case_folded_uploads(tmp_path: Path) -> None:
    library = FixtureLibrary(tmp_path / "fixtures")
    library.upload([("Report.TXT", BytesIO(b"one"))])

    added = library.upload([("report.txt", BytesIO(b"one"))])

    assert [item.model_dump() for item in added] == [{"name": "Report.TXT", "size": 3}]
    assert [item.name for item in library.list()] == ["Report.TXT"]


def test_library_enforces_file_count_and_total_bytes(tmp_path: Path) -> None:
    library = FixtureLibrary(tmp_path / "fixtures")
    # One upload just below the limit is valid. The next one crosses it.
    library.upload([("one.txt", BytesIO(b"x" * (MAX_DOCUMENT_BYTES - 1)))])

    with pytest.raises(FixtureError, match="bytes"):
        library.upload([("two.txt", BytesIO(b"xx"))])


def test_library_instances_are_isolated(tmp_path: Path) -> None:
    first = FixtureLibrary(tmp_path / "one" / "fixtures")
    second = FixtureLibrary(tmp_path / "two" / "fixtures")
    first.upload([("shared.txt", BytesIO(b"one"))])
    second.upload([("shared.txt", BytesIO(b"two"))])

    assert first.path_for("shared.txt").read_bytes() == b"one"
    assert second.path_for("shared.txt").read_bytes() == b"two"


def test_delete_refuses_referenced_fixture(tmp_path: Path) -> None:
    library = FixtureLibrary(tmp_path / "fixtures")
    library.upload([("policy.md", BytesIO(b"policy"))])

    with pytest.raises(FixtureError, match="still referenced"):
        library.delete("policy.md", referenced=["policy.md"])

    library.delete("policy.md")
    assert library.list() == []
