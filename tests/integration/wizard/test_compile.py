"""The complete Specification survives compilation, packaging and engine loading."""

from pathlib import Path

import pytest
import yaml

from metis.engine.simulation.types import Specification
from metis.wizard.application.compile import (
    CompilationError,
    compile_experiment,
    render_review,
    to_yaml,
    write_experiment,
)
from tests.fixtures.wizard.specifications import research_assistant


def test_specification_round_trip_and_golden(fixtures_dir: Path) -> None:
    specification = research_assistant()
    document = compile_experiment(specification, "research-assistant")
    output = to_yaml(document)
    assert output == to_yaml(compile_experiment(specification, "research-assistant"))
    assert output == (fixtures_dir / "golden_specification.yaml").read_text()
    loaded = Specification.model_validate(yaml.safe_load(output))
    assert loaded.target == specification.target
    assert loaded.features == specification.features
    assert loaded.tasks == specification.tasks
    assert loaded.trial_count() == 9
    assert document["tasks"][0]["behaviour_refs"] == ["EB-1"]
    assert [ref.criterion_id for ref in loaded.resolved_tasks()[0].grader_refs] == [
        "AC-1-1",
        "AC-1-2",
    ]


@pytest.mark.parametrize("fault", ["persona", "behaviour", "trials", "coverage"])
def test_invalid_specification_is_not_written(tmp_path: Path, fault: str) -> None:
    specification = research_assistant()
    if fault == "persona":
        specification.tasks[0].persona_ref = "missing"
    elif fault == "behaviour":
        specification.tasks[0].behaviour_refs = ["missing"]
    elif fault == "trials":
        specification.tasks[0].num_trials = 0
    else:
        specification.tasks = specification.tasks[:2]
    target = tmp_path / "specification.yaml"
    with pytest.raises(CompilationError):
        write_experiment(specification, "research-assistant", target)
    assert not target.exists()


def test_specification_and_review_preserve_unicode(tmp_path: Path) -> None:
    specification = research_assistant()
    specification.target.description = "Swipe → see detail"
    path = tmp_path / "specification.yaml"
    write_experiment(specification, "research-assistant", path)
    assert (
        Specification.load_file(path).target.description
        == specification.target.description
    )
    review = render_review(specification, "research-assistant")
    assert specification.target.description in review
    assert specification.target.detail in review
    assert "TC-001" in review
    assert "9 trials" in review


def test_assigned_task_ids_survive_edits_and_new_tasks_get_new_ids() -> None:
    from metis.wizard.domain.specification import Specification

    specification = research_assistant()
    specification.tasks[0].id = ""
    first = Specification.model_validate(compile_experiment(specification, "test"))
    assigned = first.tasks[0].id
    first.tasks.reverse()
    task = first.task(assigned)
    assert task is not None
    task.num_trials = 7
    task.max_turns = 9
    task.timeout_minutes = 2
    task.response_wait_ms = 45000
    task.max_run_retries = 0
    second = Specification.model_validate(compile_experiment(first, "test"))
    restored = second.task(assigned)
    assert restored is not None
    assert restored.num_trials == 7
    assert restored.max_turns == 9
    assert restored.timeout_minutes == 2
    assert restored.response_wait_ms == 45000
    assert restored.max_run_retries == 0
    first.tasks.append(task.model_copy(deep=True, update={"id": ""}))
    replacement = compile_experiment(first, "test")["tasks"][-1]
    assert replacement["id"] != assigned


def test_criterion_parameters_survive_compilation_and_reject_unknown_arguments() -> (
    None
):
    specification = research_assistant()
    criterion = specification.behaviour("EB-2").criteria[0]  # type: ignore[union-attr]
    criterion.grader_args = {"max_traces": 4}
    compiled = Specification.model_validate(compile_experiment(specification, "test"))
    assert compiled.criterion(criterion.id).grader_args == {"max_traces": 4}  # type: ignore[union-attr]
    criterion.grader_args = {"turn_buget": 4}
    with pytest.raises(CompilationError, match=criterion.id):
        compile_experiment(specification, "test")


@pytest.mark.parametrize(
    ("model", "threshold", "outcome"),
    [(None, 0.5, "failed"), ("chosen-judge", 0.0, "passed")],
)
def test_edited_yaml_description_reaches_the_judge_and_result_record(
    tmp_path: Path, model, threshold, outcome
) -> None:
    import asyncio
    import json

    from metis.engine.cli import _validate_inputs
    from metis.engine.evaluation import (
        SessionFacts,
        build_grader,
        grade_session,
    )
    from metis.library.grader import DEFAULT_MAX_INPUT_TOKENS, LLMSettings
    from metis.wizard.application.matching import CRITERION_JUDGE_FQN
    from tests.fixtures.criterion_judge import judge_client, recorded_session

    specification = research_assistant()
    criterion = specification.features[0].behaviours[0].criteria[0]
    criterion.grader_fqn = CRITERION_JUDGE_FQN
    criterion.grader_args = {"threshold": threshold}
    if model:
        criterion.grader_args["model"] = model
    specification.experiment.defaults.judge_model = "default-judge"
    path = tmp_path / "specification.yaml"
    write_experiment(specification, "fallback", path)
    document = yaml.safe_load(path.read_text())
    stored = document["features"][0]["behaviours"][0]["criteria"][0]
    assert "criterion" not in stored["grader_args"]
    stored["description"] = "it cites TWO independent sources"
    path.write_text(yaml.safe_dump(document))
    for task in specification.tasks:
        for fixture in task.fixtures:
            fixture_path = tmp_path / "fixtures" / fixture
            fixture_path.parent.mkdir(parents=True, exist_ok=True)
            fixture_path.touch()
    _validate_inputs(tmp_path)
    loaded = Specification.load_file(path)
    task = loaded.resolved_tasks()[0]
    saved_criterion = loaded.criterion(criterion.id)
    assert saved_criterion is not None
    built = build_grader(
        saved_criterion,
        default_judge_model=loaded.experiment.defaults.judge_model,
        env={},
    )
    requests = []
    client = judge_client(
        json.dumps(
            {"status": "scored", "score": 0, "reason": "Only one source is recorded."}
        ),
        requests,
    )

    async def run():
        async with client:
            return await grade_session(
                [saved_criterion],
                {saved_criterion.id: built},
                recorded_session(),
                LLMSettings(client),
                SessionFacts("session-1", task.id, task.task_id, 1),
            )

    [record] = asyncio.run(run())
    assert "TWO independent sources" in requests[0]["input"][0]["content"]
    assert record.grader_args == {
        "criterion": str(loaded.criterion(criterion.id).description),
        "model": model or "default-judge",
        "threshold": threshold,
        "max_input_tokens": DEFAULT_MAX_INPUT_TOKENS,
    }
    assert record.results[0].outcome == outcome
    assert loaded.criterion(criterion.id).grader_args == criterion.grader_args


@pytest.mark.parametrize(
    ("fault", "message"),
    [
        ("override", "description"),
        ("blank", "description"),
        ("unknown", "unknown"),
        ("threshold", "threshold"),
    ],
)
def test_engine_preflight_reports_invalid_fallback_configuration(
    tmp_path: Path, capsys, fault, message
) -> None:
    from metis.engine.cli import _validate_inputs
    from metis.wizard.application.matching import CRITERION_JUDGE_FQN

    specification = research_assistant()
    criterion = specification.features[0].behaviours[0].criteria[0]
    criterion.grader_fqn = CRITERION_JUDGE_FQN
    criterion.grader_args = {}
    specification.id = "fallback-test"
    if fault == "override":
        criterion.grader_args["criterion"] = "second instruction source"
    elif fault == "unknown":
        criterion.grader_args["unknown"] = 1
    else:
        criterion.grader_args["threshold"] = 2
    for task in specification.tasks:
        task.fixtures = []
    document = specification.model_dump(mode="json")
    if fault == "blank":
        document["features"][0]["behaviours"][0]["criteria"][0]["description"] = " "
    (tmp_path / "specification.yaml").write_text(yaml.safe_dump(document))
    with pytest.raises(SystemExit) as caught:
        _validate_inputs(tmp_path)
    assert caught.value.code == 1
    output = capsys.readouterr().out
    if fault != "blank":
        assert criterion.id in output
    assert message in output


def test_parameter_assessment_retains_identity_and_effective_settings_in_results(
    tmp_path: Path,
) -> None:
    import asyncio

    from metis.engine.evaluation import (
        SessionFacts,
        build_grader,
        grade_session,
    )
    from metis.library.grader import LLMSettings
    from tests.fixtures.criterion_judge import judge_client, recorded_session
    from tests.fixtures.wizard.scripted import TRACE_BUDGET

    specification = research_assistant()
    criterion = specification.criterion("AC-1-1")
    criterion.description = "The session stays within its trace budget."
    criterion.grader_fqn = TRACE_BUDGET
    criterion.grader_args = {"max_traces": 3}
    path = tmp_path / "specification.yaml"
    write_experiment(specification, "budget", path)
    loaded = Specification.load_file(path)
    task = loaded.resolved_tasks()[0]
    saved_criterion = loaded.criterion(criterion.id)
    assert saved_criterion is not None
    built = build_grader(saved_criterion, default_judge_model=None, env={})
    requests = []
    client = judge_client("", requests)

    async def run():
        async with client:
            return await grade_session(
                [saved_criterion],
                {saved_criterion.id: built},
                recorded_session(),
                LLMSettings(client),
                SessionFacts("session-1", task.id, task.task_id, 1),
            )

    [record] = asyncio.run(run())
    assert record.criterion_id == criterion.id
    assert record.grader_args["max_traces"] == 3
    assert record.results[0].outcome == "passed"
    assert not requests
