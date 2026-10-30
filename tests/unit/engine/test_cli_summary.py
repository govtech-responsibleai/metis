"""Tests for final summary output."""

from metis.engine.tui.state import (
    SimulationScenarioState,
    SimulationState,
    SimulationTrialState,
)


def _print_final_summary(
    state: SimulationState, experiment_dir: str, log_dir: str
) -> str:
    """Replicate the summary logic for testing."""
    from metis.engine.cli import _format_final_summary

    return _format_final_summary(state, experiment_dir, log_dir)


class TestFinalSummary:
    def test_summary_contains_experiment_id(self) -> None:
        from metis.engine.cli import _format_final_summary

        scenarios = [
            SimulationScenarioState(
                scenario_id="scn",
                trials=[
                    SimulationTrialState(
                        scenario_id="scn",
                        persona_id="per",
                        trial_index=1,
                        num_trials=1,
                        phase="completed",
                        current_turn=None,
                        max_turns=20,
                        turn_detail="",
                        duration_seconds=100.0,
                        stop_reason="goal_achieved",
                    ),
                ],
                phase="completed",
            ),
        ]
        state = SimulationState(
            experiment_id="toyapp-eval", scenarios=scenarios, total_trials=1
        )
        summary = _format_final_summary(state, "/path/to/exp", "/path/to/exp/logs")
        assert "toyapp-eval" in summary
        assert "1/1" in summary
        assert "/path/to/exp/logs" in summary

    def test_summary_counts_outcome_categories(self) -> None:
        from metis.engine.cli import _format_final_summary

        def _run(persona: str, phase: str, stop_reason: str) -> SimulationTrialState:
            return SimulationTrialState(
                scenario_id="scn",
                persona_id=persona,
                trial_index=1,
                num_trials=1,
                phase=phase,
                current_turn=None,
                max_turns=20,
                turn_detail="",
                duration_seconds=30.0,
                stop_reason=stop_reason,
            )

        scenarios = [
            SimulationScenarioState(
                scenario_id="scn",
                trials=[
                    _run("per1", "completed", "goal_achieved"),
                    _run("per2", "completed", "user_abandoned"),
                    _run("per3", "completed", "timeout"),
                    _run("per4", "failed", "system_error"),
                ],
                phase="completed",
            ),
        ]
        state = SimulationState(
            experiment_id="test-exp", scenarios=scenarios, total_trials=4
        )
        summary = _format_final_summary(state, "/exp", "/exp/logs")
        assert "4/4" in summary
        assert "1 goal achieved" in summary
        assert "1 abandoned" in summary
        assert "1 timeout" in summary
        assert "1 error" in summary

    def test_summary_elapsed_time_minutes(self) -> None:
        from metis.engine.cli import _format_final_summary

        scenarios = [
            SimulationScenarioState(
                scenario_id="scn",
                trials=[
                    SimulationTrialState(
                        scenario_id="scn",
                        persona_id="per",
                        trial_index=1,
                        num_trials=1,
                        phase="completed",
                        current_turn=None,
                        max_turns=20,
                        turn_detail="",
                        duration_seconds=90.0,
                        stop_reason="goal_achieved",
                    ),
                ],
                phase="completed",
            ),
        ]
        state = SimulationState(
            experiment_id="time-exp", scenarios=scenarios, total_trials=1
        )
        summary = _format_final_summary(state, "/exp", "/exp/logs")
        # Should contain a time formatted as Xm (minutes)
        assert "m" in summary

    def test_summary_log_dir_path(self) -> None:
        from metis.engine.cli import _format_final_summary

        scenarios = [
            SimulationScenarioState(
                scenario_id="scn",
                trials=[
                    SimulationTrialState(
                        scenario_id="scn",
                        persona_id="per",
                        trial_index=1,
                        num_trials=1,
                        phase="completed",
                        current_turn=None,
                        max_turns=20,
                        turn_detail="",
                        duration_seconds=10.0,
                        stop_reason="goal_achieved",
                    ),
                ],
                phase="completed",
            ),
        ]
        state = SimulationState(
            experiment_id="log-exp", scenarios=scenarios, total_trials=1
        )
        log_dir = "/custom/log/path"
        summary = _format_final_summary(state, "/exp", log_dir)
        assert log_dir in summary
