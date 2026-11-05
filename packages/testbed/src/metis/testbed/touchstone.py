"""Turn METIS runs into Project Touchstone verdicts files.

Project Touchstone's toy apps, such as SkyDesk, plant known flaws and keep a private ledger of
what really happened, so each app can score any evaluator's verdicts against an answer key.
An app reads verdicts in a verdicts file that belongs to no evaluator: for each session, the
app's session ID, the suite scenario it ran, and a verdict per suite check. This module writes
one such file per METIS execution folder, using a map from the Specification's criterion and
Scenario IDs to the suite's check and scenario IDs.
"""

from __future__ import annotations

from collections import defaultdict
from importlib.metadata import version
from typing import TYPE_CHECKING, Any, Literal, Self

import yaml
from pydantic import BaseModel

from metis.core import execution_layout as layout
from metis.core.reporting import EvaluationResults
from metis.core.trials import TrialRecord

if TYPE_CHECKING:
    from pathlib import Path

    from metis.core.grading import RecordedResult

Verdict = Literal["pass", "fail", "n/a", "skipped", "errored"]

VERDICTS_VERSION = 1
"""The Touchstone verdicts file version this module writes."""

METIS_ERRORS = (
    "The judge request needs about",
    "Judge failed:",
    "Criterion judge failed:",
    "The session has no turns.",
    "No recorded trace input or output",
    "Grader raised:",
    "The grader returned no results",
)
"""How METIS's own errored reasons start. A criterion judge records "does not apply" as an
errored result with its own reason, so any other errored reason means the criterion did not
apply."""


class TouchstoneMap(BaseModel, extra="forbid"):
    """The suite check each criterion states, and the suite scenario each Scenario states."""

    checks: dict[str, str]
    scenarios: dict[str, str]

    @classmethod
    def load_file(cls, path: Path) -> Self:
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def verdict(results: list[RecordedResult]) -> Verdict:
    """One criterion's verdict for a session, from every result its grader recorded."""
    outcomes = [result.outcome for result in results]
    if "failed" in outcomes:
        return "fail"
    errored = [result for result in results if result.outcome == "errored"]
    if errored:
        if all(
            not result.reason.strip().startswith(METIS_ERRORS) for result in errored
        ):
            return "n/a"
        return "errored"
    if outcomes and all(outcome == "skipped" for outcome in outcomes):
        return "skipped"
    if "passed" in outcomes:
        return "pass"
    return "errored"


def export_verdicts(experiment: Path, mapping: TouchstoneMap) -> dict[str, Any]:
    """One execution folder's sessions and verdicts, as a Touchstone verdicts file."""
    results_file = experiment / layout.RESULTS
    records = (
        EvaluationResults.load_file(results_file).records
        if results_file.exists()
        else []
    )
    verdicts: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for record in records:
        check = mapping.checks.get(record.criterion_id)
        if check is not None:
            verdicts[record.session_id][check] = {
                "verdict": verdict(record.results),
                "reason": " | ".join(result.reason for result in record.results),
            }
    sessions = []
    for path in sorted((experiment / layout.TRIALS).glob(f"*/{layout.TRIAL_RECORD}")):
        trial = TrialRecord.load_file(path)
        session_id = trial.target_session_id
        sessions.append(
            {
                "session_id": session_id,
                "scenario": mapping.scenarios.get(
                    trial.config.scenario, trial.config.scenario
                ),
                "trial": trial.config.trial_index,
                "stop_reason": trial.outcome.stop_reason,
                "goal_achieved": trial.outcome.stop_reason == "goal_achieved",
                "turns": trial.outcome.simulated_turns_completed,
                "verdicts": verdicts.get(session_id, {}) if session_id else {},
            }
        )
    return {
        "schema_version": VERDICTS_VERSION,
        "evaluator": f"METIS {version('metis-engine')}",
        "run": experiment.name,
        "sessions": sessions,
    }
