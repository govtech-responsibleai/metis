"""Wizard unit test fixtures.

The shared fixtures live under ``tests/fixtures/wizard`` so the unit and integration trees register
the same corridor. Importing them here registers them (and the autouse tracing guard) for this
subtree.
"""

from tests.fixtures.wizard._shared import (  # noqa: F401  (re-exported as fixtures)
    disable_external_tracing,
    fixtures_dir,
)
