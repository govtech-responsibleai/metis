"""TrialRecord, the model of each trial's record.json, and the models it nests."""

from metis.core.trials import TrialFailure, TrialRecord


def test_trial_record_lives_in_core_only() -> None:
    import metis.engine.simulation.types as engine_types

    for name in ("TrialRecord", "TrialConfig", "TrialOutcome", "TrialFailure"):
        assert not hasattr(engine_types, name), name


class TestTrialFailure:
    def test_construct(self) -> None:
        f = TrialFailure(
            attempt_number=1,
            failure_type="auth_loss",
            submission_phase="post",
            simulated_turns_completed=5,
            error_message="redirected to /login",
            duration_ms=45000,
        )
        assert f.attempt_number == 1
        assert f.failure_type == "auth_loss"
        assert f.submission_phase == "post"


class TestTrialRecordExtension:
    def test_new_fields_default_backward_compatible(self) -> None:
        record = TrialRecord.model_validate(
            {
                "schema_version": 1,
                "config": {
                    "persona": "p",
                    "scenario": "s",
                },
                "outcome": {
                    "stop_reason": "max_turns",
                    "simulated_turns_completed": 10,
                    "duration_seconds": 60.0,
                },
            }
        )
        assert record.attempt_number == 1
        assert record.max_allowed_attempts == 1
        assert record.prior_failures == []
        assert record.config.user_agent_model is None
        assert record.config.runner_agent_model is None

    def test_config_records_the_simulation_models(self) -> None:
        from metis.core.trials import TrialConfig

        config = TrialConfig(
            persona="p", scenario="s", user_agent_model="ua", runner_agent_model="ra"
        )
        restored = TrialConfig.model_validate_json(config.model_dump_json())
        assert (restored.user_agent_model, restored.runner_agent_model) == ("ua", "ra")

    def test_legacy_conversation_key_is_ignored(self) -> None:
        """A record written before #461 still carries `conversation`, with
        nested per-turn diagnostics. It must keep loading, minus that key."""
        record = TrialRecord.model_validate(
            {
                "schema_version": 1,
                "config": {"persona": "p", "scenario": "s"},
                "outcome": {
                    "stop_reason": "max_turns",
                    "simulated_turns_completed": 1,
                    "duration_seconds": 3.0,
                },
                "conversation": [
                    {
                        "turn_number": 1,
                        "user_message": "hello",
                        "diagnostics": {
                            "retry_count": 1,
                            "action_retries": [{"action": "send_message"}],
                        },
                    }
                ],
                "attempt_number": 2,
                "max_allowed_attempts": 3,
                "prior_failures": [
                    {
                        "attempt_number": 1,
                        "failure_type": "auth_loss",
                        "simulated_turns_completed": 5,
                        "error_message": "redirected",
                        "duration_ms": 20000,
                    }
                ],
            }
        )
        assert "conversation" not in TrialRecord.model_fields
        assert "conversation" not in record.model_dump()
        assert len(record.prior_failures) == 1
        assert record.attempt_number == 2

    def test_schema_version_is_1(self) -> None:
        record = TrialRecord.model_validate(
            {
                "schema_version": 1,
                "config": {"persona": "p", "scenario": "s"},
                "outcome": {
                    "stop_reason": "max_turns",
                    "simulated_turns_completed": 5,
                    "duration_seconds": 30.0,
                },
            }
        )
        assert record.schema_version == 1


def test_trial_record_file_name() -> None:
    from metis.core import execution_layout

    assert execution_layout.TRIAL_RECORD == "record.json"


def test_outcome_cause_defaults_to_none() -> None:
    record = TrialRecord.model_validate(
        {
            "config": {"persona": "p", "scenario": "s"},
            "outcome": {
                "stop_reason": "max_turns",
                "simulated_turns_completed": 1,
                "duration_seconds": 1.0,
            },
        }
    )
    assert record.outcome.failure_source is None
    assert record.outcome.failure_message is None
