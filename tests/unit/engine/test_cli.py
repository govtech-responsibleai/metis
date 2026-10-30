"""Tests for _validate_inputs in cli.py."""

from pathlib import Path
from textwrap import dedent

import pytest

from metis.engine.cli import _validate_inputs

MINIMAL_EXPERIMENT = dedent(
    'schema_version: 1\nid: test-exp\nrunner_factory_ref: tests.unit.engine.test_runner_ref.StubRunnerFactory\npersonas:\n- id: alice\n  description: a persona\n  name: alice\nscenarios:\n- id: task-1\n  description: a task\n  name: task-1\ntarget:\n  name: Test target\n  users: Test users\n  description: Test target\ntasks:\n- id: TC-001\n  scenario_ref: task-1\n  persona_ref: alice\n  fixtures: []\n  num_trials: 1\n  behaviour_refs:\n  - EB-1\nfeatures:\n- id: F-1\n  name: Responses\n  description: Responses\n  behaviours:\n  - id: EB-1\n    name: Respond\n    description: Respond correctly\n    measured: true\n    criteria:\n    - id: AC-1-1\n      name: Check 1\n      description: "Given a request, when the agent responds, then the requirement is met."\n      grader_fqn: tests.unit.engine.graders_for_tests.FixedScoreGrader\n      grader_args: {}\n'
)


def _write_experiment(tmp_path: Path, content: str = MINIMAL_EXPERIMENT) -> Path:
    """Write specification.yaml and return input_dir."""
    (tmp_path / "specification.yaml").write_text(content)
    return tmp_path


# --- Check 1: directory exists ---


def test_missing_directory(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    missing = tmp_path / "nonexistent"
    with pytest.raises(SystemExit) as exc_info:
        _validate_inputs(missing)
    assert exc_info.value.code == 1
    assert "does not exist" in capsys.readouterr().out


# --- Check 2: specification.yaml exists ---


def test_missing_specification_yaml(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exc_info:
        _validate_inputs(tmp_path)
    assert exc_info.value.code == 1
    assert "specification.yaml" in capsys.readouterr().out


# --- Check 3: pydantic parse failure ---


def test_malformed_specification_yaml(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    (tmp_path / "specification.yaml").write_text("schema_version: 1\nid: x\n")
    with pytest.raises(SystemExit) as exc_info:
        _validate_inputs(tmp_path)
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "validation failed" in out


# --- Check 4: duplicate persona IDs ---


def test_duplicate_persona_id(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    content = dedent(
        'schema_version: 1\nid: test-exp\nrunner_factory_ref: tests.unit.engine.test_runner_ref.StubRunnerFactory\npersonas:\n- id: alice\n  description: first\n  name: alice\n- id: alice\n  description: duplicate\n  name: alice\nscenarios:\n- id: task-1\n  description: a task\n  name: task-1\ntarget:\n  name: Test target\n  users: Test users\n  description: Test target\ntasks:\n- id: TC-001\n  scenario_ref: task-1\n  persona_ref: alice\n  fixtures: []\n  num_trials: 1\n  behaviour_refs:\n  - EB-1\nfeatures:\n- id: F-1\n  name: Responses\n  description: Responses\n  behaviours:\n  - id: EB-1\n    name: Respond\n    description: Respond correctly\n    measured: true\n    criteria:\n    - id: AC-1-1\n      name: Check 1\n      description: "Given a request, when the agent responds, then the requirement is met."\n      grader_fqn: tests.unit.engine.graders_for_tests.FixedScoreGrader\n      grader_args: {}\n'
    )
    _write_experiment(tmp_path, content)
    with pytest.raises(SystemExit) as exc_info:
        _validate_inputs(tmp_path)
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "Duplicate" in out
    assert "alice" in out


# --- Check 5: duplicate task IDs ---


def test_duplicate_task_id(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    content = dedent(
        'schema_version: 1\nid: test-exp\nrunner_factory_ref: tests.unit.engine.test_runner_ref.StubRunnerFactory\npersonas:\n- id: alice\n  description: a persona\n  name: alice\nscenarios:\n- id: task-1\n  description: first\n  name: task-1\n- id: task-1\n  description: duplicate\n  name: task-1\ntarget:\n  name: Test target\n  users: Test users\n  description: Test target\ntasks:\n- id: TC-001\n  scenario_ref: task-1\n  persona_ref: alice\n  fixtures: []\n  num_trials: 1\n  behaviour_refs:\n  - EB-1\n- id: TC-002\n  scenario_ref: task-1\n  persona_ref: alice\n  fixtures: []\n  num_trials: 1\n  behaviour_refs:\n  - EB-2\nfeatures:\n- id: F-1\n  name: Responses\n  description: Responses\n  behaviours:\n  - id: EB-1\n    name: Respond\n    description: Respond correctly\n    measured: true\n    criteria:\n    - id: AC-1-1\n      name: Check 1\n      description: "Given a request, when the agent responds, then the requirement is met."\n      grader_fqn: tests.unit.engine.graders_for_tests.FixedScoreGrader\n      grader_args: {}\n- id: F-2\n  name: Responses\n  description: Responses\n  behaviours:\n  - id: EB-2\n    name: Respond\n    description: Respond correctly\n    measured: true\n    criteria:\n    - id: AC-2-1\n      name: Check 1\n      description: "Given a request, when the agent responds, then the requirement is met."\n      grader_fqn: tests.unit.engine.graders_for_tests.FixedScoreGrader\n      grader_args: {}\n'
    )
    _write_experiment(tmp_path, content)
    with pytest.raises(SystemExit) as exc_info:
        _validate_inputs(tmp_path)
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "Duplicate" in out
    assert "task-1" in out


# --- Check 6: unknown persona_ref ---


def test_unknown_persona_ref(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    content = dedent(
        'schema_version: 1\nid: test-exp\nrunner_factory_ref: tests.unit.engine.test_runner_ref.StubRunnerFactory\npersonas:\n- id: alice\n  description: a persona\n  name: alice\nscenarios:\n- id: task-1\n  description: a task\n  name: task-1\ntarget:\n  name: Test target\n  users: Test users\n  description: Test target\ntasks:\n- id: TC-001\n  scenario_ref: task-1\n  persona_ref: bob\n  fixtures: []\n  num_trials: 1\n  behaviour_refs:\n  - EB-1\nfeatures:\n- id: F-1\n  name: Responses\n  description: Responses\n  behaviours:\n  - id: EB-1\n    name: Respond\n    description: Respond correctly\n    measured: true\n    criteria:\n    - id: AC-1-1\n      name: Check 1\n      description: "Given a request, when the agent responds, then the requirement is met."\n      grader_fqn: tests.unit.engine.graders_for_tests.FixedScoreGrader\n      grader_args: {}\n'
    )
    _write_experiment(tmp_path, content)
    with pytest.raises(SystemExit) as exc_info:
        _validate_inputs(tmp_path)
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "bob" in out or "persona" in out.lower()


# --- Check 7: missing fixture file ---


def test_missing_fixture(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    content = dedent(
        'schema_version: 1\nid: test-exp\nrunner_factory_ref: tests.unit.engine.test_runner_ref.StubRunnerFactory\npersonas:\n- id: alice\n  description: a persona\n  name: alice\nscenarios:\n- id: task-1\n  description: a task\n  name: task-1\ntarget:\n  name: Test target\n  users: Test users\n  description: Test target\ntasks:\n- id: TC-001\n  scenario_ref: task-1\n  persona_ref: alice\n  fixtures:\n  - missing.csv\n  num_trials: 1\n  behaviour_refs:\n  - EB-1\nfeatures:\n- id: F-1\n  name: Responses\n  description: Responses\n  behaviours:\n  - id: EB-1\n    name: Respond\n    description: Respond correctly\n    measured: true\n    criteria:\n    - id: AC-1-1\n      name: Check 1\n      description: "Given a request, when the agent responds, then the requirement is met."\n      grader_fqn: tests.unit.engine.graders_for_tests.FixedScoreGrader\n      grader_args: {}\n'
    )
    _write_experiment(tmp_path, content)
    with pytest.raises(SystemExit) as exc_info:
        _validate_inputs(tmp_path)
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "Task 'TC-001'" in out
    assert "missing.csv" in out
    assert "does not exist" in out


# --- Check 8: non-importable grader FQN ---


def test_bad_grader_fqn(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    content = dedent(
        'schema_version: 1\nid: test-exp\nrunner_factory_ref: tests.unit.engine.test_runner_ref.StubRunnerFactory\npersonas:\n- id: alice\n  description: a persona\n  name: alice\nscenarios:\n- id: task-1\n  description: a task\n  name: task-1\ntarget:\n  name: Test target\n  users: Test users\n  description: Test target\ntasks:\n- id: TC-001\n  scenario_ref: task-1\n  persona_ref: alice\n  fixtures: []\n  num_trials: 1\n  behaviour_refs:\n  - EB-1\nfeatures:\n- id: F-1\n  name: Responses\n  description: Responses\n  behaviours:\n  - id: EB-1\n    name: Respond\n    description: Respond correctly\n    measured: true\n    criteria:\n    - id: AC-1-1\n      name: Check 1\n      description: "Given a request, when the agent responds, then the requirement is met."\n      grader_fqn: no.such.module.FakeGrader\n      grader_args: {}\n'
    )
    _write_experiment(tmp_path, content)
    with pytest.raises(SystemExit) as exc_info:
        _validate_inputs(tmp_path)
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "could not be imported" in out


def test_grader_fqn_naming_a_function_is_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    content = dedent(
        'schema_version: 1\nid: test-exp\nrunner_factory_ref: tests.unit.engine.test_runner_ref.StubRunnerFactory\npersonas:\n- id: alice\n  description: a persona\n  name: alice\nscenarios:\n- id: task-1\n  description: a task\n  name: task-1\ntarget:\n  name: Test target\n  users: Test users\n  description: Test target\ntasks:\n- id: TC-001\n  scenario_ref: task-1\n  persona_ref: alice\n  fixtures: []\n  num_trials: 1\n  behaviour_refs:\n  - EB-1\nfeatures:\n- id: F-1\n  name: Responses\n  description: Responses\n  behaviours:\n  - id: EB-1\n    name: Respond\n    description: Respond correctly\n    measured: true\n    criteria:\n    - id: AC-1-1\n      name: Check 1\n      description: "Given a request, when the agent responds, then the requirement is met."\n      grader_fqn: os.path.join\n      grader_args: {}\n'
    )
    _write_experiment(tmp_path, content)
    with pytest.raises(SystemExit) as exc_info:
        _validate_inputs(tmp_path)
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "not a subclass of metis.library.grader.Grader" in out


# --- Happy path ---


def test_valid_input_passes(tmp_path: Path):
    _write_experiment(tmp_path)
    # Should not raise
    _validate_inputs(tmp_path)


def test_valid_input_with_fixtures(tmp_path: Path):
    content = dedent(
        'schema_version: 1\nid: test-exp\nrunner_factory_ref: tests.unit.engine.test_runner_ref.StubRunnerFactory\npersonas:\n- id: alice\n  description: a persona\n  name: alice\nscenarios:\n- id: task-1\n  description: a task\n  name: task-1\ntarget:\n  name: Test target\n  users: Test users\n  description: Test target\ntasks:\n- id: TC-001\n  scenario_ref: task-1\n  persona_ref: alice\n  fixtures:\n  - data.csv\n  num_trials: 1\n  behaviour_refs:\n  - EB-1\nfeatures:\n- id: F-1\n  name: Responses\n  description: Responses\n  behaviours:\n  - id: EB-1\n    name: Respond\n    description: Respond correctly\n    measured: true\n    criteria:\n    - id: AC-1-1\n      name: Check 1\n      description: "Given a request, when the agent responds, then the requirement is met."\n      grader_fqn: tests.unit.engine.graders_for_tests.FixedScoreGrader\n      grader_args: {}\n'
    )
    _write_experiment(tmp_path, content)
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    (fixtures_dir / "data.csv").write_text("col1,col2\n1,2\n")
    _validate_inputs(tmp_path)


# --- GraderRef input formats ---


def test_grader_ref_all_formats(tmp_path: Path):
    """All accepted GraderRef formats parse without error."""
    content = dedent(
        'schema_version: 1\nid: test-exp\nrunner_factory_ref: tests.unit.engine.test_runner_ref.StubRunnerFactory\npersonas:\n- id: alice\n  description: a persona\n  name: alice\nscenarios:\n- id: task-1\n  description: a task\n  name: task-1\ntarget:\n  name: Test target\n  users: Test users\n  description: Test target\ntasks:\n- id: TC-001\n  scenario_ref: task-1\n  persona_ref: alice\n  fixtures: []\n  num_trials: 1\n  behaviour_refs:\n  - EB-1\nfeatures:\n- id: F-1\n  name: Responses\n  description: Responses\n  behaviours:\n  - id: EB-1\n    name: Respond\n    description: Respond correctly\n    measured: true\n    criteria:\n    - id: AC-1-1\n      name: Check 1\n      description: "Given a request, when the agent responds, then the requirement is met."\n      grader_fqn: tests.unit.engine.graders_for_tests.FixedScoreGrader\n      grader_args: {}\n    - id: AC-1-2\n      name: Check 2\n      description: "Given a request, when the agent responds, then the requirement is met."\n      grader_fqn: tests.unit.engine.graders_for_tests.FixedScoreGrader\n      grader_args:\n        threshold: 0.5\n'
    )
    _write_experiment(tmp_path, content)
    _validate_inputs(tmp_path)


def test_grader_ref_legacy_class_format(tmp_path: Path):
    """Legacy {class: ..., args: ...} format parses without error."""
    from metis.engine.simulation.types import Specification

    content = dedent(
        'schema_version: 1\nid: test-exp\nrunner_factory_ref: tests.unit.engine.test_runner_ref.StubRunnerFactory\npersonas:\n- id: alice\n  description: a persona\n  name: alice\nscenarios:\n- id: task-1\n  description: a task\n  name: task-1\ntarget:\n  name: Test target\n  users: Test users\n  description: Test target\ntasks:\n- id: TC-001\n  scenario_ref: task-1\n  persona_ref: alice\n  fixtures: []\n  num_trials: 1\n  behaviour_refs:\n  - EB-1\nfeatures:\n- id: F-1\n  name: Responses\n  description: Responses\n  behaviours:\n  - id: EB-1\n    name: Respond\n    description: Respond correctly\n    measured: true\n    criteria:\n    - id: AC-1-1\n      name: Check 1\n      description: "Given a request, when the agent responds, then the requirement is met."\n      grader_fqn: tests.unit.engine.graders_for_tests.FixedScoreGrader\n      grader_args:\n        threshold: 0.5\n'
    )
    (tmp_path / "specification.yaml").write_text(content)
    exp = Specification.load_file(tmp_path / "specification.yaml")
    assert (
        exp.resolved_tasks()[0].grader_refs[0].fqn
        == "tests.unit.engine.graders_for_tests.FixedScoreGrader"
    )
    assert exp.resolved_tasks()[0].grader_refs[0].args == {"threshold": 0.5}


def test_grader_ref_null_args(tmp_path: Path):
    """Single-key mapping with null args normalizes to empty dict."""
    from metis.engine.simulation.types import Specification

    content = dedent(
        'schema_version: 1\nid: test-exp\nrunner_factory_ref: tests.unit.engine.test_runner_ref.StubRunnerFactory\npersonas:\n- id: alice\n  description: a persona\n  name: alice\nscenarios:\n- id: task-1\n  description: a task\n  name: task-1\ntarget:\n  name: Test target\n  users: Test users\n  description: Test target\ntasks:\n- id: TC-001\n  scenario_ref: task-1\n  persona_ref: alice\n  fixtures: []\n  num_trials: 1\n  behaviour_refs:\n  - EB-1\nfeatures:\n- id: F-1\n  name: Responses\n  description: Responses\n  behaviours:\n  - id: EB-1\n    name: Respond\n    description: Respond correctly\n    measured: true\n    criteria:\n    - id: AC-1-1\n      name: Check 1\n      description: "Given a request, when the agent responds, then the requirement is met."\n      grader_fqn: tests.unit.engine.graders_for_tests.FixedScoreGrader\n      grader_args: {}\n'
    )
    (tmp_path / "specification.yaml").write_text(content)
    exp = Specification.load_file(tmp_path / "specification.yaml")
    assert (
        exp.resolved_tasks()[0].grader_refs[0].fqn
        == "tests.unit.engine.graders_for_tests.FixedScoreGrader"
    )
    assert exp.resolved_tasks()[0].grader_refs[0].args == {}


# --- extra="ignore" on Persona ---


def test_extra_persona_fields_ignored(tmp_path: Path):
    """Extra fields on persona don't cause validation failure."""
    content = dedent(
        'schema_version: 1\nid: test-exp\nrunner_factory_ref: tests.unit.engine.test_runner_ref.StubRunnerFactory\npersonas:\n- id: alice\n  description: a persona\n  tone: formal\n  mood: cheerful\n  name: alice\nscenarios:\n- id: task-1\n  description: a task\n  name: task-1\ntarget:\n  name: Test target\n  users: Test users\n  description: Test target\ntasks:\n- id: TC-001\n  scenario_ref: task-1\n  persona_ref: alice\n  fixtures: []\n  num_trials: 1\n  behaviour_refs:\n  - EB-1\nfeatures:\n- id: F-1\n  name: Responses\n  description: Responses\n  behaviours:\n  - id: EB-1\n    name: Respond\n    description: Respond correctly\n    measured: true\n    criteria:\n    - id: AC-1-1\n      name: Check 1\n      description: "Given a request, when the agent responds, then the requirement is met."\n      grader_fqn: tests.unit.engine.graders_for_tests.FixedScoreGrader\n      grader_args: {}\n'
    )
    _write_experiment(tmp_path, content)
    _validate_inputs(tmp_path)


# --- Grader contract checks (grader redesign, #428) ---

GRADERS = "tests.unit.engine.graders_for_tests"


def _with_grader(fqn: str, grader_args: str = "{}", *, fixtures: str = "[]") -> str:
    """MINIMAL_EXPERIMENT with its one criterion pointed at ``fqn``."""
    return MINIMAL_EXPERIMENT.replace(
        f"grader_fqn: {GRADERS}.FixedScoreGrader\n      grader_args: {{}}\n",
        f"grader_fqn: {fqn}\n      grader_args: {grader_args}\n",
    ).replace("  fixtures: []\n", f"  fixtures: {fixtures}\n")


def _error(tmp_path: Path, capsys: pytest.CaptureFixture[str], content: str) -> str:
    _write_experiment(tmp_path, content)
    with pytest.raises(SystemExit) as exc_info:
        _validate_inputs(tmp_path)
    assert exc_info.value.code == 1
    return capsys.readouterr().out


def test_class_that_is_not_a_grader_is_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    out = _error(tmp_path, capsys, _with_grader(f"{GRADERS}.NotAGrader"))
    assert "Criterion 'AC-1-1'" in out
    assert "not a subclass of metis.library.grader.Grader" in out


@pytest.mark.parametrize(
    ("grader_args", "message"),
    [
        ("{scroe: 0.3}", "scroe: Extra inputs are not permitted"),
        ("{score: high}", "score: Input should be a valid number"),
        ("{threshold: 1.5}", "threshold: Input should be less than or equal to 1"),
        ("{model: gpt-4o}", "model: Extra inputs are not permitted"),
    ],
)
def test_invalid_grader_args_name_the_criterion_and_field(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], grader_args: str, message: str
):
    out = _error(
        tmp_path, capsys, _with_grader(f"{GRADERS}.FixedScoreGrader", grader_args)
    )
    assert "Criterion 'AC-1-1' has invalid grader_args" in out
    assert message in out


def test_check_setup_errors_are_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    out = _error(
        tmp_path,
        capsys,
        _with_grader(f"{GRADERS}.FixtureGrader", "{fixture: deck.pptx}"),
    )
    assert "Criterion 'AC-1-1': fixture 'deck.pptx' is not used by any task" in out


def test_check_setup_that_raises_is_reported_not_crashed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    out = _error(tmp_path, capsys, _with_grader(f"{GRADERS}.BrokenSetupGrader"))
    assert "Criterion 'AC-1-1': check_setup raised KeyError" in out


def test_check_setup_passes_when_satisfied(tmp_path: Path):
    _write_experiment(
        tmp_path,
        _with_grader(
            f"{GRADERS}.FixtureGrader", "{fixture: deck.pptx}", fixtures="[deck.pptx]"
        ),
    )
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "fixtures" / "deck.pptx").write_bytes(b"PK")
    _validate_inputs(tmp_path)


def test_model_based_grader_validates_without_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Pre-run validation needs no gateway: the model resolves to the package default."""
    for name in ("JUDGE_API_KEY", "OPENAI_API_KEY", "JUDGE_MODEL"):
        monkeypatch.delenv(name, raising=False)
    _write_experiment(tmp_path, _with_grader(f"{GRADERS}.EchoJudgeGrader"))
    _validate_inputs(tmp_path)


def test_old_deepeval_grader_fqn_fails_loudly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """A spec written before the redesign names a grader that no longer exists."""
    old_fqn = ".".join(["metis", "library", "graders", "TurnBudgetGrader"])
    out = _error(tmp_path, capsys, _with_grader(old_fqn))
    assert "has no attribute 'TurnBudgetGrader'" in out


def test_every_bad_criterion_is_reported_before_exiting(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """One run names every criterion to fix, not only the first one."""
    content = _with_grader(f"{GRADERS}.NotAGrader") + (
        "    - id: AC-1-2\n      name: Check 2\n      description: The requirement is met.\n"
        f"      grader_fqn: {GRADERS}.FixedScoreGrader\n"
        "      grader_args: {scroe: 0.3}\n"
    )
    out = _error(tmp_path, capsys, content)
    assert "Criterion 'AC-1-1'" in out
    assert "Criterion 'AC-1-2' has invalid grader_args" in out
