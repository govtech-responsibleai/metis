"""The shared artifact write path and code-computed file facts (#479)."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import pytest

from metis.engine.simulation import artifacts as artifacts_module
from metis.engine.simulation._fixture_artifacts import build_fixture_artifacts
from metis.engine.simulation.artifacts import (
    ArtifactLedger,
    ArtifactRejected,
    bytes_problem,
    file_facts,
)
from metis.engine.simulation.transport_log import ArtifactRef

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

PDF = b"%PDF-1.7\n1 0 obj\n"
ZIP = b"PK\x03\x04" + b"\x00" * 16
CHAT_REPLY = json.dumps({"reply": "Here is your report.", "files": []}).encode()


def _sales_csv(rows: int = 200) -> bytes:
    lines = ["region,product,units,price,month"]
    lines += [f"R{i % 4},P{i},{i},{i * 2}.5,2026-{i % 12 + 1:02d}" for i in range(rows)]
    return ("\n".join(lines) + "\n").encode()


@pytest.fixture
def trial_dir(tmp_path: Path) -> Path:
    return tmp_path / "outputs" / "trials" / "t1"


def _ledger(tmp_path: Path, trial_dir: Path, fixtures: list[str] | None = None):
    fixtures_dir = tmp_path / "inputs" / "fixtures"
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    entries = build_fixture_artifacts(fixtures or [], fixtures_dir, tmp_path)
    return ArtifactLedger(tmp_path, trial_dir, entries)


def test_a_download_is_saved_and_recorded_by_code(
    tmp_path: Path, trial_dir: Path
) -> None:
    ledger = _ledger(tmp_path, trial_dir)

    ref = ledger.record_download(
        "report.pdf", PDF, at_simulated_turn=2, external_id="f-1"
    )

    assert ref == ArtifactRef(
        path="artifacts/report.pdf", sha256=hashlib.sha256(PDF).hexdigest()
    )
    assert (trial_dir / ref.path).read_bytes() == PDF
    (entry,) = ledger.artifacts()
    assert entry.model_dump(exclude={"id", "content_description"}) == {
        "name": "report.pdf",
        "source": "target",
        "state": "received",
        "external_id": "f-1",
        "path": "outputs/trials/t1/artifacts/report.pdf",
        "at_simulated_turn": 2,
        "state_description": None,
        "digest": ref.sha256,
        "hash_algorithm": "SHA256",
        "media_type": "application/pdf",
    }


def test_the_caller_supplies_at_simulated_turn_even_when_there_is_none(
    tmp_path: Path, trial_dir: Path
) -> None:
    ledger = _ledger(tmp_path, trial_dir)
    ledger.record_download("a.pdf", PDF, at_simulated_turn=None)
    assert ledger.artifacts()[0].at_simulated_turn is None


def test_a_name_that_is_taken_gets_a_numbered_name(
    tmp_path: Path, trial_dir: Path
) -> None:
    (trial_dir / "artifacts").mkdir(parents=True)
    (trial_dir / "artifacts" / "report.pdf").write_bytes(b"%PDF-earlier")
    ledger = _ledger(tmp_path, trial_dir)

    first = ledger.record_download("report.pdf", PDF, at_simulated_turn=1)
    second = ledger.record_download("report.pdf", PDF + b"2", at_simulated_turn=2)

    assert (first.path, second.path) == (
        "artifacts/report-1.pdf",
        "artifacts/report-2.pdf",
    )
    assert (trial_dir / "artifacts" / "report.pdf").read_bytes() == b"%PDF-earlier"
    assert len(ledger.artifacts()) == 2


@pytest.mark.parametrize(
    ("reported", "saved"),
    [
        ("../../etc/report.pdf", "report.pdf"),
        ("a\\b\\report.pdf", "report.pdf"),
        ("/abs/report.pdf", "report.pdf"),
        ("..", "artifact"),
        ("", "artifact"),
    ],
)
def test_a_file_is_saved_under_the_last_component_of_its_name(
    tmp_path: Path, trial_dir: Path, reported: str, saved: str
) -> None:
    ledger = _ledger(tmp_path, trial_dir)

    ref = ledger.record_download(reported, PDF, at_simulated_turn=0)

    assert ref.path == f"artifacts/{saved}"
    assert ledger.artifacts()[0].name == saved
    assert [p.name for p in (trial_dir / "artifacts").iterdir()] == [saved]


def test_the_bytes_are_written_through_a_part_file(
    tmp_path: Path, trial_dir: Path
) -> None:
    ledger = _ledger(tmp_path, trial_dir)
    seen: list[list[str]] = []

    def chunks() -> Iterator[bytes]:
        yield PDF
        seen.append(sorted(p.name for p in (trial_dir / "artifacts").iterdir()))
        yield b"more"

    ledger.record_download("report.pdf", chunks(), at_simulated_turn=0)

    assert seen == [["report.pdf.part"]]
    assert [p.name for p in (trial_dir / "artifacts").iterdir()] == ["report.pdf"]


def test_a_partial_download_is_never_kept(tmp_path: Path, trial_dir: Path) -> None:
    ledger = _ledger(tmp_path, trial_dir)

    def broken() -> Iterator[bytes]:
        yield PDF
        raise ConnectionError("reset by peer")

    with pytest.raises(ConnectionError):
        ledger.record_download("report.pdf", broken(), at_simulated_turn=0)

    assert list((trial_dir / "artifacts").iterdir()) == []
    assert ledger.artifacts() == []


def test_a_json_chat_reply_saved_as_docx_is_refused(
    tmp_path: Path, trial_dir: Path
) -> None:
    """The original failure: a chat reply recorded as a delivered file."""
    ledger = _ledger(tmp_path, trial_dir)

    with pytest.raises(ArtifactRejected, match="JSON"):
        ledger.record_download("summary.docx", CHAT_REPLY, at_simulated_turn=1)

    assert list((trial_dir / "artifacts").iterdir()) == []
    assert ledger.artifacts() == []


@pytest.mark.parametrize(
    ("name", "good"),
    [
        ("a.png", b"\x89PNG\r\n\x1a\n"),
        ("a.jpg", b"\xff\xd8\xff\xe0"),
        ("a.gif", b"GIF89a"),
        ("a.pdf", PDF),
        ("a.docx", ZIP),
        ("a.xlsx", ZIP),
        ("a.pptx", ZIP),
        ("a.zip", ZIP),
    ],
)
def test_a_typed_file_must_start_with_its_signature(
    tmp_path: Path, trial_dir: Path, name: str, good: bytes
) -> None:
    ledger = _ledger(tmp_path, trial_dir)

    with pytest.raises(ArtifactRejected, match="not a"):
        ledger.record_download(name, b"<html>Sign in</html>", at_simulated_turn=0)
    assert ledger.artifacts() == []

    ledger.record_download(name, good, at_simulated_turn=0)
    assert [a.name for a in ledger.artifacts()] == [name]


def test_json_content_type_cannot_be_saved_under_a_non_json_name(
    tmp_path: Path, trial_dir: Path
) -> None:
    ledger = _ledger(tmp_path, trial_dir)

    with pytest.raises(ArtifactRejected, match="JSON"):
        ledger.record_download(
            "report.docx",
            ZIP,
            at_simulated_turn=0,
            content_type="application/json; charset=utf-8",
        )

    assert ledger.artifacts() == []


def test_json_is_accepted_under_a_json_name(tmp_path: Path, trial_dir: Path) -> None:
    ledger = _ledger(tmp_path, trial_dir)

    ledger.record_download(
        "chart.vl.json",
        CHAT_REPLY,
        at_simulated_turn=0,
        content_type="application/json",
    )

    assert [a.name for a in ledger.artifacts()] == ["chart.vl.json"]


def test_json_is_refused_under_any_other_name() -> None:
    for name in ("notes.txt", "data.csv", "README"):
        assert bytes_problem(name, CHAT_REPLY) is not None
    assert bytes_problem("data.csv", b"{not json, just a csv header\n1,2\n") is None
    assert bytes_problem("notes.txt", b"plain text") is None


def test_a_fixture_has_one_entry_however_often_it_is_uploaded(
    tmp_path: Path, trial_dir: Path
) -> None:
    (tmp_path / "inputs" / "fixtures").mkdir(parents=True)
    (tmp_path / "inputs" / "fixtures" / "q3_sales.csv").write_bytes(_sales_csv())
    ledger = _ledger(tmp_path, trial_dir, ["q3_sales.csv"])
    assert ledger.artifacts()[0].at_simulated_turn is None

    ledger.record_upload("q3_sales.csv", at_simulated_turn=0)
    ledger.record_upload("q3_sales.csv", at_simulated_turn=3)

    (entry,) = ledger.artifacts()
    assert (entry.source, entry.name, entry.at_simulated_turn) == (
        "fixture",
        "q3_sales.csv",
        0,
    )
    assert entry.path == "inputs/fixtures/q3_sales.csv"


def test_only_a_held_file_can_be_uploaded(tmp_path: Path, trial_dir: Path) -> None:
    ledger = _ledger(tmp_path, trial_dir)

    with pytest.raises(KeyError, match="nope.csv"):
        ledger.record_upload("nope.csv", at_simulated_turn=0)


def test_uploading_a_download_adds_no_entry(tmp_path: Path, trial_dir: Path) -> None:
    ledger = _ledger(tmp_path, trial_dir)
    ledger.record_download("report.pdf", PDF, at_simulated_turn=1)

    ledger.record_upload("report.pdf", at_simulated_turn=2)

    (entry,) = ledger.artifacts()
    assert (entry.source, entry.at_simulated_turn) == ("target", 1)


def test_artifacts_returns_copies(tmp_path: Path, trial_dir: Path) -> None:
    ledger = _ledger(tmp_path, trial_dir)
    ledger.record_download("report.pdf", PDF, at_simulated_turn=1)

    ledger.artifacts()[0].at_simulated_turn = 99
    ledger.artifacts().clear()

    assert [a.at_simulated_turn for a in ledger.artifacts()] == [1]


def test_facts_for_a_200_row_csv_state_rows_columns_and_header(
    tmp_path: Path,
) -> None:
    path = tmp_path / "q3_sales.csv"
    path.write_bytes(_sales_csv(200))

    facts = file_facts(path, "q3_sales.csv")

    assert "\n" not in facts
    assert "q3_sales.csv" in facts
    assert "text/csv" in facts
    assert f"{path.stat().st_size} bytes" in facts
    assert "200 data rows" in facts
    assert "5 columns" in facts
    assert "header: region,product,units,price,month" in facts


def test_facts_never_carry_the_content(tmp_path: Path) -> None:
    path = tmp_path / "q3_sales.csv"
    path.write_bytes(_sales_csv(5))

    assert "R1,P1" not in file_facts(path, "q3_sales.csv")


def test_facts_for_any_file_are_name_type_and_size(tmp_path: Path) -> None:
    path = tmp_path / "x.bin"
    path.write_bytes(PDF)

    facts = file_facts(path, "report.pdf")

    assert facts.startswith("report.pdf (application/pdf, 17 bytes)")
    assert "rows" not in facts


def test_facts_for_a_csv_that_is_not_text_fall_back_to_the_general_facts(
    tmp_path: Path,
) -> None:
    path = tmp_path / "x.csv"
    path.write_bytes(b"\xff\xfe\x00\x01")

    assert file_facts(path, "x.csv") == "x.csv (text/csv, 4 bytes)"


def test_a_download_carries_its_facts_as_its_content_description(
    tmp_path: Path, trial_dir: Path
) -> None:
    ledger = _ledger(tmp_path, trial_dir)

    ledger.record_download("q3_sales.csv", _sales_csv(200), at_simulated_turn=0)

    description = ledger.artifacts()[0].content_description
    assert description is not None
    assert "200 data rows" in description
    assert "5 columns" in description


def test_a_fixture_gets_facts_unless_its_author_wrote_a_description(
    tmp_path: Path, trial_dir: Path
) -> None:
    fixtures = tmp_path / "inputs" / "fixtures"
    fixtures.mkdir(parents=True)
    (fixtures / "q3_sales.csv").write_bytes(_sales_csv(200))
    (fixtures / "notes.txt").write_bytes(b"hello")
    entries = build_fixture_artifacts(
        ["q3_sales.csv", "notes.txt"], fixtures, tmp_path, {"notes.txt": "My notes"}
    )

    ledger = ArtifactLedger(tmp_path, trial_dir, entries)

    by_name = {a.name: a for a in ledger.artifacts()}
    assert "200 data rows" in (by_name["q3_sales.csv"].content_description or "")
    assert by_name["notes.txt"].content_description == "My notes"


def test_facts_are_computed_once_per_digest(
    tmp_path: Path, trial_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    real = artifacts_module._content_facts

    def spy(path: Path, name: str) -> str:
        calls.append(name)
        return real(path, name)

    monkeypatch.setattr(artifacts_module, "_content_facts", spy)
    ledger = _ledger(tmp_path, trial_dir)

    ledger.record_download("a.csv", _sales_csv(10), at_simulated_turn=0)
    ledger.record_download("b.csv", _sales_csv(10), at_simulated_turn=1)
    ledger.record_download("c.csv", _sales_csv(11), at_simulated_turn=2)

    assert calls == ["a.csv", "c.csv"]
    descriptions = [a.content_description or "" for a in ledger.artifacts()]
    assert descriptions[1].startswith("b.csv")
    assert "10 data rows" in descriptions[1]


def test_a_fixture_must_be_a_fixture(tmp_path: Path, trial_dir: Path) -> None:
    ledger = _ledger(tmp_path, trial_dir)
    ledger.record_download("report.pdf", PDF, at_simulated_turn=0)

    with pytest.raises(ValueError, match="fixture"):
        ArtifactLedger(tmp_path, trial_dir, ledger.artifacts())


def test_a_failed_download_is_recorded_once_with_its_reason(
    tmp_path: Path, trial_dir: Path
) -> None:
    ledger = _ledger(tmp_path, trial_dir)

    first = ledger.record_failure(
        "a.pdf", "unfetched", "GET /f/1 -> 404", at_simulated_turn=2, external_id="1"
    )
    ledger.record_failure(
        "b.pdf", "unavailable", "listed with no ID", at_simulated_turn=2
    )
    again = ledger.record_failure(
        "b.pdf", "unavailable", "listed again", at_simulated_turn=3
    )

    assert first is not None
    assert (first.state, first.state_description, first.external_id) == (
        "unfetched",
        "GET /f/1 -> 404",
        "1",
    )
    assert again is None
    assert [(a.name, a.state) for a in ledger.artifacts()] == [
        ("a.pdf", "unfetched"),
        ("b.pdf", "unavailable"),
    ]


def test_a_file_already_held_is_not_recorded_as_a_failure(
    tmp_path: Path, trial_dir: Path
) -> None:
    ledger = _ledger(tmp_path, trial_dir)
    ledger.record_download("a.pdf", PDF, at_simulated_turn=1)

    assert (
        ledger.record_failure("a.pdf", "unfetched", "late", at_simulated_turn=2) is None
    )
    assert [a.state for a in ledger.artifacts()] == ["received"]


def test_an_upload_can_keep_the_targets_id_for_the_file(
    tmp_path: Path, trial_dir: Path
) -> None:
    (tmp_path / "inputs" / "fixtures").mkdir(parents=True)
    (tmp_path / "inputs" / "fixtures" / "q3_sales.csv").write_bytes(_sales_csv(3))
    ledger = _ledger(tmp_path, trial_dir, ["q3_sales.csv"])

    kept = ledger.record_upload("q3_sales.csv", at_simulated_turn=1, external_id="up-1")

    assert kept.external_id == "up-1"
    assert ledger.artifacts()[0].external_id == "up-1"
