"""Shared fixtures for insights unit tests."""

from __future__ import annotations

import pytest
import structlog


@pytest.fixture(autouse=True)
def reset_structlog() -> None:
    """Reset structlog to its built-in defaults before each test.

    Tests that invoke CLI commands via Typer's CliRunner call
    configure_logging(), which reconfigures the global structlog state
    (including the logger factory's file handle).  When the CliRunner context
    exits, that file handle may be closed.  Subsequent tests that log at a
    level that is *not* filtered out (e.g. ERROR / exception) then fail with
    "I/O operation on closed file".

    This autouse fixture resets structlog to its built-in defaults before
    every test so that each test starts from a clean logging state.
    """
    structlog.reset_defaults()
