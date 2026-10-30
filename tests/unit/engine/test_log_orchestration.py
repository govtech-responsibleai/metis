"""Tests for orchestration log (simulate.log)."""

import re
from pathlib import Path

from metis.engine.logging.orchestration import OrchestrationLogger

# ISO-8601 UTC with microseconds and a Z suffix, e.g. 2026-09-02T15:02:03.138406Z
_ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


class TestOrchestrationLogger:
    def test_creates_simulate_log(self, tmp_path: Path) -> None:
        orch = OrchestrationLogger(log_dir=tmp_path)
        orch.close()
        assert (tmp_path / "simulate.log").exists()

    def test_scenario_started(self, tmp_path: Path) -> None:
        orch = OrchestrationLogger(log_dir=tmp_path)
        orch.scenario_started("direct-question")
        orch.close()
        content = (tmp_path / "simulate.log").read_text()
        assert "SCENARIO direct-question STARTED" in content

    def test_trial_started_includes_log_pointer(self, tmp_path: Path) -> None:
        orch = OrchestrationLogger(log_dir=tmp_path)
        orch.trial_started(
            "direct-question", "cooperative", trial_index=1, num_trials=1
        )
        orch.close()
        content = (tmp_path / "simulate.log").read_text()
        assert "TRIAL direct-question x cooperative [trial 1/1] STARTED" in content
        assert "simulate-direct-question_cooperative-01.log" in content

    def test_trial_completed(self, tmp_path: Path) -> None:
        orch = OrchestrationLogger(log_dir=tmp_path)
        orch.trial_completed(
            "direct-question",
            "cooperative",
            trial_index=1,
            num_trials=1,
            stop_reason="goal_achieved",
            simulated_turns_completed=3,
            duration_seconds=226.0,
        )
        orch.close()
        content = (tmp_path / "simulate.log").read_text()
        assert "TRIAL direct-question x cooperative [trial 1/1] COMPLETED" in content
        assert "goal_achieved" in content
        assert "3 simulated turns" in content

    def test_scenario_completed(self, tmp_path: Path) -> None:
        orch = OrchestrationLogger(log_dir=tmp_path)
        orch.scenario_completed("direct-question", trials_passed=1, trials_total=1)
        orch.close()
        content = (tmp_path / "simulate.log").read_text()
        assert "SCENARIO direct-question COMPLETED (1/1 trials passed)" in content

    def test_json_format(self, tmp_path: Path) -> None:
        import json

        orch = OrchestrationLogger(log_dir=tmp_path, log_format="json")
        orch.scenario_started("scn")
        orch.close()
        content = (tmp_path / "simulate.log").read_text().strip()
        parsed = json.loads(content)
        assert parsed["event_type"] == "SCENARIO_STARTED"
        assert parsed["scenario_id"] == "scn"

    def test_resume_appends_and_records_plan(self, tmp_path: Path) -> None:
        first = OrchestrationLogger(log_dir=tmp_path)
        first.scenario_started("old")
        first.close()

        resumed = OrchestrationLogger(log_dir=tmp_path, append=True)
        resumed.resume_started(redo_count=2, complete_count=3)
        resumed.close()

        content = (tmp_path / "simulate.log").read_text()
        assert "SCENARIO old STARTED" in content
        assert "RESUME STARTED (2 trials to redo, 3 already complete)" in content


class TestOrchestrationTimestampFormat:
    def test_text_line_starts_with_iso_z_timestamp(self, tmp_path: Path) -> None:
        orch = OrchestrationLogger(log_dir=tmp_path)
        orch.scenario_started("direct-question")
        orch.close()
        line = (tmp_path / "simulate.log").read_text().splitlines()[0]
        # Line shape: "[<timestamp>] SCENARIO ... STARTED"
        assert line.startswith("[")
        stamp = line[1 : line.index("]")]
        assert _ISO_Z.match(stamp), f"not ISO-8601 Z: {stamp!r}"

    def test_json_timestamp_field_is_iso_z(self, tmp_path: Path) -> None:
        import json

        orch = OrchestrationLogger(log_dir=tmp_path, log_format="json")
        orch.scenario_started("scn")
        orch.close()
        parsed = json.loads((tmp_path / "simulate.log").read_text().strip())
        assert _ISO_Z.match(parsed["timestamp"]), parsed["timestamp"]

    def test_evaluation_log_line_starts_with_iso_z_timestamp(
        self, tmp_path: Path
    ) -> None:
        from metis.engine.logging.orchestration import EvaluationLogger

        ev = EvaluationLogger(log_dir=tmp_path)
        ev.write("EVALUATION STARTED")
        line = (tmp_path / "evaluate.log").read_text().splitlines()[0]
        stamp = line[1 : line.index("]")]
        assert _ISO_Z.match(stamp), f"not ISO-8601 Z: {stamp!r}"
