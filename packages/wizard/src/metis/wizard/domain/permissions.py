"""What the model may write, and where.

Four plain tables hold the rules. `refusal` reads the first three in this order:

1. `PROTECTED`: the fields that no model call may write, each with its reason.
2. `ON_REQUEST`: the fields that a chat may set only when the user's own message asks, each
   with the reason that a refusal gets and a check of the value.
3. `StepPermissions`: each Interview step and the addresses that it owns.

An address in none of them is not writable. `KEPT_ON_REWORD` names the grader settings that keep
their values when a reword leaves the grader the same.

`StepPermissions` does not name operations, because the form of an address decides them. A list
takes ADD and REORDER (`features`, `features[F-1].behaviours`). An item takes REMOVE
(`features[F-1]`), and a SET on it is refused with `whole_item`: it would replace a persisted
item as a whole, a second creation route around the draft and materializer boundary. A field
takes SET.

The check is against the step that owns the address, not the step the user stands in: asking to
reword EB-4 while at the Criteria step simply works, because the Behaviours step owns Behaviour
descriptions. An address that no step owns is writable at no step.

Each reason is a key under `patch_reasons` in `prompts.yaml`. A new protected field needs one
line in `PROTECTED` and the sentence for its reason.

Bundled model values are protected at the structured-output boundary: strict draft models reject
persisted ids, defaults, authorship and matcher-owned fields before a domain object exists.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import TYPE_CHECKING

from metis.wizard.domain.patch import PatchOp

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable


class InterviewStep(StrEnum):
    CLARIFY = "clarify"
    BEHAVIOURS = "behaviours"
    CRITERIA = "criteria"
    PERSONAS = "personas"
    SCENARIOS = "scenarios"
    TEST_CASES = "test_cases"
    DONE = "done"


# The Trial count of a Test Case, as every door offers it.
TRIALS_MIN = 1
TRIALS_MAX = 20


class PatchReason(StrEnum):
    """Why the wizard did not apply a model patch.

    Each value is a key under `patch_reasons` in `prompts.yaml`, where its sentence lives. The
    tables below give the first group. The patch review gives the others.
    """

    MEASURED = "measured"
    NUM_TRIALS = "num_trials"
    FIXTURES = "fixtures"
    GRADER = "grader"
    JUDGE_SETTING = "judge_setting"
    CRITERION_TEXT = "criterion_text"
    WHOLE_ITEM = "whole_item"
    WRONG_OPERATION = "wrong_operation"
    NOT_WRITABLE = "not_writable"
    OUTSIDE_SCOPE = "outside_scope"
    UNKNOWN_ADDRESS = "unknown_address"
    BAD_VALUE = "bad_value"
    INVALID_SETTING = "invalid_setting"
    BROKEN_REFERENCE = "broken_reference"
    DUPLICATE_PERSONA = "duplicate_persona"
    DUPLICATE_TEST_CASE = "duplicate_test_case"


def _glob_to_regex(glob: str) -> re.Pattern[str]:
    """`features[*].behaviours[*]` matches `features[F-1].behaviours[EB-4]`.

    `[*]` stands for one id inside brackets, and a `*` name stands for one field name. Neither
    spans a `.`, so a glob for a behaviour cannot match something nested deeper under it.
    """
    parts = []
    for token in re.split(r"(\[\*\]|(?<=\.)\*)", glob):
        if token == "[*]":
            parts.append(r"\[[^\]]+\]")
        elif token == "*":
            parts.append(r"[A-Za-z_][A-Za-z0-9_]*")
        else:
            parts.append(re.escape(token))
    return re.compile("^" + "".join(parts) + "$")


def _any_value(_value: object) -> bool:
    return True


def _is_flag(value: object) -> bool:
    return isinstance(value, bool)


def _is_trial_count(value: object) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and TRIALS_MIN <= value <= TRIALS_MAX
    )


_BEHAVIOUR = "features[*].behaviours[*]"
_CRITERION = f"{_BEHAVIOUR}.criteria[*]"

# Each step owns both the list and its items. The measurement tick, the Trial count and the
# grader settings are not here: see `ON_REQUEST`. A user's tick is a wizard patch, which never
# reaches these tables.
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

# What a chat may set only when the user's own message asks. Each entry has the reason that a
# refusal gets and the check of the value. The patch review also checks a grader setting with
# its grader.
ON_REQUEST: dict[str, tuple[PatchReason, Callable[[object], bool]]] = {
    f"{_BEHAVIOUR}.measured": (PatchReason.MEASURED, _is_flag),
    "tasks[*].num_trials": (PatchReason.NUM_TRIALS, _is_trial_count),
    f"{_CRITERION}.grader_args.*": (PatchReason.OUTSIDE_SCOPE, _any_value),
}

# What no model call may set, and the reason. The matcher chooses the grader from the wording
# of the Criterion. The judge comes from the run configuration, and the judge instructions come
# from the Criterion description. The files of a Test Case change only in its form.
PROTECTED: dict[str, PatchReason] = {
    f"{_CRITERION}.grader_fqn": PatchReason.GRADER,
    f"{_CRITERION}.grader_args.model": PatchReason.JUDGE_SETTING,
    f"{_CRITERION}.grader_args.provider": PatchReason.JUDGE_SETTING,
    f"{_CRITERION}.grader_args.max_input_tokens": PatchReason.JUDGE_SETTING,
    f"{_CRITERION}.grader_args.criterion": PatchReason.CRITERION_TEXT,
    "tasks[*].fixtures": PatchReason.FIXTURES,
}

# The grader settings that keep their values when a reword leaves the grader the same.
KEPT_ON_REWORD = frozenset({"threshold", "scope"})

_OWNED = {glob for globs in StepPermissions.values() for glob in globs}


def _allowed_ops(glob: str) -> frozenset[PatchOp]:
    """The operations that fit the form of an owned address."""
    if glob.endswith("[*]"):
        return frozenset({PatchOp.REMOVE})
    if f"{glob}[*]" in _OWNED:
        return frozenset({PatchOp.ADD, PatchOp.REORDER})
    return frozenset({PatchOp.SET})


def _compile(globs: Iterable[str]) -> list[tuple[re.Pattern[str], str]]:
    return [(_glob_to_regex(glob), glob) for glob in globs]


def _match(table: list[tuple[re.Pattern[str], str]], path: str) -> str | None:
    return next((glob for pattern, glob in table if pattern.match(path)), None)


_PROTECTED = _compile(PROTECTED)
_ON_REQUEST = _compile(ON_REQUEST)
_STEPS = {step: _compile(globs) for step, globs in StepPermissions.items()}


def refusal(
    path: str, op: PatchOp, value: object = None, *, user_message: bool = False
) -> PatchReason | None:
    """Why a model patch may not make this change, or None when it may.

    `user_message` is True only for a chat that answers the user's own message.
    """
    if (glob := _match(_PROTECTED, path)) is not None:
        return PROTECTED[glob]
    if (glob := _match(_ON_REQUEST, path)) is not None:
        reason, accepts = ON_REQUEST[glob]
        if op is not PatchOp.SET:
            return PatchReason.WRONG_OPERATION
        return None if user_message and accepts(value) else reason
    for table in _STEPS.values():
        if (glob := _match(table, path)) is not None:
            if op in _allowed_ops(glob):
                return None
            if glob.endswith("[*]"):
                return PatchReason.WHOLE_ITEM
            return PatchReason.WRONG_OPERATION
    return PatchReason.NOT_WRITABLE


def owner_of(path: str) -> InterviewStep | None:
    """Which step owns this address, if any.

    Deliberately not "may my current step write this?". A path owned by no step is writable
    at no point, ever, which is what bounds the whole arrangement.
    """
    return next(
        (step for step, table in _STEPS.items() if _match(table, path) is not None),
        None,
    )
