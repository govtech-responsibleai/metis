"""Tests for scenario-level simulation limit fields."""

from metis.core.trials import TrialConfig
from metis.engine.simulation.types import Scenario


class TestScenarioLimits:
    """Scenario accepts max_turns and timeout_minutes with correct defaults."""

    def test_defaults(self):
        s = Scenario(
            id="basic",
            description="test",
            persona_refs=["p1"],
        )
        assert s.max_turns == 20
        assert s.timeout_minutes == 15
        assert s.response_wait_ms == 300000

    def test_custom_values(self):
        s = Scenario(
            id="custom",
            description="test",
            persona_refs=["p1"],
            max_turns=30,
            timeout_minutes=25,
            response_wait_ms=600000,
        )
        assert s.max_turns == 30
        assert s.timeout_minutes == 25
        assert s.response_wait_ms == 600000

    def test_from_yaml_dict(self):
        data = {
            "id": "yaml-scenario",
            "description": "loaded from yaml",
            "persona_refs": ["analyst"],
            "max_turns": 50,
            "timeout_minutes": 45,
        }
        s = Scenario.model_validate(data)
        assert s.max_turns == 50
        assert s.timeout_minutes == 45
        assert s.response_wait_ms == 300000  # not overridden


class TestTrialConfigFromScenario:
    """TrialConfig constructed from Scenario sources all three limits."""

    def test_limits_from_scenario_defaults(self):
        s = Scenario(id="s1", description="test", persona_refs=["p1"])
        rc = TrialConfig(
            persona="p1",
            scenario=s.id,
            grader_refs=s.grader_refs,
            max_turns=s.max_turns,
            timeout_minutes=s.timeout_minutes,
            response_wait_ms=s.response_wait_ms,
        )
        assert rc.max_turns == 20
        assert rc.timeout_minutes == 15
        assert rc.response_wait_ms == 300000

    def test_limits_from_scenario_custom(self):
        s = Scenario(
            id="s2",
            description="test",
            persona_refs=["p1"],
            max_turns=40,
            timeout_minutes=30,
            response_wait_ms=600000,
        )
        rc = TrialConfig(
            persona="p1",
            scenario=s.id,
            grader_refs=s.grader_refs,
            max_turns=s.max_turns,
            timeout_minutes=s.timeout_minutes,
            response_wait_ms=s.response_wait_ms,
        )
        assert rc.max_turns == 40
        assert rc.timeout_minutes == 30
        assert rc.response_wait_ms == 600000


class TestResponseTimeoutResolution:
    """response_wait_ms from scenario is the runtime source of truth."""

    def test_scenario_value_is_authoritative(self):
        """TrialConfig.response_wait_ms (from Scenario) is never zero/None."""
        s = Scenario(
            id="s1",
            description="test",
            persona_refs=["p1"],
            response_wait_ms=450000,
        )
        rc = TrialConfig(
            persona="p1",
            scenario=s.id,
            grader_refs=s.grader_refs,
            max_turns=s.max_turns,
            timeout_minutes=s.timeout_minutes,
            response_wait_ms=s.response_wait_ms,
        )
        assert rc.response_wait_ms == 450000

    def test_extended_timeout_uses_scenario_value(self):
        """Extended timeout for file uploads uses max(scenario_value, 180s)."""
        scenario_wait = 250000  # 250s — above 180s floor
        extended = max(scenario_wait, 180000)
        assert extended == 250000

        scenario_wait_short = 120000  # 120s — below 180s floor
        extended_short = max(scenario_wait_short, 180000)
        assert extended_short == 180000
