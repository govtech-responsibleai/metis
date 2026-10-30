"""Shared test configuration."""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest


def _find_repo_root() -> Path:
    """Walk up from this file to find the workspace root (contains pyproject.toml with [tool.uv.workspace])."""
    current = Path(__file__).resolve().parent
    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").exists() and (parent / "uv.lock").exists():
            return parent
    raise RuntimeError("Could not find repo root")


REPO_ROOT = _find_repo_root()

# Rich and Typer choose colour, layout, and line width from these. A CI runner and a developer
# terminal set them differently, and the tests assert on plain text.
_TERMINAL_VARIABLES = (
    "FORCE_COLOR",
    "GITHUB_ACTIONS",
    "NO_COLOR",
    "PY_COLORS",
    "TTY_COMPATIBLE",
    "TTY_INTERACTIVE",
)


@pytest.fixture(autouse=True)
def plain_terminal(monkeypatch):
    """Run every test in the same terminal, whatever the machine or the CI runner sets."""
    for name in _TERMINAL_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("COLUMNS", "200")


@pytest.fixture
def repo_root() -> Path:
    """Path to the monorepo workspace root."""
    return REPO_ROOT


@pytest.fixture
def export_clock(monkeypatch):
    from metis.wizard.application import export_layout

    def set_time(value: datetime) -> None:
        monkeypatch.setattr(
            export_layout, "datetime", SimpleNamespace(now=lambda: value)
        )

    set_time(datetime(2026, 10, 16, 22, 30, 45))
    return set_time


@pytest.fixture
def a_catalogued_grader(monkeypatch: pytest.MonkeyPatch):
    """Expose the demo grader to test catalogue discovery and parameter reading."""
    import metis.library.graders as graders
    from metis.library.graders.demo import DemoTraceBudgetGrader

    monkeypatch.setattr(
        graders, "DemoTraceBudgetGrader", DemoTraceBudgetGrader, raising=False
    )
    from metis.wizard.application.matching.library_catalogue import library_catalogue

    library_catalogue.cache_clear()
    yield DemoTraceBudgetGrader
    library_catalogue.cache_clear()
