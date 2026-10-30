"""Task and Criterion identity across planning, evaluation and resume."""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from metis.core.traces import GradingInput, Observation, Trace
from metis.core.trials import TrialConfig, TrialOutcome, TrialRecord
from metis.engine.cli import _classify_resume_trials
from metis.engine.evaluation import SessionFacts, build_grader, grade_session
from metis.engine.simulation.experiment import expand_trial_plan, trial_folder_name
from metis.engine.simulation.types import Specification
from metis.library.grader import LLMSettings


def specification() -> Specification:
    data = Specification.model_validate(
        {
            "schema_version": 1,
            "id": "task-identity",
            "runner_factory_ref": "metis.engine.simulation.runners.http.HttpRunnerFactory",
            "target": {
                "name": "Chatbot",
                "users": "Analysts",
                "description": "Answer questions.",
            },
            "features": [
                {
                    "id": "F-1",
                    "name": "Chat",
                    "description": "Answer questions.",
                    "behaviours": [
                        {
                            "id": "B-1",
                            "name": "Efficiency",
                            "description": "Use few turns.",
                            "measured": True,
                            "criteria": [
                                {
                                    "id": "AC-UNI-22",
                                    "name": "Short budget",
                                    "description": "Given a question, when the session ends, then at most 4 turns.",
                                    "grader_fqn": "tests.unit.engine.graders_for_tests.FixedScoreGrader",
                                    "grader_args": {"score": 0.2},
                                }
                            ],
                        }
                    ],
                }
            ],
            "personas": [
                {
                    "id": "P-1",
                    "name": "Cooperative user",
                    "description": "Gives details.",
                }
            ],
            "scenarios": [
                {"id": "S-1", "name": "Question", "description": "Ask a question."}
            ],
            "tasks": [
                {
                    "id": "TC-001",
                    "scenario_ref": "S-1",
                    "persona_ref": "P-1",
                    "fixtures": [],
                    "num_trials": 1,
                    "behaviour_refs": ["B-1"],
                }
            ],
        }
    ).model_dump()
    short = data["features"][0]["behaviours"][0]["criteria"][0]
    long = {**short, "id": "AC-LONG", "grader_args": {"score": 0.9}}
    data["features"][0]["behaviours"][0]["criteria"].append(long)
    data["features"][0]["behaviours"][0]["criteria"].append({**short, "id": "AC-TWIN"})
    first = data["tasks"][0]
    data["features"][0]["behaviours"].append(
        {
            **data["features"][0]["behaviours"][0],
            "id": "B-2",
            "criteria": [{**short, "id": "AC-OTHER"}],
        }
    )
    data["tasks"].append({**first, "id": "TC-002", "behaviour_refs": ["B-2"]})
    return Specification.model_validate(data)


def _session(session_id: str) -> GradingInput:
    trace_id = f"{session_id}-t0"
    return GradingInput(
        traces=(
            Trace(
                id=trace_id,
                session_id=session_id,
                observations=(Observation(id="o", trace_id=trace_id, output="ok"),),
            ),
        )
    )


def test_task_records_keep_criterion_configuration_and_trial_identity(
    tmp_path: Path,
) -> None:
    """Each criterion keeps its own args, and every record names its task and trial.

    AC-UNI-22 and AC-TWIN share a grader and args but are separate criteria; AC-LONG shares the
    grader with different args. Two criteria on one grader must never share a result.
    """
    experiment = specification()
    plan = expand_trial_plan(experiment, {p.id: p for p in experiment.personas})
    assert [
        [ref.criterion_id for ref in scenario.grader_refs] for scenario, _, _ in plan
    ] == [["AC-UNI-22", "AC-LONG", "AC-TWIN"], ["AC-OTHER"]]
    names = [trial_folder_name(*item) for item in plan]
    assert len(set(names)) == 2

    records = []
    for item in plan:
        scenario, persona, index = item
        criteria = [
            experiment.criterion(ref.criterion_id) for ref in scenario.grader_refs
        ]
        assert all(criterion is not None for criterion in criteria)
        criteria = [criterion for criterion in criteria if criterion is not None]
        graders = {
            criterion.id: build_grader(criterion, default_judge_model=None, env={})
            for criterion in criteria
        }
        facts = SessionFacts(
            session_id=f"session-{scenario.task_id}",
            scenario_id=scenario.id,
            task_id=scenario.task_id,
            trial_index=index,
        )
        records.extend(
            asyncio.run(
                grade_session(
                    criteria,
                    graders,
                    _session(facts.session_id),
                    LLMSettings(client=MagicMock()),
                    facts,
                )
            )
        )
        path = (
            tmp_path / "outputs" / "trials" / trial_folder_name(*item) / "record.json"
        )
        path.parent.mkdir(parents=True)
        record = TrialRecord(
            config=TrialConfig(
                task_id=scenario.task_id,
                trial_index=index,
                persona=persona.id,
                scenario=scenario.id,
                grader_refs=scenario.grader_refs,
            ),
            outcome=TrialOutcome(
                stop_reason="goal_achieved",
                simulated_turns_completed=7,
                duration_seconds=1,
            ),
        )
        path.write_text(record.model_dump_json())

    assert _classify_resume_trials(tmp_path, plan)[0] == []
    by_criterion = {r.criterion_id: r for r in records}
    assert [r.criterion_id for r in records] == [
        "AC-UNI-22",
        "AC-LONG",
        "AC-TWIN",
        "AC-OTHER",
    ]
    assert by_criterion["AC-UNI-22"].results[0].outcome == "failed"
    assert by_criterion["AC-LONG"].results[0].outcome == "passed"
    assert by_criterion["AC-TWIN"].results[0].outcome == "failed"
    assert by_criterion["AC-LONG"].grader_args == {"threshold": 0.5, "score": 0.9}
    assert [(r.task_id, r.trial_index) for r in records] == [
        ("TC-001", 1),
        ("TC-001", 1),
        ("TC-001", 1),
        ("TC-002", 1),
    ]


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate_task",
        "duplicate_criterion",
        "scenario",
        "persona",
        "behaviour",
        "duplicate_behaviour",
        "empty_selection",
        "unmeasured",
        "empty_criteria",
        "coverage",
        "trials",
    ],
)
def test_specification_rejects_invalid_task_graph(fault: str) -> None:
    data = specification().model_dump()
    if fault == "duplicate_task":
        data["tasks"][1]["id"] = data["tasks"][0]["id"]
    elif fault == "duplicate_criterion":
        criteria = data["features"][0]["behaviours"][0]["criteria"]
        criteria[1]["id"] = criteria[0]["id"]
    elif fault in {"scenario", "persona"}:
        data["tasks"][0][f"{fault}_ref"] = "missing"
    elif fault == "behaviour":
        data["tasks"][0]["behaviour_refs"] = ["missing"]
    elif fault == "duplicate_behaviour":
        data["tasks"][0]["behaviour_refs"] = ["B-1", "B-1"]
    elif fault == "empty_selection":
        data["tasks"][0]["behaviour_refs"] = []
    elif fault == "unmeasured":
        data["features"][0]["behaviours"][0]["measured"] = False
    elif fault == "empty_criteria":
        data["features"][0]["behaviours"][0]["criteria"] = []
    elif fault == "coverage":
        data["tasks"] = []
    else:
        data["tasks"][0]["num_trials"] = 0
    with pytest.raises(ValidationError):
        Specification.model_validate(data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_turns", 0),
        ("timeout_minutes", 0),
        ("response_wait_ms", 0),
        ("max_run_retries", -1),
    ],
)
def test_execution_settings_require_positive_limits_and_nonnegative_retries(
    field: str,
    value: int,
) -> None:
    document = specification().model_dump()
    document["tasks"][0][field] = value
    with pytest.raises(ValidationError, match=field):
        Specification.model_validate(document)


def test_omitted_execution_settings_use_engine_defaults() -> None:
    document = specification().model_dump()
    task_fields = (
        "max_turns",
        "timeout_minutes",
        "response_wait_ms",
        "max_run_retries",
    )
    resolved_fields = (
        "max_turns",
        "timeout_minutes",
        "response_wait_ms",
        "max_trial_retries",
    )
    for field in task_fields:
        document["tasks"][0].pop(field)
    parsed = Specification.model_validate(document)
    resolved = parsed.resolved_tasks()[0]
    assert tuple(getattr(resolved, field) for field in resolved_fields) == (
        20,
        15,
        300000,
        None,
    )
