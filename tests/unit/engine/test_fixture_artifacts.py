"""build_fixture_artifacts turns staged fixtures into source='fixture' Artifacts (#321, #328)."""

from __future__ import annotations

from pathlib import Path

from metis.engine.simulation._fixture_artifacts import build_fixture_artifacts


def test_builds_one_artifact_per_existing_fixture(tmp_path: Path) -> None:
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    (fixtures_dir / "input.csv").write_text("a,b\n1,2\n")
    (fixtures_dir / "brief.pdf").write_bytes(b"%PDF-1.4 ...")

    arts = build_fixture_artifacts(["input.csv", "brief.pdf"], fixtures_dir, tmp_path)

    assert [a.name for a in arts] == ["input.csv", "brief.pdf"]
    assert all(a.source == "fixture" for a in arts)
    assert all(a.state == "received" for a in arts)
    assert [a.path for a in arts] == ["fixtures/input.csv", "fixtures/brief.pdf"]
    assert all(len(a.digest or "") == 64 for a in arts)
    assert all(a.hash_algorithm == "SHA256" for a in arts)
    assert all(
        a.at_simulated_turn is None and a.content_description is None for a in arts
    )
    assert arts[0].media_type == "text/csv"
    assert arts[1].media_type == "application/pdf"


def test_skips_missing_fixture(tmp_path: Path) -> None:
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    (fixtures_dir / "present.csv").write_text("x")

    arts = build_fixture_artifacts(["present.csv", "gone.csv"], fixtures_dir, tmp_path)

    assert [a.name for a in arts] == ["present.csv"]


def test_skips_path_escape(tmp_path: Path) -> None:
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    (tmp_path / "secret.txt").write_text("nope")

    arts = build_fixture_artifacts(["../secret.txt"], fixtures_dir, tmp_path)

    assert arts == []


def test_empty_or_missing_dir_yields_nothing(tmp_path: Path) -> None:
    assert build_fixture_artifacts([], tmp_path / "fixtures", tmp_path) == []
    assert build_fixture_artifacts(["x.csv"], tmp_path / "nonexistent", tmp_path) == []


def test_build_fixture_artifacts_applies_author_description(tmp_path: Path) -> None:
    (tmp_path / "q3.csv").write_text("a,b\n1,2\n")
    (tmp_path / "notes.txt").write_text("hello")
    arts = build_fixture_artifacts(
        ["q3.csv", "notes.txt"],
        tmp_path,
        tmp_path,
        {"q3.csv": "Q3 sales, 200 rows."},
    )
    by_name = {a.name: a for a in arts}
    assert by_name["q3.csv"].content_description == "Q3 sales, 200 rows."
    assert by_name["notes.txt"].content_description is None
