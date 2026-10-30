"""Tests for the simulation exception hierarchy."""

from metis.engine.simulation.exceptions import (
    ConsecutiveFailureEscalation,
    ResponseTimeoutError,
    SimulationError,
    TargetSessionEnded,
    TrialRecoverableError,
    TurnRecoverableError,
    UserAgentUnavailableError,
)


class TestExceptionHierarchy:
    def test_turn_recoverable_is_simulation_error(self) -> None:
        assert issubclass(TurnRecoverableError, SimulationError)

    def test_trial_recoverable_is_simulation_error(self) -> None:
        assert issubclass(TrialRecoverableError, SimulationError)

    def test_consecutive_failure_is_trial_recoverable(self) -> None:
        assert issubclass(ConsecutiveFailureEscalation, TrialRecoverableError)

    def test_response_timeout_is_simulation_error(self) -> None:
        assert issubclass(ResponseTimeoutError, SimulationError)

    def test_response_timeout_is_not_turn_or_trial_recoverable(self) -> None:
        assert not issubclass(ResponseTimeoutError, TurnRecoverableError)
        assert not issubclass(ResponseTimeoutError, TrialRecoverableError)


def test_target_session_ended_is_simulation_error() -> None:
    assert issubclass(TargetSessionEnded, SimulationError)
    assert not issubclass(TargetSessionEnded, TurnRecoverableError)
    assert not issubclass(TargetSessionEnded, TrialRecoverableError)


def test_user_agent_unavailable_is_trial_recoverable() -> None:
    assert issubclass(UserAgentUnavailableError, TrialRecoverableError)
