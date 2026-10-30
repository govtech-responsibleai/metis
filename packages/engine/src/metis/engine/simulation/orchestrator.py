"""The turn loop: the user agent says one action, the runner carries it out.

Each turn is one user-agent decision and one ``Runner.act``,
numbered from 1. After the loop the orchestrator calls ``Runner.end_chat`` once, unless
the trial was interrupted, the session was spent, or the user agent failed; that closing
call is not a turn and is not in ``simulated_turns_completed``. Nor is an action that sent nothing
because it quoted no message (``Observation.sent_nothing``); the user agent is told, and
the trial ends after three of them in a row.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from metis.core.logging import get_logger
from metis.core.trials import TrialConfig, TrialOutcome, TrialRecord

from .artifacts import ArtifactLedger
from .exceptions import (
    ConsecutiveFailureEscalation,
    ResponseTimeoutError,
    TargetSessionEnded,
    TrialRecoverableError,
    TurnRecoverableError,
    UserAgentUnavailableError,
)
from .types import Observation, Promise, Reading

if TYPE_CHECKING:
    import threading
    from pathlib import Path

    from metis.core import Artifact
    from metis.engine.tui import SimulationState, TUIContext

    from .runner import Runner
    from .types import Scenario
    from .user_agent.agent import UserAgent

logger = get_logger()

_STOPS_WITH_CLOSING_CALL = frozenset(
    {"goal_achieved", "user_abandoned", "max_turns", "timeout"}
)
"""Endings after which the session is healthy and the user still wants its files."""
_UNCHECKED_STOPS = frozenset({"interrupted", "system_error"})
"""Endings after which the fixture check does not run: the trial is already cut short."""
_DECISION_STOPS = {"goal_achieved": "goal_achieved", "giving_up": "user_abandoned"}
_MAX_EMPTY_ACTIONS = 3
"""Actions in a row that send nothing before the trial is ended: they are not turns, so
``max_turns`` would never stop a user agent that keeps quoting no message."""


def _undelivered_notice(exc: Exception) -> str:
    """What the user is told when a turn did not complete, worded for the user agent."""
    if isinstance(exc, ResponseTimeoutError):
        return "Response timeout — no response received"
    return (
        "No reply was captured for this turn — the target's response could not be read."
    )


def _undelivered(notice: str) -> Observation:
    return Observation(
        reply=None,
        reading=Reading(
            outcome="not_completed", why="The runner did not finish this action."
        ),
        observed=False,
        notice=notice,
    )


class Orchestrator:
    """Drives the turn loop for one attempt. Owns the trial's :class:`ArtifactLedger`."""

    def __init__(
        self,
        runner: Runner,
        agent: UserAgent,
        trial_config: TrialConfig,
        scenario: Scenario,
        run_dir: Path,
        experiment_root: Path,
        fixture_artifacts: list[Artifact],
        trial_index: int = 1,  # 1-based
        state: SimulationState | None = None,
        tui_ctx: TUIContext | None = None,
        shutdown_event: threading.Event | None = None,
    ) -> None:
        self._runner = runner
        self._agent = agent
        self._config = trial_config
        self._scenario = scenario
        self._trial_index = trial_index
        self._state = state
        self._tui_ctx = tui_ctx
        self._shutdown_event = shutdown_event
        self._ledger = ArtifactLedger(experiment_root, run_dir, fixture_artifacts)
        runner.use_ledger(self._ledger)

        # Progress, kept on self so partial_record() can read it if execute() raises.
        self._turns = 0
        self._promised: list[Promise] = []
        self._session_id: str | None = None
        self._start = time.time()
        self._failure: tuple[str, str] | None = None
        """``(failure_source, failure_message)`` when a METIS check failed the trial."""

    async def execute(self) -> TrialRecord:
        """Run the trial to a stop reason and return its record."""
        self._start = time.time()
        logger.info(
            "[sim] START: %s x %s (max_turns=%d, timeout=%d min)",
            self._config.persona,
            self._config.scenario,
            self._config.max_turns,
            self._config.timeout_minutes,
        )
        try:
            await self._runner.setup(self._config)
            stop_reason = await self._run_turns()
            if self._turns and (
                stop_reason in _STOPS_WITH_CLOSING_CALL or self._failure is not None
            ):
                await self._close()
            if self._turns and stop_reason not in _UNCHECKED_STOPS:
                stop_reason = self._check_fixtures(stop_reason)
            logger.info("[sim] STOP: %s after %d turn(s)", stop_reason, self._turns)
            return self.partial_record(stop_reason)
        finally:
            await self._runner.teardown()

    def _check_fixtures(self, stop_reason: str) -> str:
        """Check 1: a fixture the scenario names that was never sent fails the trial."""
        for a in self._ledger.artifacts():
            if a.source == "fixture" and a.at_simulated_turn is None:
                self._failure = (
                    "evaluation_runner",
                    f"fixture_never_uploaded: {a.name}",
                )
                return "system_error"
        return stop_reason

    def partial_record(self, stop_reason: str) -> TrialRecord:
        """A record from whatever progress the trial has made, for the retry loop."""
        source, message = self._failure or (None, None)
        return TrialRecord(
            config=self._config,
            target_session_id=self._session_id,
            outcome=TrialOutcome(
                stop_reason=stop_reason,
                simulated_turns_completed=self._turns,
                duration_seconds=round(time.time() - self._start, 1),
                failure_source=source,
                failure_message=message,
            ),
            artifacts=self._ledger.artifacts(),
        )

    async def _run_turns(self) -> str:
        consecutive_failures = 0
        empty_actions = 0
        while True:
            if self._shutdown_event and self._shutdown_event.is_set():
                return "interrupted"
            if self._turns >= self._config.max_turns:
                return "max_turns"
            if time.time() - self._start >= self._config.timeout_minutes * 60:
                return "timeout"

            turn = self._turns + 1
            self._mark(turn, "waiting for LLM...")
            try:
                output = await self._agent.decide(
                    turn, self._ledger.artifacts(), self._still_promised()
                )
            except UserAgentUnavailableError:
                raise
            except Exception as exc:
                logger.info("[turn %d] STOP: user agent LLM failed: %s", turn, exc)
                return "system_error"
            if output.decision in _DECISION_STOPS:
                return _DECISION_STOPS[output.decision]

            self._mark(turn, "sending action...")
            try:
                observation = await self._runner.act(
                    output.action, self._still_promised()
                )
                consecutive_failures = 0
            except TargetSessionEnded as exc:
                logger.info("[turn %d] STOP: target_exhausted (%s)", turn, exc)
                return "target_exhausted"
            except TrialRecoverableError:
                raise
            except (TurnRecoverableError, ResponseTimeoutError) as exc:
                # The caller cannot know whether the action landed, so it is never
                # re-sent; the next decision starts from what the user is told here.
                consecutive_failures += 1
                if consecutive_failures >= 2:
                    raise ConsecutiveFailureEscalation(
                        f"{consecutive_failures} consecutive turn failures"
                    ) from exc
                notice = _undelivered_notice(exc)
                logger.info("[turn %d] turn not completed: %s", turn, notice)
                observation = _undelivered(notice)
            finally:
                self._session_id = self._session_id or self._runner.session_id

            if observation.sent_nothing:
                empty_actions += 1
            else:
                empty_actions = 0
                self._turns += 1
            self._note_promises(observation, turn)
            self._agent.remember(output, observation)
            logger.info(
                "orchestrator_turn_result",
                turn=turn,
                counted=not observation.sent_nothing,
                sent_nothing=observation.sent_nothing,
                outcome=observation.reading.outcome,
                action=output.action,
                reply=observation.reply,
                notice=observation.notice,
            )
            if empty_actions >= _MAX_EMPTY_ACTIONS:
                self._failure = ("user_agent", "no_message_quoted")
                logger.info("[turn %d] STOP: no_message_quoted", turn)
                return "system_error"
            if observation.submission_unresolved:
                # No new submission may be sent while one is open, so no later turn
                # could proceed; the closing step still collects what it can.
                self._failure = ("evaluation_runner", "submission_unresolved")
                logger.info("[turn %d] STOP: submission_unresolved", turn)
                return "system_error"

    async def _close(self) -> None:
        """The closing call. Whatever it fails with, the turns already played stand."""
        try:
            await self._runner.end_chat(self._still_promised())
        except (TurnRecoverableError, ResponseTimeoutError, TargetSessionEnded) as exc:
            logger.warning("[sim] end_chat did not complete: %s", exc)

    def _note_promises(self, observation: Observation, turn: int) -> None:
        known = {p.name for p in self._promised}
        for name in observation.promised:
            if name not in known:
                known.add(name)
                self._promised.append(Promise(name=name, turn=turn))

    def _still_promised(self) -> list[Promise]:
        """Promised files still worth waiting for, worked out from the ledger each time.

        A file the ledger holds as ``received`` or has given up on as ``unavailable`` is
        settled; an ``unfetched`` one can still be retried, so it stays promised.
        """
        settled = {
            a.name
            for a in self._ledger.artifacts()
            if a.source == "target" and a.state != "unfetched"
        }
        return [p for p in self._promised if p.name not in settled]

    def _mark(self, turn: int, detail: str) -> None:
        if not self._state:
            return
        self._state.mark_trial_turn(
            self._scenario.task_id or self._scenario.id,
            self._config.persona,
            trial_index=self._trial_index,
            turn=turn,
            max_turns=self._config.max_turns,
            detail=detail,
        )
        if self._tui_ctx:
            self._tui_ctx.refresh()


__all__ = ["Orchestrator"]
