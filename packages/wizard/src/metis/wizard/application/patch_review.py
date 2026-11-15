"""One review for every model result, before anything is applied.

A model changes the Specification only through the patches in its result. `review_patches`
decides which of them the wizard accepts. The gateway calls it on each attempt to decide on a
retry, and the driver calls the same function for the real apply, so the two cannot disagree.

The review works on a copy and does these checks in order:

    1. normalise the path (`paths.normalise`)
    2. the scope: the part of the Specification that this call may write
    3. the permission tables (`permissions.refusal`)
    4. apply the patch to the copy, and check that the copy is still a valid Specification
    5. check the result for what the call touched: grader settings, Task references and
       duplicates

A patch that fails a result check leaves the accepted list, and the review applies the rest
again. The result is the accepted patches, the candidate Specification after them, and one
problem for each patch that was not accepted. Replaying the accepted patches with `apply` gives
the candidate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from metis.wizard.application.matching.matcher import grader_args_errors
from metis.wizard.domain import paths
from metis.wizard.domain.applier import (
    APPLY_ERRORS,
    apply_one,
    check,
    rejection_for,
    sanitise,
)
from metis.wizard.domain.nodes import duplicate_test_cases
from metis.wizard.domain.patch import Patch, PatchOp
from metis.wizard.domain.permissions import PatchReason
from metis.wizard.domain.specification import collect_specification_ids

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from typing import Any

    from metis.wizard.domain.specification import Specification

ALL_OPS = frozenset(PatchOp)

# The fields of an item that a call with locked items must not change.
_LOCKED_FIELDS = frozenset({"name", "description"})


@dataclass(frozen=True)
class ScopeArea:
    """One part of the Specification that a model call may write."""

    path: str
    ops: frozenset[PatchOp] = ALL_OPS
    # Whether the addresses under `path` are in the area too.
    below: bool = True
    # When set, only a patch whose last field has one of these names.
    fields: frozenset[str] | None = None

    def holds(self, path: str, op: PatchOp) -> bool:
        if op not in self.ops:
            return False
        inside = path == self.path or (
            self.below and path.startswith((f"{self.path}.", f"{self.path}["))
        )
        return inside and (
            self.fields is None or paths.parse(path)[-1].field in self.fields
        )


@dataclass(frozen=True)
class PatchScope:
    """What one model call may write.

    `areas` is None for a call that may write anywhere the permission tables allow. `user_message` is
    True only for a chat that answers the user's own message. `locked_items` are ids whose name
    and description the call must not change, such as the items that the user typed in a form.
    `fixture_names` are the files that a drafted Test Case may name.
    """

    areas: tuple[ScopeArea, ...] | None = None
    user_message: bool = False
    locked_items: frozenset[str] = frozenset()
    fixture_names: frozenset[str] = frozenset()

    @classmethod
    def exactly(
        cls, addresses: Iterable[str], ops: Iterable[PatchOp] = ALL_OPS, **values: Any
    ) -> PatchScope:
        """A scope of these addresses only, with these operations."""
        allowed = frozenset(ops)
        return cls(
            areas=tuple(
                ScopeArea(address, allowed, below=False)
                for address in sorted(addresses)
            ),
            **values,
        )

    @classmethod
    def under(cls, prefixes: Iterable[str], **values: Any) -> PatchScope:
        """A scope of these addresses and everything under them."""
        return cls(
            areas=tuple(ScopeArea(prefix) for prefix in sorted(prefixes)), **values
        )

    def allows(self, path: str, op: PatchOp) -> bool:
        if self.areas is not None and not any(
            area.holds(path, op) for area in self.areas
        ):
            return False
        segments = paths.parse(path)
        return not (
            len(segments) >= 2
            and segments[-1].field in _LOCKED_FIELDS
            and segments[-2].key in self.locked_items
        )


@dataclass(frozen=True)
class PatchProblem:
    """One patch that the review did not accept, and why.

    `detail` says more for the model. It can name internal paths, so the user never sees it,
    except for a reason whose detail is plain words.
    """

    op: PatchOp
    path: str
    reason: PatchReason
    detail: str = ""


@dataclass
class PatchReview:
    accepted: list[Patch]
    candidate: Specification
    problems: list[PatchProblem]


@dataclass
class _Applied:
    """One pass of the per-patch checks over the patches that are still in play."""

    candidate: Specification
    # The accepted patches by their index in the model result, with the top-level items that
    # each one created or changed.
    accepted: dict[int, tuple[Patch, frozenset[str]]] = field(default_factory=dict)
    problems: dict[int, PatchProblem] = field(default_factory=dict)


def review_patches(
    specification: Specification,
    patches: Sequence[Any],
    scope: PatchScope,
    *,
    issued_ids: set[str] | None = None,
    user_typed: set[str] | None = None,
) -> PatchReview:
    """Decide which model patches the wizard accepts. The Specification is not changed."""
    proposed = sanitise(patches)
    removed: dict[int, PatchProblem] = {}
    while True:
        applied = _apply_each(
            specification,
            proposed,
            scope,
            skip=set(removed),
            issued_ids=issued_ids,
            user_typed=user_typed,
        )
        found = _result_problems(specification, applied)
        if not found:
            break
        # Each pass removes at least one patch, so the loop ends.
        removed.update(found)

    problems = {**applied.problems, **removed}
    return PatchReview(
        accepted=[patch for patch, _ in applied.accepted.values()],
        candidate=applied.candidate,
        problems=[problems[index] for index in sorted(problems)],
    )


def _problem(patch: Patch, reason: PatchReason, detail: str = "") -> PatchProblem:
    return PatchProblem(op=patch.op, path=patch.path, reason=reason, detail=detail)


def _apply_each(
    specification: Specification,
    proposed: list[Patch],
    scope: PatchScope,
    *,
    skip: set[int],
    issued_ids: set[str] | None,
    user_typed: set[str] | None,
) -> _Applied:
    applied = _Applied(candidate=specification.model_copy(deep=True))
    ids = set(
        issued_ids
        if issued_ids is not None
        else collect_specification_ids(specification)
    )
    typed = set(user_typed or ())

    for index, patch in enumerate(proposed):
        if index in skip:
            continue
        try:
            path = paths.normalise(applied.candidate, patch.path)
        except paths.PathError as exc:
            applied.problems[index] = _problem(
                patch, PatchReason.UNKNOWN_ADDRESS, str(exc)
            )
            continue
        patch = patch.model_copy(update={"path": path})
        if not scope.allows(path, patch.op):
            applied.problems[index] = _problem(patch, PatchReason.OUTSIDE_SCOPE)
            continue
        reason = check(patch, user_message=scope.user_message)
        if reason is not None:
            applied.problems[index] = _problem(patch, reason)
            continue

        trial = applied.candidate.model_copy(deep=True)
        trial_ids, trial_typed = set(ids), set(typed)
        try:
            apply_one(
                trial,
                patch,
                issued_ids=trial_ids,
                user_typed=trial_typed,
                allowed_fixture_names=set(scope.fixture_names),
            )
            # Assignment is not validated on Pydantic models. Rebuilding after each patch
            # catches a scalar SET of the wrong type as well as nested model errors.
            trial = type(trial).model_validate(
                trial.model_dump(mode="python", warnings=False)
            )
        except APPLY_ERRORS as exc:
            rejection = rejection_for(patch, exc)
            applied.problems[index] = _problem(
                patch, rejection.reason, rejection.detail
            )
            continue
        applied.accepted[index] = (patch, _touched(applied.candidate, trial, path))
        applied.candidate, ids, typed = trial, trial_ids, trial_typed
    return applied


def _touched(before: Specification, after: Specification, path: str) -> frozenset[str]:
    """The ids of the Personas, Test Cases and grader settings that one patch changed.

    A grader setting counts as its Criterion's id.
    """
    segments = paths.parse(path)
    if len(segments) >= 2 and segments[-2].field == "grader_args":
        return frozenset({segments[-3].key or ""})
    first = segments[0]
    if first.field not in ("personas", "tasks"):
        return frozenset()
    if first.key is not None:
        return frozenset({first.key})
    old = {item.id for item in getattr(before, first.field)}
    return frozenset(item.id for item in getattr(after, first.field)) - old


def _result_problems(
    specification: Specification, applied: _Applied
) -> dict[int, PatchProblem]:
    """Check the candidate for what the call touched. Name the patches that caused each problem."""
    candidate = applied.candidate
    found: dict[int, PatchProblem] = {}

    def blame(ids: Iterable[str], reason: PatchReason, detail: str) -> None:
        ids = set(ids)
        for index, (patch, touched) in applied.accepted.items():
            if touched & ids and index not in found:
                found[index] = _problem(patch, reason, detail)

    touched = frozenset().union(*(items for _, items in applied.accepted.values()))

    # A grader setting that the call set is one that its grader accepts, as the engine checks
    # before a run. Only a new error counts, and it removes the patch of the setting that the
    # error names. When the error names none, it removes each setting patch that fails alone,
    # or every setting patch of that Criterion when only the combination fails.
    for criterion in (c for b in candidate.behaviours() for c in b.criteria):
        if criterion.id not in touched:
            continue
        old = specification.criterion(criterion.id)
        known = (
            set(
                grader_args_errors(
                    old.grader_fqn, old.grader_args, description=old.description
                )
            )
            if old is not None
            else set()
        )
        errors = [
            error
            for error in grader_args_errors(
                criterion.grader_fqn,
                criterion.grader_args,
                description=criterion.description,
            )
            if error not in known
        ]
        if not errors:
            continue
        settings = {
            index: paths.parse(patch.path)[-1].field
            for index, (patch, items) in applied.accepted.items()
            if criterion.id in items
        }
        named = {name.split(".", 1)[0] for name, _ in errors}
        culprits = named & set(settings.values())
        if not culprits and old is not None:
            # The error names no setting. A setting is a cause when it fails alone.
            culprits = {
                setting
                for setting in set(settings.values())
                if set(
                    grader_args_errors(
                        old.grader_fqn,
                        {
                            **old.grader_args,
                            setting: criterion.grader_args.get(setting),
                        },
                        description=old.description,
                    )
                )
                - known
            }
        for index, setting in settings.items():
            if setting in culprits or not culprits:
                messages = [m for n, m in errors if n.split(".", 1)[0] == setting] or [
                    m for _, m in errors
                ]
                found[index] = _problem(
                    applied.accepted[index][0],
                    PatchReason.INVALID_SETTING,
                    f"{criterion.name}, {setting}: {' '.join(messages)}",
                )
    measured = {behaviour.id for behaviour in candidate.measured_behaviours()}
    behaviours = {behaviour.id for behaviour in candidate.behaviours()}

    # A Test Case that the call created or changed names only items that exist, and only
    # measured Behaviours. A Test Case that a removal broke is not this check's concern: the
    # driver removes it with the item it used.
    for task in candidate.tasks:
        if task.id not in touched:
            continue
        broken = [
            ref
            for ref, exists in (
                (task.persona_ref, candidate.persona(task.persona_ref) is not None),
                (task.scenario_ref, candidate.scenario(task.scenario_ref) is not None),
                *(
                    (ref, ref in behaviours and ref in measured)
                    for ref in task.behaviour_refs
                ),
            )
            if not exists
        ]
        if broken:
            blame(
                {task.id},
                PatchReason.BROKEN_REFERENCE,
                f"{task.id} names {', '.join(broken)}.",
            )

    # A model should update or remove an existing Persona, not add the same prose under
    # another id. The check reads the whole candidate, so an add-then-remove replacement is
    # judged in its final state.
    previous = _persona_descriptions(specification)
    for description, ids in _persona_descriptions(candidate).items():
        if len(ids) > max(1, len(previous.get(description, []))):
            blame(
                ids,
                PatchReason.DUPLICATE_PERSONA,
                f"{', '.join(ids)} have the same description.",
            )

    # A Test Case is unique by its Persona and Scenario pair. The later Test Case of a pair is
    # the repeat, unless the call changed only the earlier one.
    earlier_repeats = duplicate_test_cases(specification)
    for later, earlier in duplicate_test_cases(candidate):
        if (later, earlier) not in earlier_repeats:
            blame(
                {later} if later in touched else {earlier},
                PatchReason.DUPLICATE_TEST_CASE,
                f"{later} has the same Persona and Scenario as {earlier}.",
            )
    return found


def _persona_descriptions(specification: Specification) -> dict[str, list[str]]:
    descriptions: dict[str, list[str]] = {}
    for persona in specification.personas:
        key = " ".join(persona.description.split()).casefold()
        descriptions.setdefault(key, []).append(persona.id)
    return descriptions


__all__ = [
    "ALL_OPS",
    "PatchProblem",
    "PatchReview",
    "PatchScope",
    "ScopeArea",
    "review_patches",
]
