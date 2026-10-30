"""What the model may write, and where.

Two pieces of **config, not models**, because a patch can reach a field two different ways and
an address check only sees one of them.

`StepPermissions` maps a step to the path globs it owns. Two rules make it work, and both are
structural rather than prompt instructions:

**The check is against the step that owns the address, not the step you are standing in.**
Asking to reword EB-4 while sitting at the criteria step should simply work: the behaviours
step owns behaviour descriptions, so the patch is applied where you stand and your current step
never changes. Being told to press Back first would be the wizard enforcing its own structure
over a clearly stated intent. It stays bounded — an address no step owns is writable nowhere.

**Some addresses are unwritable by the model at any step.** `measured` is the user's only real
decision, and `num_trials` and `fixtures` are the user's to set, so none of them appears in any
entry. A chat that answers the user's own message may still set `measured` and `num_trials`:
the driver marks those patches as the user's, so no drafting call can reach them.

Bundled model values are protected at the structured-output boundary: strict draft models reject
persisted ids, defaults, authorship and matcher-owned fields before a domain object exists.
"""

from __future__ import annotations

import re
from enum import StrEnum


class InterviewStep(StrEnum):
    CLARIFY = "clarify"
    BEHAVIOURS = "behaviours"
    CRITERIA = "criteria"
    PERSONAS = "personas"
    SCENARIOS = "scenarios"
    TEST_CASES = "test_cases"
    DONE = "done"


# Note that BEHAVIOURS grants no path for `measured`: the measurement ticks are PatchOrigin.WIZARD,
# so they never reach an address check. Clarify owns the target prose. The driver narrows a clarify
# result to those four paths before applying it; the global owner lookup remains what lets a later
# step correct an earlier step's fields.
# Note that each step owns both the *container* and its *elements*. ADD addresses the list
# it appends to (`features`, `features[F-1].behaviours`), while SET and REMOVE address an element
# (`features[F-1]`). Listing only one of the two silently forbids half the operations.
StepPermissions: dict[InterviewStep, list[str]] = {
    InterviewStep.CLARIFY: [
        "target.name",
        "target.users",
        "target.description",
        "target.detail",
    ],
    InterviewStep.BEHAVIOURS: [
        "features",
        "features[*]",
        "features[*].name",
        "features[*].description",
        "features[*].behaviours",
        "features[*].behaviours[*]",
        "features[*].behaviours[*].name",
        "features[*].behaviours[*].description",
    ],
    InterviewStep.CRITERIA: [
        "features[*].behaviours[*].criteria",
        "features[*].behaviours[*].criteria[*]",
        "features[*].behaviours[*].criteria[*].name",
        "features[*].behaviours[*].criteria[*].description",
    ],
    InterviewStep.PERSONAS: [
        "personas",
        "personas[*]",
        "personas[*].name",
        "personas[*].description",
        "personas[*].metadata",
    ],
    InterviewStep.SCENARIOS: [
        "scenarios",
        "scenarios[*]",
        "scenarios[*].name",
        "scenarios[*].description",
        "scenarios[*].metadata",
    ],
    InterviewStep.TEST_CASES: [
        "tasks",
        "tasks[*]",
        "tasks[*].scenario_ref",
        "tasks[*].persona_ref",
        "tasks[*].behaviour_refs",
    ],
}


def _glob_to_regex(glob: str) -> re.Pattern[str]:
    """`features[*].behaviours[*]` matches `features[F-1].behaviours[EB-4]`.

    `*` stands for one id inside brackets and never spans a `.`, so a glob for a behaviour
    cannot accidentally match something nested deeper under it.
    """
    parts = []
    for token in re.split(r"(\[\*\])", glob):
        if token == "[*]":
            parts.append(r"\[[^\]]+\]")
        else:
            parts.append(re.escape(token))
    return re.compile("^" + "".join(parts) + "$")


_COMPILED: dict[InterviewStep, list[re.Pattern[str]]] = {
    step: [_glob_to_regex(g) for g in globs] for step, globs in StepPermissions.items()
}


def owner_of(path: str) -> InterviewStep | None:
    """Which step owns this address, if any.

    Deliberately not "may my current step write this?". A path owned by no step is writable
    at no point, ever — which is what bounds the whole arrangement.
    """
    for step, patterns in _COMPILED.items():
        if any(p.match(path) for p in patterns):
            return step
    return None
