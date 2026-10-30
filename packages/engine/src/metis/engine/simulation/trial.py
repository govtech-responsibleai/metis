"""The per-attempt seam between the retry loop and a trial.

``create_trial`` builds one attempt's trial around a runner, and ``resolve_fixture_descriptions``
describes the fixtures once per experiment. The retry loop drives whatever ``Trial`` it gets.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from ._fixture_artifacts import build_fixture_artifacts
from .artifacts import file_facts
from .llm_calls import LLMCallLog
from .model_settings import user_agent_settings
from .orchestrator import Orchestrator
from .user_agent.agent import UserAgent

if TYPE_CHECKING:
    import threading
    from collections.abc import Iterable
    from pathlib import Path

    from metis.core import Artifact
    from metis.core.trials import TrialConfig, TrialRecord
    from metis.engine.tui import SimulationState, TUIContext

    from .runner import Runner
    from .types import Persona, Scenario


class Trial(Protocol):
    """One attempt at a trial, as the experiment's retry loop drives it."""

    async def execute(self) -> TrialRecord:
        """Run the trial to completion and return its record."""
        ...

    def partial_record(self, stop_reason: str) -> TrialRecord:
        """Build a record from whatever progress the trial has made."""
        ...


def create_trial(
    *,
    runner: Runner,
    persona: Persona,
    scenario: Scenario,
    trial_config: TrialConfig,
    run_dir: Path,
    experiment_root: Path,
    fixture_artifacts: list[Artifact],
    trial_index: int,
    state: SimulationState | None,
    tui_ctx: TUIContext | None,
    shutdown_event: threading.Event | None,
) -> Trial:
    """Build the user agent and the orchestrator that drive ``runner`` for one attempt."""
    agent = UserAgent(
        persona=persona,
        scenario=scenario,
        llm_log=LLMCallLog.for_trial(run_dir),
        settings=user_agent_settings(trial_config.user_agent_model),
    )
    return Orchestrator(
        runner=runner,
        agent=agent,
        trial_config=trial_config,
        scenario=scenario,
        run_dir=run_dir,
        experiment_root=experiment_root,
        fixture_artifacts=fixture_artifacts,
        trial_index=trial_index,
        state=state,
        tui_ctx=tui_ctx,
        shutdown_event=shutdown_event,
    )


async def resolve_fixture_descriptions(
    fixture_names: Iterable[str],
    fixtures_dir: Path,
    experiment_root: Path,
    author_descriptions: dict[str, str],
) -> dict[str, str]:
    """One description per distinct fixture: the author's, else its file facts.

    No LLM is called. A fixture missing on disk is left out.
    """
    artifacts = build_fixture_artifacts(
        sorted(set(fixture_names)), fixtures_dir, experiment_root, author_descriptions
    )
    root = experiment_root.resolve()
    return {
        a.name: a.content_description or file_facts(root / str(a.path), a.name)
        for a in artifacts
    }
