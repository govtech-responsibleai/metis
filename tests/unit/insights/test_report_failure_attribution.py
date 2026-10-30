"""How a failed trial gets blamed: the report's failureSource rule (issues #329, #423).

`_load_trial_records` decides whether a trial's failure is attributed to the target under
test, the user agent, or METIS. The cause comes from `outcome.failure_source` and
`outcome.failure_message`, which the engine records from #462; without them it falls back to
the trial's `stop_reason`.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from metis.core.trials import TrialConfig, TrialOutcome, TrialRecord
from metis.insights._report import _load_trial_records

if TYPE_CHECKING:
    from pathlib import Path


def _only_trial(
    tmp_path: Path,
    stop_reason: str,
    failure_source: str | None = None,
    failure_message: str | None = None,
) -> dict[str, Any]:
    record = TrialRecord(
        config=TrialConfig(persona="p", scenario="s"),
        outcome=TrialOutcome(
            stop_reason=stop_reason,
            simulated_turns_completed=1,
            duration_seconds=1.0,
            failure_source=failure_source,
            failure_message=failure_message,
        ),
        target_session_id="sess-1",
    )
    trial_dir = tmp_path / "outputs" / "trials" / "trial-1"
    trial_dir.mkdir(parents=True)
    (trial_dir / "record.json").write_text(json.dumps(record.model_dump()))
    trials = _load_trial_records(tmp_path)
    assert len(trials) == 1
    return trials[0]


def test_a_clean_trial_is_not_blamed_on_the_target(tmp_path: Path) -> None:
    trial = _only_trial(tmp_path, "goal_achieved")
    assert trial["failureSource"] == "outcome"


def test_a_recorded_cause_is_used(tmp_path: Path) -> None:
    trial = _only_trial(
        tmp_path,
        "max_turns",
        failure_source="target",
        failure_message="tool call failed",
    )
    assert trial["failureSource"] == "target"
    assert trial["message"] == "tool call failed"


def test_an_unknown_recorded_source_falls_back(tmp_path: Path) -> None:
    """A source name the report cannot map is not left blank: the stop reason decides."""
    trial = _only_trial(tmp_path, "max_turns", failure_source="banana")
    assert trial["failureSource"] == "evaluationRunner"


def test_user_abandoned_is_the_user_agents_failure(tmp_path: Path) -> None:
    trial = _only_trial(tmp_path, "user_abandoned")
    assert trial["failureSource"] == "userAgent"


def test_any_other_stop_is_the_evaluation_runners_failure(tmp_path: Path) -> None:
    trial = _only_trial(tmp_path, "max_turns")
    assert trial["failureSource"] == "evaluationRunner"
    assert trial["message"] == "max_turns"
