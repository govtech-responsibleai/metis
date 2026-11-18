"""Shared fixtures for all unit tests."""

from __future__ import annotations

import pytest

_TARGET_LANGFUSE_VARS = (
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_BASE_URL",
    "LANGFUSE_HOST",
    "LANGFUSE_TIMEOUT",
)


@pytest.fixture(autouse=True)
def no_target_langfuse(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear the target's Langfuse keys, so no unit test looks up a real Langfuse project.

    A test that needs the keys sets them itself.
    """
    for name in _TARGET_LANGFUSE_VARS:
        monkeypatch.delenv(name, raising=False)
