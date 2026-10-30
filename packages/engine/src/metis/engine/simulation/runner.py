"""The Runner ABC: carries out one plain-language action on the target."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from metis.core.trials import TrialConfig

    from .artifacts import ArtifactLedger
    from .types import Observation, Promise


class Runner(ABC):
    """Works out how to carry out the user's action, and does it.

    The orchestrator owns the trial's :class:`ArtifactLedger` and binds it with
    :meth:`use_ledger` before ``setup``. A runner records every file it sends or
    receives through ``self.ledger``, stamping ``at_simulated_turn`` with its own count of ``act``
    calls from 1. The orchestrator calls ``act`` exactly once per turn, so the two
    counts agree. ``end_chat`` records under the last turn's number.
    """

    ledger: ArtifactLedger

    def use_ledger(self, ledger: ArtifactLedger) -> None:
        """Bind the trial's ledger. Called once, before ``setup``."""
        self.ledger = ledger

    @property
    @abstractmethod
    def session_id(self) -> str | None:
        """The target's session ID, recorded by code from a submission's answer."""

    @abstractmethod
    async def setup(self, config: TrialConfig) -> None:
        """Prepare the connection. ``config`` carries the trial's budget and deadline."""

    @abstractmethod
    async def act(self, action: str, promised: list[Promise]) -> Observation:
        """Carry out ``action`` and report what happened.

        :param promised: Files the target promised and has not delivered.
        """

    @abstractmethod
    async def end_chat(self, promised: list[Promise]) -> None:
        """The closing step: collect what the target made available.

        Not a turn. Files it fetches go in the ledger.
        """

    @abstractmethod
    async def teardown(self) -> None:
        """Release what ``setup`` acquired."""
