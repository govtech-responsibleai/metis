"""Shared fixtures for the wizard tests.

`FIXTURES` is where hand-authored specifications and golden files live. A hand-authored
`Specification` is a first-class test input: the specification model deliberately requires no
interview, no step and no history, so a fixture can be written by hand and compiled.

Import the fixtures you need into a conftest to register them for that test subtree:

    from tests.fixtures.wizard._shared import disable_external_tracing, fixtures_dir
"""

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(autouse=True)
def disable_external_tracing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the test suite from sending model content to a real Langfuse instance."""
    for name in (
        "LANGFUSE_BASE_URL",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "METIS_INTERNAL_LANGFUSE_BASE_URL",
        "METIS_INTERNAL_LANGFUSE_PUBLIC_KEY",
        "METIS_INTERNAL_LANGFUSE_SECRET_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
