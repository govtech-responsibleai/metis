"""The patch review: one decision on every model result, before anything is applied."""

import pytest

from metis.wizard.application.patch_review import PatchScope, review_patches
from metis.wizard.contracts import Patch, PatchOp, StepResultPatch
from metis.wizard.domain.applier import apply
from metis.wizard.domain.permissions import PatchReason
from metis.wizard.domain.specification import collect_specification_ids
from tests.fixtures.wizard.specifications import research_assistant

EB1 = "features[F-1].behaviours[EB-1]"
AC11 = f"{EB1}.criteria[AC-1-1]"
EB3 = "features[F-2].behaviours[EB-3]"
AC31 = f"{EB3}.criteria[AC-3-1]"


def set_(path: str, value: object) -> Patch:
    return Patch(op=PatchOp.SET, path=path, value=value)


def add(path: str, value: dict) -> StepResultPatch:
    """An ADD as the model sends it: the value is a strict draft."""
    return StepResultPatch.model_validate(Patch(op=PatchOp.ADD, path=path, value=value))


PERSONA = {
    "name": "Sceptic",
    "description": "Doubts every answer and asks for sources.",
}
CRITERION = {
    "name": "Names the source",
    "description": "Given a question, when the answer returns, then it names a source.",
}


@pytest.mark.parametrize(
    ("scope", "inside", "outside"),
    [
        # A chat on one Criteria card writes that Behaviour's Criteria only.
        (
            PatchScope.under({f"{EB1}.criteria"}, user_message=True),
            set_(f"{AC11}.name", "Cites"),
            set_(f"{EB3}.criteria[AC-3-1].name", "Elsewhere"),
        ),
        # A drafting step adds to its own collection only.
        (
            PatchScope.exactly({"personas"}, {PatchOp.ADD}),
            add("personas", PERSONA),
            add("features[F-1].behaviours", {"name": "Extra", "description": "x"}),
        ),
        # Clarify writes the Target prose only.
        (
            PatchScope.exactly({"target.name", "target.detail"}),
            set_("target.detail", "It also summarises."),
            set_(f"{EB1}.description", "Clarify must not reach this"),
        ),
        # A follow-up call must not change the text that the user typed.
        (
            PatchScope(locked_items=frozenset({"AC-1-1"})),
            set_(f"{EB1}.criteria[AC-1-2].name", "Untyped"),
            set_(f"{AC11}.description", "Typed text must stay"),
        ),
    ],
    ids=["card chat", "drafting step", "clarify", "typed item"],
)
def test_a_patch_outside_the_scope_is_a_problem(scope, inside, outside) -> None:
    specification = research_assistant()

    review = review_patches(specification, [outside, inside], scope)

    assert [patch.path for patch in review.accepted] == [inside.path]
    assert [(problem.path, problem.reason) for problem in review.problems] == [
        (outside.path, PatchReason.OUTSIDE_SCOPE)
    ]
    assert specification == research_assistant()


@pytest.mark.parametrize(
    ("patch", "reason"),
    [
        (set_(f"{AC11}.grader_fqn", "some.Grader"), PatchReason.GRADER),
        (set_(f"{EB1}.measured", False), PatchReason.MEASURED),
        (set_("features[F-1].behaviours[EB-9].name", "x"), PatchReason.UNKNOWN_ADDRESS),
        (set_("personas[cooperative-delegator]", PERSONA), PatchReason.WHOLE_ITEM),
        (set_(f"{EB1}.description", ["not", "text"]), PatchReason.BAD_VALUE),
    ],
    ids=lambda value: getattr(value, "value", None) or "",
)
def test_each_refused_patch_is_a_problem_with_its_reason(patch, reason) -> None:
    review = review_patches(
        research_assistant(), [patch, set_(f"{EB1}.name", "Cites")], PatchScope()
    )

    assert [problem.reason for problem in review.problems] == [reason]
    assert [p.path for p in review.accepted] == [f"{EB1}.name"]


@pytest.mark.parametrize(
    ("failing", "reason"),
    [
        # The pass mark is a number from 0 to 1. The grader rejects 1.5.
        (set_(f"{AC11}.grader_args.threshold", 1.5), PatchReason.INVALID_SETTING),
        # Two settings of one Criterion: only the setting that the grader rejects is removed.
        (set_(f"{AC31}.grader_args.max_traces", 0), PatchReason.INVALID_SETTING),
        # A grader accepts only the judgment forms that it declares.
        (
            set_(f"{AC31}.grader_args.judgment_form", "scalar"),
            PatchReason.INVALID_SETTING,
        ),
        (set_("tasks[TC-001].persona_ref", "nobody"), PatchReason.BROKEN_REFERENCE),
        # EB-2 exists, but it is not measured.
        (set_("tasks[TC-001].behaviour_refs", ["EB-2"]), PatchReason.BROKEN_REFERENCE),
        (
            add(
                "personas",
                {
                    **PERSONA,
                    "description": research_assistant().personas[0].description,
                },
            ),
            PatchReason.DUPLICATE_PERSONA,
        ),
        (
            set_("tasks[TC-002].persona_ref", "cooperative-delegator"),
            PatchReason.DUPLICATE_TEST_CASE,
        ),
    ],
    ids=[
        "threshold out of range",
        "grader setting",
        "unsupported judgment form",
        "missing persona",
        "unmeasured behaviour",
        "same persona",
        "same pair",
    ],
)
def test_a_failed_result_check_removes_only_the_patches_that_caused_it(
    failing, reason
) -> None:
    valid = [
        set_(f"{EB1}.name", "Cites every claim"),
        set_(f"{AC31}.grader_args.threshold", 0.85),
    ]

    review = review_patches(
        research_assistant(), [*valid, failing], PatchScope(user_message=True)
    )

    assert review.accepted == valid
    assert [(p.path, p.reason) for p in review.problems] == [(failing.path, reason)]
    assert review.candidate.behaviour("EB-1").name == "Cites every claim"  # type: ignore[union-attr]
    assert review.candidate.criterion("AC-3-1").grader_args == {"threshold": 0.85}  # type: ignore[union-attr]
    assert review.candidate.tasks == research_assistant().tasks
    assert review.candidate.personas == research_assistant().personas


def test_replaying_the_accepted_patches_gives_the_candidate() -> None:
    specification = research_assistant()
    issued = collect_specification_ids(specification)
    patches = [
        add("personas", PERSONA),
        add(f"{EB3}.criteria", CRITERION),
        set_("features[F-1].behaviours[EB-3].name", "Stops"),  # a wrong ancestor
        set_(f"{AC11}.grader_fqn", "refused.Grader"),
        set_("tasks[TC-003].scenario_ref", "S-404"),
    ]

    review = review_patches(
        specification, patches, PatchScope(issued_ids=frozenset(issued))
    )
    apply(specification, review.accepted, issued_ids=issued)

    assert len(review.accepted) == 3
    assert specification == review.candidate
