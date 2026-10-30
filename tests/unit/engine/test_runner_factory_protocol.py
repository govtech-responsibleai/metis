"""Tests for the RunnerFactory protocol."""

from __future__ import annotations

from pathlib import Path

import pytest

from metis.core.trials import TrialConfig
from metis.engine.simulation.factory import RunnerFactory
from metis.engine.simulation.runner import Runner
from metis.engine.simulation.types import Observation, Promise, Reading


class FakeRunner(Runner):
    """Minimal Runner for testing."""

    @property
    def session_id(self) -> str | None:
        return None

    async def setup(self, config: TrialConfig) -> None:
        pass

    async def act(self, action: str, promised: list[Promise]) -> Observation:
        return Observation(
            reply="ok", reading=Reading(outcome="completed", why="A fake reply.")
        )

    async def end_chat(self, promised: list[Promise]) -> None:
        pass

    async def teardown(self) -> None:
        pass


class FakeRunnerFactory:
    """Minimal RunnerFactory implementation for protocol conformance test."""

    def __init__(self) -> None:
        self.started = False
        self.closed = False

    async def start(self) -> None:
        self.started = True

    async def create(
        self, run_dir: Path, fixtures_dir: Path, experiment_root: Path
    ) -> Runner:
        return FakeRunner()

    async def close(self) -> None:
        self.closed = True


class TestRunnerFactoryProtocol:
    def test_fake_factory_satisfies_protocol(self) -> None:
        factory: RunnerFactory = FakeRunnerFactory()
        assert hasattr(factory, "start")
        assert hasattr(factory, "create")
        assert hasattr(factory, "close")

    @pytest.mark.asyncio
    async def test_factory_lifecycle(self) -> None:
        factory = FakeRunnerFactory()
        await factory.start()
        assert factory.started
        runner = await factory.create(
            Path("/tmp/run"), Path("/tmp/fixtures"), Path("/tmp/exp")
        )
        assert isinstance(runner, Runner)
        await factory.close()
        assert factory.closed
