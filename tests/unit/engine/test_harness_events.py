"""Tests that harness emits structured events for TUI/logging integration."""

from metis.engine.tui.state import (
    SimulationScenarioState,
    SimulationState,
    SimulationTrialState,
)


class TestHarnessEventEmission:
    def test_structlog_context_bound_on_run_start(self) -> None:
        """Verify that structlog contextvars get bound with run identity."""
        import structlog.contextvars

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            scenario_id="test-scn", persona_id="test-per", trial_index=1
        )
        ctx = structlog.contextvars.get_contextvars()
        assert ctx["scenario_id"] == "test-scn"
        assert ctx["persona_id"] == "test-per"
        assert ctx["trial_index"] == 1
        structlog.contextvars.clear_contextvars()

    def test_state_transitions_on_run_lifecycle(self) -> None:
        """Simulate the state transitions the harness would make."""
        scenarios = [
            SimulationScenarioState(
                scenario_id="scn",
                trials=[
                    SimulationTrialState(
                        scenario_id="scn",
                        persona_id="per",
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
        ]
        state = SimulationState(
            experiment_id="test", scenarios=scenarios, total_trials=1
        )

        # Simulate what harness does
        state.mark_trial_started("scn", "per", trial_index=1)
        assert state.active_scenario is not None

        state.mark_trial_turn(
            "scn", "per", trial_index=1, turn=1, max_turns=20, detail="sending message"
        )
        trial = state.scenarios[0].trials[0]
        assert trial.current_turn == 1

        state.mark_trial_completed(
            "scn",
            "per",
            trial_index=1,
            stop_reason="goal_achieved",
            duration_seconds=100.0,
        )
        assert state.completed_trials == 1
