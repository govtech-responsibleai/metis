from __future__ import annotations

import io
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
import yaml

from metis.wizard import SpecificationFixture, package_specification
from metis.wizard.application.compile import (
    SpecificationError,
    build_specification_archive,
    write_specification,
)
from metis.wizard.application.compile import specification as specification_module
from metis.wizard.contracts import Specification
from tests.fixtures.wizard.specifications import research_assistant

pytestmark = pytest.mark.usefixtures("export_clock")


class GuardedStream(BytesIO):
    """Record stream reads and reject any unbounded read."""

    def __init__(self, content: bytes) -> None:
        super().__init__(content)
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if size < 0:
            raise AssertionError("fixture stream was read without a bound")
        return super().read(size)


def _document(*fixtures: str) -> dict:
    specification = research_assistant()
    specification.id = "research-assistant"
    for task in specification.tasks:
        task.fixtures = list(fixtures)
    return specification.model_dump(mode="json")


def test_specification_has_engine_input_shape_and_opaque_bytes(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    (fixture_dir / "policy.html").write_bytes(b"<script>alert(1)</script>")
    (fixture_dir / "data.csv").write_text("a,b\n1,2\n")
    target = tmp_path / "specification.zip"

    write_specification(_document("policy.html"), fixture_dir, target)

    with zipfile.ZipFile(target) as archive:
        assert archive.namelist() == [
            "20261016-223045-manual/inputs/",
            "20261016-223045-manual/outputs/specification.yaml",
            "20261016-223045-manual/outputs/fixtures/",
            "20261016-223045-manual/outputs/fixtures/data.csv",
            "20261016-223045-manual/outputs/fixtures/policy.html",
        ]
        assert (
            archive.read("20261016-223045-manual/outputs/fixtures/policy.html")
            == b"<script>alert(1)</script>"
        )
        assert (
            "features:"
            in archive.read(
                "20261016-223045-manual/outputs/specification.yaml"
            ).decode()
        )


def test_specification_keeps_an_explicit_empty_fixtures_directory(
    tmp_path: Path,
) -> None:
    target = tmp_path / "specification.zip"
    write_specification(_document(), tmp_path / "fixtures", target)

    with zipfile.ZipFile(target) as archive:
        assert archive.namelist() == [
            "20261016-223045-manual/inputs/",
            "20261016-223045-manual/outputs/specification.yaml",
            "20261016-223045-manual/outputs/fixtures/",
        ]


def test_specification_can_include_a_portable_specification(tmp_path: Path) -> None:
    specification = research_assistant()
    specification.id = "research-assistant"
    for task in specification.tasks:
        task.fixtures = []
    target = tmp_path / "specification.zip"

    write_specification(
        specification.model_dump(mode="json"),
        tmp_path / "fixtures",
        target,
    )

    with zipfile.ZipFile(target) as archive:
        assert archive.namelist() == [
            "20261016-223045-manual/inputs/",
            "20261016-223045-manual/outputs/specification.yaml",
            "20261016-223045-manual/outputs/fixtures/",
        ]
        saved = Specification.model_validate(
            yaml.safe_load(
                archive.read("20261016-223045-manual/outputs/specification.yaml")
            )
        )

    assert saved == specification


def test_specification_refuses_missing_referenced_file(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()

    with pytest.raises(SpecificationError, match="missing.txt"):
        write_specification(
            _document("missing.txt"), fixture_dir, tmp_path / "specification.zip"
        )


def test_in_memory_packager_contains_specification_and_fixtures() -> None:
    specification = research_assistant()
    specification.id = "research-assistant"
    archive_bytes = package_specification(
        specification,
        [SpecificationFixture("policy.pdf", BytesIO(b"policy bytes"))],
    )

    with zipfile.ZipFile(io.BytesIO(archive_bytes.content)) as archive:
        assert set(archive.namelist()) == {
            "20261016-223045-manual/inputs/",
            "20261016-223045-manual/outputs/specification.yaml",
            "20261016-223045-manual/outputs/fixtures/",
            "20261016-223045-manual/outputs/fixtures/policy.pdf",
        }
        assert (
            archive.read("20261016-223045-manual/outputs/fixtures/policy.pdf")
            == b"policy bytes"
        )
        assert (
            Specification.model_validate(
                yaml.safe_load(
                    archive.read("20261016-223045-manual/outputs/specification.yaml")
                )
            )
            == specification
        )


def test_in_memory_packager_includes_unreferenced_fixtures() -> None:
    specification = research_assistant()
    specification.id = "research-assistant"
    archive_bytes = package_specification(
        specification,
        [
            SpecificationFixture("policy.pdf", BytesIO(b"policy bytes")),
            SpecificationFixture("notes.txt", BytesIO(b"unreferenced notes")),
        ],
    )

    with zipfile.ZipFile(io.BytesIO(archive_bytes.content)) as archive:
        assert (
            archive.read("20261016-223045-manual/outputs/fixtures/notes.txt")
            == b"unreferenced notes"
        )


@pytest.mark.parametrize("name", ["../invoice.pdf", "CON.txt", "", "bad\\name.pdf"])
def test_in_memory_packager_rejects_invalid_scenario_references(name: str) -> None:
    with pytest.raises(SpecificationError):
        build_specification_archive(_document(name), [])


def test_in_memory_packager_keeps_an_empty_fixture_directory() -> None:
    archive_bytes = build_specification_archive(_document(), [])

    with zipfile.ZipFile(io.BytesIO(archive_bytes.content)) as archive:
        assert archive.namelist() == [
            "20261016-223045-manual/inputs/",
            "20261016-223045-manual/outputs/specification.yaml",
            "20261016-223045-manual/outputs/fixtures/",
        ]


@pytest.mark.parametrize(
    "fixture",
    [
        SpecificationFixture("../policy.pdf", BytesIO(b"bytes")),
        SpecificationFixture("policy.exe", BytesIO(b"bytes")),
        SpecificationFixture("policy.pdf", "not a stream"),  # type: ignore[arg-type]
    ],
)
def test_in_memory_packager_rejects_invalid_fixture_input(
    fixture: SpecificationFixture,
) -> None:
    with pytest.raises(SpecificationError):
        build_specification_archive(_document(), [fixture])


def test_in_memory_packager_refuses_missing_referenced_file() -> None:
    with pytest.raises(SpecificationError, match="missing.txt"):
        build_specification_archive(_document("missing.txt"), [])


def test_in_memory_packager_refuses_duplicate_fixture_identities() -> None:
    with pytest.raises(SpecificationError, match="already exists"):
        build_specification_archive(
            _document(),
            [
                SpecificationFixture("Policy.pdf", BytesIO(b"one")),
                SpecificationFixture("policy.pdf", BytesIO(b"two")),
            ],
        )


def test_in_memory_packager_refuses_more_than_twenty_fixtures() -> None:
    fixtures = [
        SpecificationFixture(f"fixture-{index}.txt", BytesIO(b"x"))
        for index in range(21)
    ]

    with pytest.raises(SpecificationError, match="at most 20"):
        build_specification_archive(_document(), fixtures)


def test_in_memory_packager_rejects_excess_fixture_parts_before_reading() -> None:
    streams = [GuardedStream(b"x") for _ in range(21)]

    with pytest.raises(SpecificationError, match="at most 20"):
        build_specification_archive(
            _document(),
            [
                SpecificationFixture(f"fixture-{index}.txt", stream)
                for index, stream in enumerate(streams)
            ],
        )

    assert all(stream.read_sizes == [] for stream in streams)


def test_in_memory_packager_reads_fixture_content_with_a_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(specification_module, "MAX_DOCUMENT_BYTES", 8)
    stream = GuardedStream(b"123456789")

    with pytest.raises(SpecificationError, match="at most 8"):
        build_specification_archive(
            _document(), [SpecificationFixture("fixture.txt", stream)]
        )

    assert stream.read_sizes == [9]
