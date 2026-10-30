"""Shared fixtures for the API door tests.

The API tests reuse the wizard's own offline corridor — the `ScriptedInterviewer`, the `walk`
driver and the hand-authored specifications under ``tests/fixtures/wizard`` — so a door test proves the
HTTP adapter preserves wizard behaviour without re-scripting it.

Every client is built over a fresh `create_app()` with the wizard dependencies overridden to the
scripted pair, so no test ever constructs the real gateway or reaches the network.

Import the fixtures you need into a conftest to register them for that test subtree:

    from tests.fixtures.api._shared import client, make_client
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from metis.api.main import create_app
from metis.wizard import InterviewRequest, handle_interview
from tests.fixtures.wizard.scripted import ScriptedInterviewer, ScriptedMatcher


def scripted_interview_handler(interviewer: object | None = None):
    """Build the public Interview seam over a fully offline scripted pair."""
    provider = interviewer or ScriptedInterviewer()
    matcher = ScriptedMatcher()

    def interview(body: InterviewRequest):
        return handle_interview(body, interviewer=provider, matcher=matcher)

    return interview


@pytest.fixture
def make_client() -> Callable[..., TestClient]:
    """Build a TestClient over its own fresh app, with the scripted dependencies injected.

    A factory rather than one client, because the cross-instance test needs two apps and some
    tests want their own interviewer to inspect afterwards.
    """

    def _make(
        interviewer: object | None = None, *, raise_server_exceptions: bool = True
    ) -> TestClient:
        app = create_app(interview_handler=scripted_interview_handler(interviewer))
        return TestClient(app, raise_server_exceptions=raise_server_exceptions)

    return _make


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client()
