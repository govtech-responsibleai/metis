"""Tests for TUI dashboard panel rendering."""

from rich.console import Console

from metis.engine.tui.dashboard import render_dashboard
from metis.engine.tui.state import (
    SimulationScenarioState,
    SimulationState,
    SimulationTrialState,
)


def _make_state_with_active_trial() -> SimulationState:
    scenarios = [
        SimulationScenarioState(
            scenario_id="direct-question",
            trials=[
                SimulationTrialState(
                    scenario_id="direct-question",
                    persona_id="cooperative",
                    trial_index=1,
                    num_trials=1,
                    phase="completed",
                    current_turn=None,
                    max_turns=20,
                    turn_detail="",
                    duration_seconds=226.0,
                    stop_reason="goal_achieved",
                ),
            ],
            phase="completed",
        ),
        SimulationScenarioState(
            scenario_id="constrained-analysis",
            trials=[
                SimulationTrialState(
                    scenario_id="constrained-analysis",
                    persona_id="impatient",
                    trial_index=1,
                    num_trials=1,
                    phase="simulating",
                    current_turn=4,
                    max_turns=8,
                    turn_detail="waiting for LLM...",
                    duration_seconds=None,
                    stop_reason=None,
                ),
            ],
            phase="active",
        ),
    ]
    return SimulationState(
        experiment_id="toyapp-eval", scenarios=scenarios, total_trials=2
    )


class TestRenderDashboard:
    def test_returns_renderable(self) -> None:
        state = _make_state_with_active_trial()
        result = render_dashboard(state)
        assert result is not None

    def test_contains_experiment_id(self) -> None:
        state = _make_state_with_active_trial()
        result = render_dashboard(state)
        console = Console(file=None, force_terminal=True, width=80)
        with console.capture() as capture:
            console.print(result)
        output = capture.get()
        assert "toyapp-eval" in output

    def test_contains_progress_fractions(self) -> None:
        state = _make_state_with_active_trial()
        result = render_dashboard(state)
        console = Console(file=None, force_terminal=True, width=80)
        with console.capture() as capture:
            console.print(result)
        output = capture.get()
        assert "1/2" in output  # scenarios or trials

    def test_contains_active_scenario(self) -> None:
        state = _make_state_with_active_trial()
        result = render_dashboard(state)
        console = Console(file=None, force_terminal=True, width=80)
        with console.capture() as capture:
            console.print(result)
        output = capture.get()
        assert "constrained-analysis" in output

    def test_contains_completed_scenario(self) -> None:
        state = _make_state_with_active_trial()
        result = render_dashboard(state)
        console = Console(file=None, force_terminal=True, width=80)
        with console.capture() as capture:
            console.print(result)
        output = capture.get()
        assert "direct-question" in output
