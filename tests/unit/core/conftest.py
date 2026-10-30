"""Shared fixtures for core unit tests."""

from __future__ import annotations

import pytest
import structlog


@pytest.fixture(autouse=True)
def reset_structlog() -> None:
    """Reset structlog to its built-in defaults before each test.

    Tests in ``test_logging.py`` call ``configure_logging()``, which reconfigures
    the global structlog state (including the logger factory's file handle). When
    pytest's ``capsys`` context exits after such a test, that file handle may be
    closed. Subsequent tests that call ``logger.warning()`` (e.g. ``Trace.root``
    fallback paths in ``test_traces.py``) then fail with "I/O operation on
    closed file".

    This autouse fixture resets structlog to its built-in defaults before every
    test so that each test starts from a clean logging state.
    """
    structlog.reset_defaults()
