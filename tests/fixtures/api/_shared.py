"""Shared fixtures for the API door tests.

The API tests reuse the wizard's own offline corridor — the `ScriptedInterviewer`, the `walk`
driver and the hand-authored specifications under ``tests/fixtures/wizard`` — so a door test proves the
HTTP adapter preserves wizard behaviour without re-scripting it.

Every client is built over a fresh `create_app()` with the wizard dependencies overridden to the
scripted pair, so no test ever constructs the real gateway or reaches the network. Each test has
its own store in a project folder under `tmp_path`. Two clients in one test share that store, so
they act as two browsers of one project.

Import the fixtures you need into a conftest to register them for that test subtree:

    from tests.fixtures.api._shared import (
        client, make_client, project_dir, project_cwd, store
    )
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from metis.api.main import create_app
from metis.api.store import DATABASE, Store
from metis.wizard import InterviewRequest, handle_interview
from tests.fixtures.wizard.scripted import ScriptedInterviewer, ScriptedMatcher

if TYPE_CHECKING:
    from pathlib import Path


def scripted_interview_handler(interviewer: object | None = None):
    """Build the public Interview seam over a fully offline scripted pair."""
    provider = interviewer or ScriptedInterviewer()
    matcher = ScriptedMatcher()

    def interview(body: InterviewRequest):
        return handle_interview(body, interviewer=provider, matcher=matcher)

    return interview


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """The project folder of the test store. Experiments go in its `experiments/execute/`."""
    folder = tmp_path / "project"
    folder.mkdir()
    (folder / "pyproject.toml").write_text('[project]\nname = "test-project"\n')
    return folder


@pytest.fixture(autouse=True)
def project_cwd(project_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Start each test in the project folder, so an app that builds its own store finds it."""
    monkeypatch.chdir(project_dir)
    monkeypatch.delenv("METIS_DATABASE_URL", raising=False)


def database_url(project_dir: Path) -> str:
    """The URL of the default SQLite store in ``project_dir``."""
    return f"sqlite:///{project_dir / DATABASE}"


@pytest.fixture
def store(project_dir: Path) -> Iterator[Store]:
    """One SQLite store in the project folder, shared by every client of the test."""
    opened = Store(database_url(project_dir), project_dir)
    yield opened
    opened.close()


@pytest.fixture
def make_client(store: Store) -> Callable[..., TestClient]:
    """Build a TestClient over its own fresh app, with the scripted dependencies injected.

    It is a factory, because the cross-instance tests need two apps and some tests want their
    own interviewer to inspect afterwards.
    """

    def _make(
        interviewer: object | None = None, *, raise_server_exceptions: bool = True
    ) -> TestClient:
        app = create_app(
            interview_handler=scripted_interview_handler(interviewer), store=store
        )
        return TestClient(app, raise_server_exceptions=raise_server_exceptions)

    return _make


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client()
