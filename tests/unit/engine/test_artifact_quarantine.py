"""Moving a previous attempt's artifacts aside (issue #346)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from metis.engine.simulation._artifact_store import quarantine_stale_artifacts

# Fixed so the destination name is deterministic.
_STAMP = datetime(2026, 9, 21, 6, 15, 0, tzinfo=UTC)


def test_returns_none_when_there_is_no_artifacts_dir(tmp_path: Path) -> None:
    assert quarantine_stale_artifacts(tmp_path, now=_STAMP) is None
    assert list(tmp_path.iterdir()) == []


def test_leaves_an_empty_artifacts_dir_alone(tmp_path: Path) -> None:
    """An attempt that downloaded nothing must not leave an empty quarantine."""
    (tmp_path / "artifacts").mkdir()

    assert quarantine_stale_artifacts(tmp_path, now=_STAMP) is None

    assert (tmp_path / "artifacts").is_dir()
    assert not list(tmp_path.glob("artifacts-superseded-*"))


def test_moves_a_populated_dir_aside(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "report.pdf").write_text("attempt 1")

    dest = quarantine_stale_artifacts(tmp_path, now=_STAMP)

    assert dest == tmp_path / "artifacts-superseded-20260921T061500Z"
    assert (dest / "report.pdf").read_text() == "attempt 1"
    # Gone, so the next attempt's runner creates a clean one.
    assert not artifacts.exists()


def test_keeps_nested_subdirectories(tmp_path: Path) -> None:
    """The browser runner writes charts to artifacts/charts/."""
    charts = tmp_path / "artifacts" / "charts"
    charts.mkdir(parents=True)
    (charts / "fig.png").write_bytes(b"png")

    dest = quarantine_stale_artifacts(tmp_path, now=_STAMP)

    assert dest is not None
    assert (dest / "charts" / "fig.png").read_bytes() == b"png"


def test_second_quarantine_in_the_same_second_gets_its_own_dir(tmp_path: Path) -> None:
    for text in ("first", "second"):
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        (artifacts / "report.pdf").write_text(text)
        quarantine_stale_artifacts(tmp_path, now=_STAMP)

    assert sorted(p.name for p in tmp_path.glob("artifacts-superseded-*")) == [
        "artifacts-superseded-20260921T061500Z",
        "artifacts-superseded-20260921T061500Z-2",
    ]
    base = tmp_path / "artifacts-superseded-20260921T061500Z"
    assert (base / "report.pdf").read_text() == "first"
    collision = tmp_path / "artifacts-superseded-20260921T061500Z-2"
    assert (collision / "report.pdf").read_text() == "second"
