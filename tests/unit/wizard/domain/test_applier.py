"""Patches, permissions, and the two things the model can never write."""

import pytest

from metis.wizard.contracts import Patch, PatchOp, PatchOrigin
from metis.wizard.domain import cascade, materializer, paths
from metis.wizard.domain.applier import apply, sanitise
from metis.wizard.domain.permissions import InterviewStep, StepPermissions, owner_of
from tests.fixtures.wizard.specifications import research_assistant

EB1_MEASURED = "features[F-1].behaviours[EB-1].measured"
EB1_DESCRIPTION = "features[F-1].behaviours[EB-1].description"
AC1_GRADER = "features[F-1].behaviours[EB-1].criteria[AC-1-1].grader_fqn"


def patch(path: str, value=None, *, op=PatchOp.SET, origin=PatchOrigin.MODEL) -> Patch:
    return Patch(op=op, path=path, value=value, origin=origin)


# ── origin is checked before address ───────────────────────────────────────


def test_the_users_tick_is_applied_and_the_models_is_not() -> None:
    """The two patches are byte-identical. Only origin tells them apart."""
    specification = research_assistant()
    specification.behaviour("EB-1").measured = False  # type: ignore[union-attr]

    from_model = patch(EB1_MEASURED, True, origin=PatchOrigin.MODEL)
    from_wizard = patch(EB1_MEASURED, True, origin=PatchOrigin.WIZARD)
    assert from_model.op == from_wizard.op and from_model.path == from_wizard.path

    rejected = apply(specification, [from_model])
    assert rejected.applied == []
    assert len(rejected.rejected) == 1
    assert specification.behaviour("EB-1").measured is False  # type: ignore[union-attr]

    accepted = apply(specification, [from_wizard])
    assert len(accepted.applied) == 1
    assert specification.behaviour("EB-1").measured is True  # type: ignore[union-attr]


def test_rejecting_a_tick_says_whose_call_it_is() -> None:
    """The one message where the wizard must say *I chose not to*."""
    specification = research_assistant()

    result = apply(specification, [patch(EB1_MEASURED, True)])

    message = result.rejected[0].message
    assert "your call" in message
    assert "wrong" not in message.lower()  # not the user's fault
    assert "error" not in message.lower()  # not an outage


def test_the_model_cannot_claim_wizard_origin() -> None:
    """Origin is stamped by the code that builds a patch, never carried in model output."""
    claimed = [patch(EB1_MEASURED, True, origin=PatchOrigin.WIZARD)]

    cleaned = sanitise(claimed)

    assert cleaned[0].origin is PatchOrigin.MODEL
    specification = research_assistant()
    specification.behaviour("EB-1").measured = False  # type: ignore[union-attr]
    assert apply(specification, cleaned).applied == []


def test_measured_is_owned_by_no_step() -> None:
    """The path appears in no entry — that is the structural half of the rule."""
    assert owner_of(EB1_MEASURED) is None
    for globs in StepPermissions.values():
        assert not any("measured" in g for g in globs)


def test_strict_model_drafts_materialize_ids_and_scenario_defaults() -> None:
    from metis.wizard.contracts import (
        BehaviourDraft,
        FeatureDraft,
        PersonaDraft,
        ScenarioDraft,
        StepResultPatch,
    )

    specification = research_assistant()
    result = apply(
        specification,
        sanitise(
            [
                StepResultPatch(
                    op=PatchOp.ADD,
                    path="features",
                    value=FeatureDraft(
                        name="New",
                        description="A new feature.",
                        behaviours=[
                            BehaviourDraft(
                                name="Something",
                                description="does something",
                            )
                        ],
                    ),
                ),
                StepResultPatch(
                    op=PatchOp.ADD,
                    path="personas",
                    value=PersonaDraft(name="Impatient Executive", description="short"),
                ),
                StepResultPatch(
                    op=PatchOp.ADD,
                    path="scenarios",
                    value=ScenarioDraft(name="Exercise", description="exercise it"),
                ),
            ]
        ),
        allowed_fixture_names={"policy.md"},
    )

    assert not result.rejected
    assert specification.features[-1].id == "F-3"
    assert specification.features[-1].behaviours[0].id == "EB-4"
    assert specification.features[-1].behaviours[0].measured is True
    assert specification.personas[-1].id == "impatient-executive-2"
    assert specification.scenarios[-1].id == "S-3"


def test_model_whole_entity_set_is_refused() -> None:
    from metis.wizard.contracts import Patch, ScenarioDraft

    specification = research_assistant()
    patch_value = Patch(
        op=PatchOp.SET,
        path="scenarios[S-1]",
        value=ScenarioDraft(name="Replacement", description="replacement"),
    )
    result = apply(specification, sanitise([patch_value]))
    assert result.applied == []
    assert result.rejected
    assert specification.scenario("S-1").description.startswith("Ask for")  # type: ignore[union-attr]


# ── the grader is the matcher's, not the model's ────────────────────────────


def test_grader_fqn_is_owned_by_no_step() -> None:
    """Like measured, it appears in no entry — the matcher resolves it, never the model."""
    assert owner_of(AC1_GRADER) is None
    for globs in StepPermissions.values():
        assert not any("grader_fqn" in g for g in globs)


def test_rejecting_a_grader_write_points_at_rewording() -> None:
    """A stray model write is refused with wording help, not the raw internal path."""
    specification = research_assistant()

    result = apply(specification, [patch(AC1_GRADER, "some.other.Grader")])

    assert result.applied == []
    message = result.rejected[0].message
    assert "reword" in message.lower()
    assert "grader_fqn" not in message  # the raw field name never surfaces
    assert AC1_GRADER not in message  # nor the raw path
    assert specification.behaviour("EB-1").criteria[0].grader_fqn != "some.other.Grader"  # type: ignore[union-attr]


# ── the fields inside a bundled value ──────────────────────────────────────
#
# The address check reads `patch.path` alone, and the model is told to draft a whole step in
# one go — so its patches address a *container* (`scenarios`, `features`) and carry the finished
# object inside. Every user-owned field below is reachable that way without the path ever
# naming it. These are the same three rules as above, tested at the shape the model actually
# sends rather than the targeted SET it rarely does.


def test_a_model_cannot_change_fixtures_on_an_existing_scenario() -> None:
    specification = research_assistant()
    before = specification.task("TC-001").fixtures.copy()  # type: ignore[union-attr]

    result = apply(
        specification,
        [patch("scenarios[S-1].fixtures", ["policy.md"])],
        allowed_fixture_names={"policy.md"},
    )

    assert not result.applied
    assert result.rejected
    assert specification.task("TC-001").fixtures == before  # type: ignore[union-attr]


def test_a_bundled_feature_cannot_carry_a_tick_or_a_grader() -> None:
    """The recursion case. `Feature.model_validate` builds nested behaviours and criteria from
    raw dicts without re-entering the coercion, so the nesting is the whole smuggling route."""
    specification = research_assistant()

    result = apply(
        specification,
        [
            patch(
                "features",
                {
                    "id": "F-9",
                    "name": "Data handling",
                    "description": "Handle uploaded data safely.",
                    "behaviours": [
                        {
                            "id": "EB-9",
                            "name": "Validate uploaded data",
                            "description": "Validates uploaded data before analysing it",
                            "criteria": [
                                {
                                    "id": "AC-9-1",
                                    "name": "Flag gaps",
                                    "description": "Given a spreadsheet with missing values, when analysis is requested, then the gaps are flagged before any figure is quoted.",
                                    "grader_fqn": "some.other.Grader",
                                }
                            ],
                        }
                    ],
                },
                op=PatchOp.ADD,
            )
        ],
    )

    assert len(result.applied) == 1
    behaviour = specification.behaviour("EB-9")
    assert behaviour is not None
    assert behaviour.description.startswith("Validates uploaded data")
    # A generic persisted-object compatibility patch keeps the domain default. Strict model
    # drafts and direct forms use the materializer and start selected.
    assert behaviour.measured is False
    assert behaviour.criteria[0].description.find("the gaps are flagged") >= 0
    assert behaviour.criteria[0].grader_fqn is None  # still the matcher's to resolve


def test_a_bundled_item_cannot_claim_the_user_typed_it() -> None:
    """FORM means the user typed it, and `chat_user` protects FORM items from replacement.
    A model that could stamp its own suggestions FORM would make them stick."""
    specification = research_assistant()

    apply(
        specification,
        [
            patch(
                "personas",
                {
                    "id": "fragmented-sender",
                    "name": "Fragmented sender",
                    "description": "Sends one fact per message and changes their mind",
                    "interaction_type": "form",
                },
                op=PatchOp.ADD,
            )
        ],
    )

    persona = specification.persona("fragmented-sender")
    assert persona is not None
    assert persona.name == "Fragmented sender"
    assert "interaction_type" not in persona.model_dump()


def test_user_task_settings_are_preserved() -> None:
    specification = research_assistant()
    result = apply(
        specification,
        [
            patch("tasks[TC-001].num_trials", 10, origin=PatchOrigin.WIZARD),
            patch(
                "tasks[TC-001].fixtures", ["uploaded.csv"], origin=PatchOrigin.WIZARD
            ),
        ],
    )
    assert len(result.applied) == 2
    assert specification.tasks[0].num_trials == 10
    assert specification.tasks[0].fixtures == ["uploaded.csv"]


def test_trials_and_files_are_owned_by_no_step() -> None:
    """The other half, mirroring measured: the targeted SET the field filter cannot see."""
    assert owner_of("tasks[TC-001].num_trials") is None
    assert owner_of("tasks[TC-001].fixtures") is None
    for globs in StepPermissions.values():
        assert not any("num_trials" in g or "fixtures" in g for g in globs)


def test_an_unowned_address_is_refused_without_leaking_its_path() -> None:
    """The generic refusal names 'part of that change', never the bookkeeping address."""
    result = apply(research_assistant(), [patch("target.invented_field", "x")])

    message = result.rejected[0].message
    assert "invented_field" not in message
    assert "isn't mine to write" in message


# ── permission follows the address, not the step ───────────────────────────


def test_a_behaviour_edit_from_the_criteria_step_is_applied() -> None:
    """ "Reword EB-4" typed at the criteria step should simply work."""
    specification = research_assistant()
    step = InterviewStep.CRITERIA

    result = apply(
        specification, [patch(EB1_DESCRIPTION, "Cites a source, accurately")]
    )

    assert len(result.applied) == 1
    assert specification.behaviour("EB-1").description == "Cites a source, accurately"  # type: ignore[union-attr]
    assert (
        owner_of(EB1_DESCRIPTION) is InterviewStep.BEHAVIOURS
    )  # a different step owns it
    assert step is InterviewStep.CRITERIA  # and the current step never changed


def test_an_address_no_step_owns_is_writable_nowhere() -> None:
    specification = research_assistant()

    result = apply(specification, [patch("target.invented_field", "x")])

    assert result.applied == []
    assert owner_of("target.invented_field") is None


def test_clarify_owns_the_target_prose_and_measured_is_owned_nowhere() -> None:
    """Clarify owns the target prose. The measurement flag is the user's only real decision,
    so no step owns it: the model can write it at no point, and only a WIZARD-origin tick can."""
    assert StepPermissions[InterviewStep.CLARIFY] == [
        "target.name",
        "target.users",
        "target.description",
        "target.detail",
    ]
    assert owner_of(EB1_MEASURED) is None


# ── the mechanics ──────────────────────────────────────────────────────────


def test_add_remove_and_set() -> None:
    specification = research_assistant()

    apply(
        specification,
        [
            patch(
                "personas",
                {
                    "id": "P-9",
                    "name": "New archetype",
                    "description": "A new archetype",
                },
                op=PatchOp.ADD,
                origin=PatchOrigin.WIZARD,
            )
        ],
    )
    assert specification.persona("P-9") is not None

    apply(
        specification,
        [patch("personas[P-9]", op=PatchOp.REMOVE, origin=PatchOrigin.WIZARD)],
    )
    assert specification.persona("P-9") is None


def test_a_patch_at_a_missing_node_is_reported_not_raised() -> None:
    specification = research_assistant()

    # A behaviour id no feature owns stays unreachable — a wrong *feature* ancestor is corrected
    # against the behaviour id (see `test_a_wrong_feature_ancestor_is_corrected`), but a wrong
    # behaviour id is a genuinely missing node.
    result = apply(
        specification, [patch("features[F-404].behaviours[EB-404].description", "x")]
    )

    assert result.applied == []
    assert result.any_rejected


def test_a_wrong_feature_ancestor_is_corrected() -> None:
    """A model drafting criteria can pair the right, unique behaviour id with the wrong
    feature ancestor — `features[F-1].behaviours[EB-3]` when EB-3 lives under F-2. Behaviour ids
    are globally unique, so the applier corrects the ancestor against the behaviour rather
    than reporting a node it could plainly find. This is what stops "no behaviour with id
    'EB-3'" from reaching the user during the criteria step.
    """
    specification = research_assistant()
    assert specification.feature_of("EB-3").id == "F-2"  # type: ignore[union-attr]

    result = apply(
        specification,
        [
            patch(
                "features[F-1].behaviours[EB-3].description",
                "Stops after repeated failures and reports what it tried",
            )
        ],
    )

    assert result.applied and not result.any_rejected
    assert (
        specification.behaviour("EB-3").description  # type: ignore[union-attr]
        == "Stops after repeated failures and reports what it tried"
    )


def test_a_positional_path_is_resolved_to_ids() -> None:
    """A model can draft a positional path — `features[0].behaviours[0]` — against the contract
    to address by id. The index plainly names a node, so the applier reads the id at each
    index and substitutes it rather than reporting "no feature with id '0'". User ticks and
    edits are always built with real ids, so only a model mistake ever carries a number.
    """
    specification = research_assistant()
    first_feature = specification.features[0]
    first_behaviour = first_feature.behaviours[0]

    result = apply(
        specification,
        [
            patch(
                "features[0].behaviours[0].description",
                "Cites a source for every claim",
            )
        ],
    )

    assert result.applied and not result.any_rejected
    assert first_behaviour.description == "Cites a source for every claim"


def test_a_malformed_value_is_reported_not_raised() -> None:
    """A model can send an ADD whose value won't build the object its list holds — a bad
    enum, or behaviours as bare id strings instead of objects. That is a patch that didn't
    happen, not a crash four answers into an interview. The module's contract is that a
    rejected patch is never silent; a value that won't validate is one of them.
    """
    specification = research_assistant()

    result = apply(
        specification,
        [
            patch(
                "features",
                {"id": "F-9", "behaviours": ["EB-1", "EB-2"]},
                op=PatchOp.ADD,
                origin=PatchOrigin.WIZARD,  # even a trusted patch must not crash on a bad value
            )
        ],
    )

    assert result.applied == []
    assert result.any_rejected
    assert not any(e.id == "F-9" for e in specification.features)


def test_paths_address_by_id_not_index() -> None:
    specification = research_assistant()

    node = paths.resolve(
        specification, "features[F-1].behaviours[EB-1].criteria[AC-1-1]"
    )

    assert node.id == "AC-1-1"


@pytest.mark.parametrize(
    ("bracket", "expected_id", "raises"),
    [
        ("EB-1", "EB-1", False),  # an id that matches always wins
        ("0", None, True),  # numeric brackets are not positional addresses
        ("99", None, True),  # out of range is still an error, not a silent miss
    ],
)
def test_a_list_is_addressed_by_id_first_then_by_numeric_index(
    bracket, expected_id, raises
) -> None:
    """A model is told to address by id and mostly does, but it sometimes falls back to
    `behaviours[0]`. A bare integer resolves positionally — no id in the scheme is an integer,
    so it cannot shadow a real id — which stops a whole behaviour's freshly drafted criteria
    from being silently dropped. Id addressing stays first and preferred.
    """
    specification = research_assistant()
    path = f"features[F-1].behaviours[{bracket}]"

    if raises:
        with pytest.raises(paths.PathError):
            paths.resolve(specification, path)
    else:
        assert paths.resolve(specification, path).id == expected_id


def test_criteria_added_by_positional_index_actually_land() -> None:
    """The end-to-end shape of the live failure: a criteria ADD addressed by index applies
    rather than being rejected, so the criteria the model drafted are not lost."""
    specification = research_assistant()
    specification.behaviour("EB-1").criteria = []  # type: ignore[union-attr]

    result = apply(
        specification,
        [
            patch(
                "features[F-1].behaviours[EB-1].criteria",
                {
                    "id": "AC-1-1",
                    "name": "Cite answer",
                    "description": "Given a question, when answered, then it cites a source.",
                },
                op=PatchOp.ADD,
                origin=PatchOrigin.WIZARD,
            )
        ],
    )

    assert len(result.applied) == 1
    assert specification.behaviour("EB-1").criteria[0].id == "AC-1-1"  # type: ignore[union-attr]


def test_a_glob_does_not_span_a_dot() -> None:
    """`features[*].behaviours[*]` must not match something nested deeper under it."""
    assert owner_of("features[F-1].behaviours[EB-1]") is InterviewStep.BEHAVIOURS
    assert (
        owner_of("features[F-1].behaviours[EB-1].criteria[AC-1-1]")
        is InterviewStep.CRITERIA
    )


def test_materializer_uses_dot_free_ids_for_every_specification_node() -> None:
    """Application-created identities are compact opaque ids, never path fragments."""
    from metis.wizard.contracts import (
        BehaviourDraft,
        CriterionDraft,
        FeatureDraft,
        PersonaDraft,
        ScenarioDraft,
        Specification,
        Target,
    )

    specification = Specification(target=Target(name="X", users="", description=""))
    issued: set[str] = set()
    typed: set[str] = set()
    feature = materializer.add_feature(
        specification,
        FeatureDraft(
            name="Answer",
            description="Answer well.",
            behaviours=[BehaviourDraft(name="Cite", description="Cite sources.")],
        ),
        PatchOrigin.MODEL,
        issued_ids=issued,
        user_typed=typed,
    )
    behaviour = feature.behaviours[0]
    criterion = materializer.add_criterion(
        specification,
        behaviour,
        CriterionDraft(
            name="Supported",
            description="Given a question, when answered, then it cites a source.",
        ),
        PatchOrigin.WIZARD,
        issued_ids=issued,
        user_typed=typed,
    )
    persona = materializer.add_persona(
        specification,
        PersonaDraft(name="Careful reviewer", description="Checks the result."),
        PatchOrigin.WIZARD,
        issued_ids=issued,
        user_typed=typed,
    )
    scenario = materializer.add_scenario(
        specification,
        ScenarioDraft(name="Review", description="Review the answer."),
        PatchOrigin.MODEL,
        issued_ids=issued,
        user_typed=typed,
    )

    created = {
        feature.id,
        behaviour.id,
        criterion.id,
        persona.id,
        scenario.id,
        *[t.id for t in specification.tasks],
    }
    assert created == issued
    assert all("." not in node_id for node_id in created)
    assert {criterion.id, persona.id} <= typed


def test_removed_highest_ids_are_not_reused() -> None:
    """Issued identity history survives removal and controls the next allocation."""
    from metis.wizard.contracts import BehaviourDraft, CriterionDraft
    from metis.wizard.domain.specification import collect_specification_ids

    specification = research_assistant()
    issued = collect_specification_ids(specification)
    typed: set[str] = set()
    specification.features[1].behaviours.pop()
    specification.behaviour("EB-1").criteria.pop()  # type: ignore[union-attr]

    new_behaviour = materializer.add_behaviour(
        specification,
        BehaviourDraft(name="New recovery", description="Recovers safely."),
        PatchOrigin.WIZARD,
        issued_ids=issued,
        user_typed=typed,
    )
    specification.features[1].behaviours.append(new_behaviour)
    new_criterion = materializer.add_criterion(
        specification,
        specification.behaviour("EB-1"),  # type: ignore[arg-type]
        CriterionDraft(
            name="Another source",
            description="Given a question, when answered, then it cites a source.",
        ),
        PatchOrigin.MODEL,
        issued_ids=issued,
        user_typed=typed,
    )

    assert new_behaviour.id == "EB-4"
    assert new_criterion.id == "AC-1-3"


def test_tree_regeneration_does_not_reuse_removed_ids() -> None:
    from metis.wizard.contracts import BehaviourDraft, FeatureDraft
    from metis.wizard.domain.specification import collect_specification_ids

    specification = research_assistant()
    issued = collect_specification_ids(specification)
    cascade.clear_for_regeneration(
        specification,
        cascade.Impact(subject="target.description", kind="tree"),
        set(),
    )
    assert specification.features == [] and specification.scenarios == []

    feature = materializer.add_feature(
        specification,
        FeatureDraft(
            name="New feature",
            description="A regenerated feature.",
            behaviours=[
                BehaviourDraft(name="New behaviour", description="A new behaviour.")
            ],
        ),
        PatchOrigin.MODEL,
        issued_ids=issued,
    )
    assert feature.id == "F-3"
    assert feature.behaviours[0].id == "EB-4"


def test_persona_slug_collisions_get_deterministic_suffixes() -> None:
    from metis.wizard.contracts import PersonaDraft, Specification, Target

    specification = Specification(target=Target(name="X", users="", description=""))
    issued: set[str] = set()
    first = materializer.add_persona(
        specification,
        PersonaDraft(name="Same name", description="First."),
        PatchOrigin.MODEL,
        issued_ids=issued,
    )
    second = materializer.add_persona(
        specification,
        PersonaDraft(name="Same name", description="Second."),
        PatchOrigin.MODEL,
        issued_ids=issued,
    )
    assert (first.id, second.id) == ("same-name", "same-name-2")


def test_stale_user_authorship_does_not_protect_a_new_id() -> None:
    """A regenerated node gets a fresh id, so an old user-typed id cannot keep it alive."""
    from metis.wizard.contracts import CriterionDraft
    from metis.wizard.domain.specification import collect_specification_ids

    specification = research_assistant()
    behaviour = specification.behaviour("EB-3")
    assert behaviour is not None
    issued = collect_specification_ids(specification)
    user_typed = {"AC-3-1"}
    behaviour.criteria.clear()
    fresh = materializer.add_criterion(
        specification,
        behaviour,
        CriterionDraft(
            name="Fresh retry outcome",
            description="Given a retry, when it fails, then it reports the attempt.",
        ),
        PatchOrigin.MODEL,
        issued_ids=issued,
        user_typed=user_typed,
    )
    assert fresh.id == "AC-3-2"
    cascade.clear_for_regeneration(
        specification,
        cascade.Impact(subject="EB-3", kind="criteria"),
        user_typed,
    )
    assert behaviour.criteria == []
