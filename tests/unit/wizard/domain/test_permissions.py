"""The permission tables: what a model patch may write, and why a protected address is refused."""

import pytest

from metis.wizard.application import prompts
from metis.wizard.domain.patch import PatchOp
from metis.wizard.domain.permissions import (
    ON_REQUEST,
    PROTECTED,
    InterviewStep,
    PatchReason,
    StepPermissions,
    owner_of,
    refusal,
)

BEHAVIOUR = "features[F-1].behaviours[EB-1]"
CRITERION = f"{BEHAVIOUR}.criteria[AC-1-1]"

ADD, REMOVE, SET, REORDER = PatchOp.ADD, PatchOp.REMOVE, PatchOp.SET, PatchOp.REORDER
LIST = {ADD, REORDER}
ITEM = {REMOVE}
FIELD = {SET}

# Each owned address, an example path, and the operations that a model call may use there.
OWNED = {
    "target.name": ("target.name", FIELD),
    "target.users": ("target.users", FIELD),
    "target.description": ("target.description", FIELD),
    "target.detail": ("target.detail", FIELD),
    "features": ("features", LIST),
    "features[*]": ("features[F-1]", ITEM),
    "features[*].name": ("features[F-1].name", FIELD),
    "features[*].description": ("features[F-1].description", FIELD),
    "features[*].behaviours": ("features[F-1].behaviours", LIST),
    "features[*].behaviours[*]": (BEHAVIOUR, ITEM),
    "features[*].behaviours[*].name": (f"{BEHAVIOUR}.name", FIELD),
    "features[*].behaviours[*].description": (f"{BEHAVIOUR}.description", FIELD),
    "features[*].behaviours[*].criteria": (f"{BEHAVIOUR}.criteria", LIST),
    "features[*].behaviours[*].criteria[*]": (CRITERION, ITEM),
    "features[*].behaviours[*].criteria[*].name": (f"{CRITERION}.name", FIELD),
    "features[*].behaviours[*].criteria[*].description": (
        f"{CRITERION}.description",
        FIELD,
    ),
    "personas": ("personas", LIST),
    "personas[*]": ("personas[cooperative-delegator]", ITEM),
    "personas[*].name": ("personas[cooperative-delegator].name", FIELD),
    "personas[*].description": ("personas[cooperative-delegator].description", FIELD),
    "personas[*].metadata": ("personas[cooperative-delegator].metadata", FIELD),
    "scenarios": ("scenarios", LIST),
    "scenarios[*]": ("scenarios[S-1]", ITEM),
    "scenarios[*].name": ("scenarios[S-1].name", FIELD),
    "scenarios[*].description": ("scenarios[S-1].description", FIELD),
    "scenarios[*].metadata": ("scenarios[S-1].metadata", FIELD),
    "tasks": ("tasks", LIST),
    "tasks[*]": ("tasks[TC-001]", ITEM),
    "tasks[*].scenario_ref": ("tasks[TC-001].scenario_ref", FIELD),
    "tasks[*].persona_ref": ("tasks[TC-001].persona_ref", FIELD),
    "tasks[*].behaviour_refs": ("tasks[TC-001].behaviour_refs", FIELD),
}


def test_every_owned_address_has_an_example() -> None:
    assert {glob for globs in StepPermissions.values() for glob in globs} == set(OWNED)


@pytest.mark.parametrize(
    ("step", "glob"),
    [(step, glob) for step, globs in StepPermissions.items() for glob in globs],
    ids=lambda value: value if "." in str(value) or "[" in str(value) else None,
)
def test_the_form_of_an_owned_address_decides_its_operations(step, glob) -> None:
    path, allowed = OWNED[glob]

    for op in PatchOp:
        for user_message in (False, True):
            reason = refusal(path, op, "x", user_message=user_message)
            assert (reason is None) == (op in allowed), (path, op)

    assert owner_of(path) is step


@pytest.mark.parametrize(
    ("path", "op", "value", "user_message", "reason"),
    [
        # A user decision is set only when the user's own message asks, with a valid value.
        (f"{BEHAVIOUR}.measured", SET, True, True, None),
        (f"{BEHAVIOUR}.measured", SET, True, False, PatchReason.MEASURED),
        (f"{BEHAVIOUR}.measured", SET, "yes", True, PatchReason.MEASURED),
        ("tasks[TC-001].num_trials", SET, 5, True, None),
        ("tasks[TC-001].num_trials", SET, 5, False, PatchReason.NUM_TRIALS),
        ("tasks[TC-001].num_trials", SET, 50, True, PatchReason.NUM_TRIALS),
        ("tasks[TC-001].num_trials", SET, True, True, PatchReason.NUM_TRIALS),
        # A protected field is refused for every call.
        ("tasks[TC-001].fixtures", SET, ["a.md"], True, PatchReason.FIXTURES),
        (f"{CRITERION}.grader_fqn", SET, "x.Grader", True, PatchReason.GRADER),
        # The form of an owned address.
        ("scenarios[S-1]", SET, {}, True, PatchReason.WHOLE_ITEM),
        ("features", REMOVE, None, True, PatchReason.WRONG_OPERATION),
        # An address in no table.
        ("target.invented_field", SET, "x", True, PatchReason.NOT_WRITABLE),
        ("scenarios[S-1].fixtures", SET, [], True, PatchReason.NOT_WRITABLE),
    ],
)
def test_each_change_is_allowed_or_refused_with_its_reason(
    path, op, value, user_message, reason
) -> None:
    assert refusal(path, op, value, user_message=user_message) is reason


def test_every_reason_has_a_sentence_in_the_prompt_catalogue() -> None:
    """A table or the patch review can give any reason. Each one needs its sentence."""
    for reason in PatchReason:
        assert prompts.patch_reason(reason).strip()
    assert set(PROTECTED.values()) <= set(PatchReason)
    assert {reason for reason, _ in ON_REQUEST.values()} <= set(PatchReason)


def test_a_glob_does_not_span_a_dot() -> None:
    """`features[*].behaviours[*]` must not match a Criterion nested deeper under it."""
    assert owner_of(BEHAVIOUR) is InterviewStep.BEHAVIOURS
    assert owner_of(CRITERION) is InterviewStep.CRITERIA
