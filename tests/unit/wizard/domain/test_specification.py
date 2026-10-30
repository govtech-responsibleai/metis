"""The document model: round-tripping, the tick, and walking the tree."""

import json
from pathlib import Path

import jsonschema
import pytest
import yaml

import metis.core
from metis.core.experiment import Experiment
from metis.core.profile import TargetProfile
from metis.wizard.contracts import Specification
from tests.fixtures.wizard.specifications import research_assistant

# The schema ships beside the core package (packages/core/schemas), not inside its source, so
# anchor to the installed package rather than to this test file's location.
SCHEMA_PATH = (
    Path(metis.core.__file__).resolve().parents[3]
    / "schemas"
    / "specification.schema.json"
)


def test_round_trips_through_json_unchanged() -> None:
    """Every id, enum value and reference list survives a serialise/parse cycle."""
    original = research_assistant()
    parsed = Specification.model_validate_json(original.model_dump_json())

    assert parsed == original
    # spot-check the structured criterion description and references
    assert parsed.behaviour("EB-3").criteria[0].description.find("it stops") >= 0  # type: ignore[union-attr]
    assert parsed.task("TC-001").behaviour_refs == ["EB-1"]  # type: ignore[union-attr]


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    original = research_assistant()
    path = tmp_path / "specification.yaml"
    original.save(path)

    assert Specification.load(path) == original
    assert list(yaml.safe_load(path.read_text()))[:5] == [
        "schema_version",
        "id",
        "runner_factory_ref",
        "target",
        "features",
    ]


def test_specification_combines_profile_and_experiment() -> None:
    source = research_assistant()
    profile = TargetProfile(target=source.target, features=source.features)
    experiment = Experiment(
        id="research",
        personas=source.personas,
        scenarios=source.scenarios,
        tasks=source.tasks,
    )
    specification = Specification(profile=profile, experiment=experiment)

    assert specification.profile is profile
    assert specification.experiment is experiment
    assert set(profile.model_dump()) == {"target", "features"}
    assert profile.criterion("AC-1-1") == specification.criterion("AC-1-1")
    assert experiment.task("TC-001") == specification.task("TC-001")

    specification.target.name = "Research assistant"
    specification.tasks = specification.tasks[:1]
    assert profile.target.name == "Research assistant"
    assert len(experiment.tasks) == 1
    document = specification.model_dump(mode="json")
    assert document == {
        "schema_version": 1,
        **profile.model_dump(mode="json"),
        **experiment.model_dump(mode="json"),
    }
    assert Specification.model_validate(document) == specification

    copied = specification.model_copy(deep=True)
    copied.profile.target.name = "Copy"
    copied.experiment.tasks.clear()
    assert specification.target.name == "Research assistant"
    assert len(specification.tasks) == 1


def test_unmeasuring_keeps_criteria() -> None:
    """`measured` is scope, not content — the criteria are never derived from it.

    This is what lets the tick stay live without any staleness tracking.
    """
    specification = research_assistant()
    behaviour = specification.behaviour("EB-1")
    assert behaviour is not None
    before = [c.model_copy(deep=True) for c in behaviour.criteria]

    behaviour.measured = False

    assert behaviour.criteria == before
    assert len(behaviour.criteria) == 2


def test_dormant_criteria_survive_on_unmeasured_behaviours() -> None:
    """The fixture's EB-2 is unmeasured but keeps its criterion."""
    specification = research_assistant()
    behaviour = specification.behaviour("EB-2")

    assert behaviour is not None
    assert behaviour.measured is False
    assert len(behaviour.criteria) == 1


def test_measured_behaviours_are_the_behaviours_the_user_chose() -> None:
    """The measurement choice is the user's only real decision."""
    specification = research_assistant()

    assert {b.id for b in specification.measured_behaviours()} == {"EB-1", "EB-3"}
    # EB-2 is unmeasured: still in the document, still carrying criteria
    assert "EB-2" in {b.id for b in specification.behaviours()}


def test_a_behaviour_resolves_to_its_owning_feature() -> None:
    """`Behaviour` carries no feature id — position in the tree is the only link."""
    specification = research_assistant()

    assert specification.feature_of("EB-1").id == "F-1"  # type: ignore[union-attr]
    assert specification.feature_of("EB-3").id == "F-2"  # type: ignore[union-attr]
    assert specification.feature_of("EB-nope") is None


def test_criterion_ids_are_scoped_to_their_behaviour() -> None:
    specification = research_assistant()
    behaviour = specification.behaviour("EB-1")

    assert behaviour is not None
    assert [c.id for c in behaviour.criteria] == ["AC-1-1", "AC-1-2"]


def test_coverage_and_trial_count() -> None:
    specification = research_assistant()

    assert specification.uncovered() == []
    assert [t.id for t in specification.scenarios_covering("EB-1")] == ["S-1"]
    # S-1: 2 personas × 3 trials = 6; S-2: 1 × 3 = 3
    assert specification.trial_count() == 9

    specification.tasks[2].num_trials = 1
    assert specification.trial_count() == 7

    specification.tasks = specification.tasks[2:]
    assert specification.trial_count() == 1


def test_uncovered_reports_ticked_behaviours_with_no_scenario() -> None:
    specification = research_assistant()
    specification.scenarios = [t for t in specification.scenarios if t.id != "S-2"]

    assert [b.id for b in specification.uncovered()] == ["EB-3"]


def test_full_specification_validates_against_committed_schema() -> None:
    """A specification exercising every shape conforms to the shipped specification.schema.json."""
    schema = json.loads(SCHEMA_PATH.read_text())
    jsonschema.validate(
        instance=research_assistant().model_dump(mode="json"), schema=schema
    )


def test_save_and_load_round_trip_survives_non_ascii(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A target description the interview or a hand-authored specification wrote can
    contain any character a person can type — not just ASCII. save()/load()
    must round-trip it exactly, and never rely on the platform's locale
    encoding to do so (issue #385)."""
    import pathlib

    original_write_text = pathlib.Path.write_text
    encodings_used: list[str | None] = []

    def spy_write_text(self: pathlib.Path, data: str, *args: object, **kwargs: object):
        encodings_used.append(kwargs.get("encoding"))  # type: ignore[arg-type]
        return original_write_text(self, data, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(pathlib.Path, "write_text", spy_write_text)

    specification = research_assistant()
    specification.target.description = "Swipe to metric → see detail"
    path = tmp_path / "specification.yaml"

    specification.save(path)

    assert encodings_used == ["utf-8"]
    assert "→" in path.read_text(encoding="utf-8")
    assert Specification.load(path) == specification
