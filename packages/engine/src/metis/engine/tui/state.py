"""Pure data model tracking experiment progress for the TUI dashboard."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

SimulationTrialPhase = Literal["pending", "simulating", "completed", "failed"]


@dataclass
class SimulationTrialState:
    scenario_id: str
    persona_id: str
    trial_index: int  # 1-based: first trial is 1, up to num_trials
    num_trials: int
    phase: SimulationTrialPhase
    current_turn: int | None
    max_turns: int
    turn_detail: str
    duration_seconds: float | None
    stop_reason: str | None
    worker_id: int | None = None


@dataclass
class SimulationScenarioState:
    scenario_id: str
    trials: list[SimulationTrialState]
    phase: Literal["pending", "active", "completed"]


class SimulationState:
    def __init__(
        self,
        experiment_id: str,
        scenarios: list[SimulationScenarioState],
        total_trials: int,
    ) -> None:
        self.experiment_id = experiment_id
        self.scenarios = scenarios
        self.total_trials = total_trials
        self._start_time = time.monotonic()

    def _find_trial(
        self, scenario_id: str, persona_id: str, trial_index: int
    ) -> tuple[SimulationScenarioState, SimulationTrialState]:
        for sc in self.scenarios:
            if sc.scenario_id == scenario_id:
                for trial in sc.trials:
                    if (
                        trial.persona_id == persona_id
                        and trial.trial_index == trial_index
                    ):
                        return sc, trial
        raise KeyError(
            f"Trial not found: {scenario_id} x {persona_id} trial {trial_index}"
        )

    def mark_trial_started(
        self,
        scenario_id: str,
        persona_id: str,
        trial_index: int,  # 1-based
        worker_id: int | None = None,
    ) -> None:
        sc, trial = self._find_trial(scenario_id, persona_id, trial_index)
        trial.phase = "simulating"
        trial.worker_id = worker_id
        if sc.phase == "pending":
            sc.phase = "active"

    def mark_trial_turn(
        self,
        scenario_id: str,
        persona_id: str,
        trial_index: int,  # 1-based
        turn: int,
        max_turns: int,
        detail: str,
    ) -> None:
        _, trial = self._find_trial(scenario_id, persona_id, trial_index)
        trial.current_turn = turn
        trial.max_turns = max_turns
        trial.turn_detail = detail

    def mark_trial_completed(
        self,
        scenario_id: str,
        persona_id: str,
        trial_index: int,  # 1-based
        stop_reason: str,
        duration_seconds: float,
    ) -> None:
        sc, trial = self._find_trial(scenario_id, persona_id, trial_index)
        trial.phase = "completed"
        trial.stop_reason = stop_reason
        trial.duration_seconds = duration_seconds
        self._check_scenario_complete(sc)

    def mark_trial_failed(
        self,
        scenario_id: str,
        persona_id: str,
        trial_index: int,  # 1-based
        reason: str,
        duration_seconds: float,
    ) -> None:
        sc, trial = self._find_trial(scenario_id, persona_id, trial_index)
        trial.phase = "failed"
        trial.stop_reason = reason
        trial.duration_seconds = duration_seconds
        self._check_scenario_complete(sc)

    def _check_scenario_complete(self, sc: SimulationScenarioState) -> None:
        if all(t.phase in ("completed", "failed") for t in sc.trials):
            sc.phase = "completed"

    @property
    def completed_trials(self) -> int:
        return sum(
            1
            for sc in self.scenarios
            for t in sc.trials
            if t.phase in ("completed", "failed")
        )

    @property
    def completed_scenarios(self) -> int:
        return sum(1 for sc in self.scenarios if sc.phase == "completed")

    @property
    def active_scenario(self) -> SimulationScenarioState | None:
        for sc in self.scenarios:
            if sc.phase == "active":
                return sc
        return None

    @property
    def pending_scenario_count(self) -> int:
        return sum(1 for sc in self.scenarios if sc.phase == "pending")

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self._start_time
