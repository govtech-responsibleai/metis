"""RunnerFactory protocol — the lifecycle every runner factory shares."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pathlib import Path


class RunnerFactory(Protocol):
    """Factory that manages shared resources and creates Runner instances.

    Implementations own the lifecycle of expensive shared state (e.g., a
    browser process) and produce fresh Runner instances per attempt.

    A factory may define a classmethod ``from_specification(specification, inputs_dir)``.
    ``metis engine simulate`` then builds it with the specification and the experiment's
    ``inputs/`` folder instead of with no arguments. It is optional, so it is not declared
    here.

    ``create`` returns a :class:`metis.engine.simulation.runner.Runner`; it is typed
    ``object`` here so this module does not import the runner.
    """

    async def start(self) -> None:
        """Acquire shared resources (launch browser, open connection pool)."""
        ...

    async def create(
        self, run_dir: Path, fixtures_dir: Path, experiment_root: Path
    ) -> object:
        """Create a fresh Runner for one attempt."""
        ...

    async def close(self) -> None:
        """Release shared resources."""
        ...
