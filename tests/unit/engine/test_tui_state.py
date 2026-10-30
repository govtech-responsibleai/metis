"""Tests for the simulation TUI state model."""

from __future__ import annotations

import time

from metis.engine.tui import (
    SimulationScenarioState,
    SimulationState,
    SimulationTrialState,
)


class TestSimulationState:
    def _make_state(self) -> SimulationState:
        """Build a state with 2 scenarios, 3 total runs."""
        scenarios = [
            SimulationScenarioState(
                scenario_id="direct-question",
                trials=[
                    SimulationTrialState(
                        scenario_id="direct-question",
                        persona_id="cooperative",
                        trial_index=1,
                        num_trials=1,
                        phase="pending",
                        current_turn=None,
                        max_turns=20,
                        turn_detail="",
                        duration_seconds=None,
                        stop_reason=None,
                    ),
                ],
                phase="pending",
            ),
            SimulationScenarioState(
                scenario_id="constrained-analysis",
                trials=[
                    SimulationTrialState(
                        scenario_id="constrained-analysis",
                        persona_id="impatient",
                        trial_index=1,
                        num_trials=2,
                        phase="pending",
                        current_turn=None,
                        max_turns=20,
                        turn_detail="",
                        duration_seconds=None,
                        stop_reason=None,
                    ),
                    SimulationTrialState(
                        scenario_id="constrained-analysis",
                        persona_id="impatient",
                        trial_index=2,
                        num_trials=2,
                        phase="pending",
                        current_turn=None,
                        max_turns=20,
                        turn_detail="",
                        duration_seconds=None,
                        stop_reason=None,
                    ),
                ],
                phase="pending",
            ),
        ]
        return SimulationState(
            experiment_id="test-exp", scenarios=scenarios, total_trials=3
        )

    def test_initial_counts(self) -> None:
        state = self._make_state()
        assert state.completed_trials == 0
        assert state.completed_scenarios == 0
        assert state.total_trials == 3
        assert state.pending_scenario_count == 2
        assert state.active_scenario is None

    def test_start_run(self) -> None:
        state = self._make_state()
        state.mark_trial_started("direct-question", "cooperative", trial_index=1)
        assert state.active_scenario is not None
        assert state.active_scenario.scenario_id == "direct-question"
        assert state.active_scenario.phase == "active"
        trial = state.active_scenario.trials[0]
        assert trial.phase == "simulating"

    def test_update_run_turn(self) -> None:
        state = self._make_state()
        state.mark_trial_started("direct-question", "cooperative", trial_index=1)
        state.mark_trial_turn(
            "direct-question",
            "cooperative",
            trial_index=1,
            turn=3,
            max_turns=20,
            detail="waiting for LLM...",
        )
        trial = state.active_scenario.trials[0]
        assert trial.current_turn == 3
        assert trial.max_turns == 20
        assert trial.turn_detail == "waiting for LLM..."

    def test_complete_run_marks_scenario_complete(self) -> None:
        state = self._make_state()
        state.mark_trial_started("direct-question", "cooperative", trial_index=1)
        state.mark_trial_completed(
            "direct-question",
            "cooperative",
            trial_index=1,
            stop_reason="goal_achieved",
            duration_seconds=226.0,
        )
        assert state.completed_trials == 1
        assert state.completed_scenarios == 1
        # Scenario with single trial is now completed
        assert state.scenarios[0].phase == "completed"

    def test_complete_run_partial_scenario(self) -> None:
        """Completing 1 of 2 trials does NOT mark the scenario complete."""
        state = self._make_state()
        state.mark_trial_started("constrained-analysis", "impatient", trial_index=1)
        state.mark_trial_completed(
            "constrained-analysis",
            "impatient",
            trial_index=1,
            stop_reason="goal_achieved",
            duration_seconds=100.0,
        )
        assert state.completed_trials == 1
        assert state.completed_scenarios == 0
        assert state.scenarios[1].phase == "active"

    def test_fail_run(self) -> None:
        state = self._make_state()
        state.mark_trial_started("direct-question", "cooperative", trial_index=1)
        state.mark_trial_failed(
            "direct-question",
            "cooperative",
            trial_index=1,
            reason="system_error",
            duration_seconds=5.0,
        )
        trial = state.scenarios[0].trials[0]
        assert trial.phase == "failed"
        assert trial.stop_reason == "system_error"
        # Failed trials still count toward completion
        assert state.completed_trials == 1

    def test_elapsed_seconds(self) -> None:
        state = self._make_state()
        time.sleep(0.05)
        assert state.elapsed_seconds >= 0.04
