"""Confirms pytest collects this package's tests at all."""

from pathlib import Path


def test_fixtures_dir_exists(fixtures_dir: Path) -> None:
    assert fixtures_dir.is_dir()
