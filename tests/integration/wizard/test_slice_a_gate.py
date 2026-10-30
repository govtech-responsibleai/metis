"""Slice A gate: a hand-written specification compiles to something the engine actually loads.

This is the end of the first build slice. No model call has happened anywhere in it — the
specification is written by hand, the compiler is a pure function, and the engine's own validator
is the judge. If this passes, the output contract is proven before anything upstream of it
exists.

`_validate_inputs` is the engine's real load path, not a stand-in: it parses `specification.yaml`
through `Specification`, checks persona references resolve, checks every fixture file is present,
and imports every grader FQN via `importlib` to confirm it is a real grader class. That last
part is the one that matters most here — grader FQNs are strings until run time, so a typo in
a compiled file is invisible until something tries to import it.
"""

import io
import json
import zipfile
from pathlib import Path

import pytest
import yaml

from metis.wizard import (
    ConnectionTransport,
    InterviewState,
    Specification,
    SpecificationFixture,
    package_specification,
    set_connection,
)
from metis.wizard.application.compile import (
    write_experiment,
    write_review,
)
from tests.fixtures.wizard.connections import connection
from tests.fixtures.wizard.context import interview_context
from tests.fixtures.wizard.specifications import CITATION_GRADER, research_assistant

EXPERIMENT_ID = "research-assistant"


def _input_dir(tmp_path: Path) -> Path:
    """Compile a specification into the directory layout the engine reads.

    The engine's input directory is `specification.yaml` plus a `fixtures/` folder — there is
    no separate personas file, because personas are inline.
    """
    specification = research_assistant()
    write_experiment(specification, EXPERIMENT_ID, tmp_path / "specification.yaml")
    write_review(specification, EXPERIMENT_ID, tmp_path / "review.md")

    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    for scenario in specification.tasks:
        for name in scenario.fixtures:
            (fixtures / name).write_text("stand-in fixture\n")

    return tmp_path


def test_the_engine_loads_the_compiled_experiment(tmp_path: Path) -> None:
    from metis.engine.cli import _validate_inputs

    input_dir = _input_dir(tmp_path)

    # `_validate_inputs` calls sys.exit(1) on any problem, so reaching the end is the pass.
    _validate_inputs(input_dir)

    assert (input_dir / "specification.yaml").is_file()
    assert (input_dir / "review.md").is_file()


def test_the_gate_would_catch_an_unimportable_grader(tmp_path: Path) -> None:
    """Proves the gate is actually checking, rather than passing vacuously.

    FQNs are resolved by importlib at run time, so an experiment naming a grader that has
    moved stops loading. Not silent — which is what this asserts.
    """
    from metis.engine.cli import _validate_inputs

    input_dir = _input_dir(tmp_path)
    experiment = input_dir / "specification.yaml"
    original = experiment.read_text()
    # A grader that does not exist, in a module that does. Sourced from the fixture so this
    # cannot quietly become a no-op if the compiled graders change.
    dead_fqn = CITATION_GRADER + "Removed"
    assert CITATION_GRADER in original, (
        "the corrupted grader must actually be compiled in"
    )
    experiment.write_text(original.replace(CITATION_GRADER, dead_fqn))

    with pytest.raises(SystemExit) as exit_info:
        _validate_inputs(input_dir)

    assert exit_info.value.code == 1


@pytest.mark.parametrize("interview", [False, True])
def test_the_specification_package_passes_the_engine_input_gate(
    interview: bool,
    tmp_path: Path,
    repo_root: Path,
) -> None:
    """The web transform's shared Specification produces the complete runnable package."""
    from metis.engine.cli import _validate_inputs

    specification_path = repo_root / "tests/fixtures/wizard/manual_specification.json"
    specification = Specification.model_validate(
        json.loads(specification_path.read_text())
    )
    source = (
        InterviewState(specification=specification, context=interview_context())
        if interview
        else specification
    )
    archive_bytes = package_specification(
        source,
        [
            SpecificationFixture("policy.pdf", io.BytesIO(b"policy")),
            SpecificationFixture("notes.txt", io.BytesIO(b"notes")),
        ],
    )
    archive = tmp_path / "specification.zip"
    archive.write_bytes(archive_bytes.content)

    root = archive_bytes.filename.removesuffix(".zip")
    extracted = tmp_path / "extracted"
    with zipfile.ZipFile(archive) as specification:
        expected = {
            "inputs/",
            "outputs/specification.yaml",
            "outputs/fixtures/",
            "outputs/fixtures/notes.txt",
            "outputs/fixtures/policy.pdf",
        }
        if interview:
            expected.add("inputs/interview_state.json")
        assert set(specification.namelist()) == {f"{root}/{name}" for name in expected}
        specification.extractall(extracted)

    extracted = extracted / root

    from metis.engine.simulation.types import Specification as EngineSpecification

    experiment = yaml.safe_load((extracted / "outputs/specification.yaml").read_text())
    assert [task["id"] for task in experiment["tasks"]] == [
        "TC-001",
        "TC-002",
        "TC-003",
    ]
    graders = {
        scenario.id: [ref.fqn for ref in scenario.grader_refs]
        for scenario in EngineSpecification.model_validate(experiment).resolved_tasks()
    }
    assert graders == {
        "supported-answer": [
            "tests.unit.engine.graders_for_tests.FixedScoreGrader",
            "metis.library.graders.demo.DemoTraceBudgetGrader",
        ],
        "short-recovery": ["metis.library.graders.demo.DemoTraceBudgetGrader"],
    }
    _validate_inputs(extracted / "outputs")


@pytest.mark.parametrize("transport", [None, *ConnectionTransport])
def test_the_engine_builds_the_runner_factory_that_a_download_names(
    transport: ConnectionTransport | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run-mode download loads into the generic runner factory; a spec-only one keeps the default.

    The engine copies `outputs/` to the experiment's `inputs/`, so the factory reads the
    binding from there. No request reaches a target: the factory only loads the binding.
    """
    from metis.engine.cli import _validate_inputs
    from metis.engine.simulation.runner_resolver import resolve_runner_factory
    from metis.engine.simulation.types import Specification as EngineSpecification

    for name, value in (
        ("APP_URL", "https://app.example"),
        ("APP_KEY", "key"),
        ("APP_USER", "alice"),
        ("APP_PASSWORD", "password"),
    ):
        monkeypatch.setenv(name, value)
    state = InterviewState(
        specification=research_assistant(), context=interview_context()
    )
    if transport is not None:
        state = set_connection(state, connection(transport))
    archive = package_specification(
        state,
        [
            SpecificationFixture(name, io.BytesIO(b"fixture"))
            for name in {n for task in state.specification.tasks for n in task.fixtures}
        ],
    )
    with zipfile.ZipFile(io.BytesIO(archive.content)) as specification:
        specification.extractall(tmp_path)
    outputs = tmp_path / archive.filename.removesuffix(".zip") / "outputs"
    _validate_inputs(outputs)

    loaded = EngineSpecification.load_file(outputs / "specification.yaml")
    factory_cls = resolve_runner_factory(loaded.runner_factory_ref)
    if transport is None:
        assert factory_cls.__name__ == "HttpRunnerFactory"
        assert loaded.target_binding is None
        return
    factory = factory_cls.from_specification(loaded, outputs)
    assert factory.binding.binding.transport == transport.value
