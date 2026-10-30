"""Tests for run-level retry logic in _worker."""

from metis.core.trials import TrialFailure, TrialRecord


class TestRunRetryBehavior:
    def test_run_failure_model_captures_attempt_info(self) -> None:
        failure = TrialFailure(
            attempt_number=1,
            failure_type="auth_loss",
            submission_phase="unknown",
            simulated_turns_completed=3,
            error_message="redirected to /login",
            duration_ms=15000,
        )
        assert failure.attempt_number == 1
        assert failure.failure_type == "auth_loss"

    def test_run_record_tracks_multiple_attempts(self) -> None:
        record = TrialRecord.model_validate(
            {
                "schema_version": 1,
                "config": {"persona": "p", "scenario": "s"},
                "outcome": {
                    "stop_reason": "system_error",
                    "simulated_turns_completed": 0,
                    "duration_seconds": 45.0,
                },
                "attempt_number": 3,
                "max_allowed_attempts": 3,
                "prior_failures": [
                    {
                        "attempt_number": 1,
                        "failure_type": "auth_loss",
                        "simulated_turns_completed": 5,
                        "error_message": "redirected",
                        "duration_ms": 20000,
                    },
                    {
                        "attempt_number": 2,
                        "failure_type": "page_crash",
                        "simulated_turns_completed": 2,
                        "error_message": "disconnected",
                        "duration_ms": 10000,
                    },
                ],
            }
        )
        assert record.attempt_number == 3
        assert record.max_allowed_attempts == 3
        assert len(record.prior_failures) == 2
        assert record.prior_failures[0].failure_type == "auth_loss"

    def test_scenario_override_respected(self) -> None:
        from metis.engine.simulation.types import Scenario

        scenario = Scenario.model_validate(
            {
                "id": "s1",
                "name": "Test",
                "description": "test",
                "max_trial_retries": 0,
                "persona_refs": ["p1"],
            }
        )
        assert scenario.max_trial_retries == 0
