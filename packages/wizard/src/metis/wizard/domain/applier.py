"""Applying patches to the specification.

The order of the checks is the whole design:

    1. origin      — did the package compose this? then it is trusted
    2. ownership   — does *any* step own this address?
    3. construction — strict drafts are materialized with code-owned fields.

Origin comes first because an address check alone cannot tell the user's tick from the
model's attempt at one — the two patches are byte-identical. See `PatchOrigin`.

The model-facing contract is validated before this module sees provider JSON. Bundled values
are strict drafts, and this module materializes ids, defaults and authorship before constructing
the persisted domain object.

A rejected patch is never silent. The user asked for something and part of it did not happen,
so the applier says which part and why, and the caller attaches that as a RUNTIME warning.
Attribution matters more here than anywhere else: it is the one message where the wizard has
to say *I chose not to*, rather than *you did something wrong* or *something broke*.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from metis.wizard.domain import materializer, paths
from metis.wizard.domain.nodes import duplicate_test_cases
from metis.wizard.domain.patch import Patch, PatchOp, PatchOrigin
from metis.wizard.domain.permissions import owner_of
from metis.wizard.domain.specification import (
    Behaviour,
    Criterion,
    Feature,
    Persona,
    Scenario,
    Specification,
    Task,
    collect_specification_ids,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

# What a list of each name holds, so an ADD patch can build the right object from a dict.
_LIST_TYPES: dict[str, type] = {
    "features": Feature,
    "behaviours": Behaviour,
    "criteria": Criterion,
    "personas": Persona,
    "scenarios": Scenario,
    "tasks": Task,
}


def _draft(value: Any, name: str) -> bool:
    """Recognise a strict draft without making the domain layer depend on contracts."""
    return type(value).__name__ == name


@dataclass
class Rejection:
    """One patch that did not happen, and the sentence the user is shown."""

    patch: Patch
    reason: str

    @property
    def message(self) -> str:
        return self.reason


class PatchValueError(Exception):
    """A model patch carries data that cannot build the node at its destination."""


@dataclass
class ApplyResult:
    applied: list[Patch] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)

    @property
    def any_rejected(self) -> bool:
        return bool(self.rejected)


def _check(patch: Patch) -> str | None:
    """Return a rejection reason, or None if the patch may be applied."""
    # 1. The package composed it, and knows it did, at the moment it drew the option.
    if patch.origin is PatchOrigin.WIZARD:
        return None

    # 2. Not "does my current step allow this?" but "does any step own it?".
    if owner_of(patch.path) is None:
        if patch.path.endswith(".measured"):
            return (
                "I've made that change. I can't tick it for you, though — "
                "which behaviours actually matter is your call, not mine."
            )
        if patch.path.endswith(".grader_fqn"):
            # Graders are chosen by the matcher from the criterion's wording, never written
            # directly. The model is told to reword instead; if one slips through anyway, the
            # user hears about the wording, not a field they have never seen.
            return (
                "The grader is chosen from how the criterion is worded, so I can't set it "
                "directly — but rewording the criterion will point it at the right one."
            )
        # A model patch for an address no step owns. The path is package bookkeeping the user
        # has never seen, so it is named as "part of this" rather than shown verbatim.
        return "I wasn't able to make part of that change — it isn't mine to write."

    # A model may edit a named semantic field, but cannot replace a persisted entity wholesale:
    # that would be a second creation route around the draft/materializer boundary.
    if (
        patch.origin is PatchOrigin.MODEL
        and patch.op is PatchOp.SET
        and patch.path.rsplit(".", 1)[-1].find("[") >= 0
    ):
        return "I can update a field on that item, but I can't replace the whole item."

    return None


def _coerce(field_name: str, value: Any, origin: PatchOrigin) -> Any:
    """Turn a wizard-composed dictionary into the object its list holds."""
    # Runtime callers from older integrations may still construct a generic model Patch. Keep
    # that compatibility safe; provider JSON is already rejected by strict drafts before here.
    if origin is PatchOrigin.MODEL and isinstance(value, dict):
        allowed = {
            "features": {"id", "name", "description", "behaviours"},
            "behaviours": {"id", "name", "description", "criteria"},
            "criteria": {"id", "name", "description"},
            "personas": {"id", "name", "description", "metadata"},
            "tasks": {"id", "scenario_ref", "persona_ref", "behaviour_refs"},
            "scenarios": {
                "id",
                "name",
                "description",
                "metadata",
                "tasks",
            },
        }.get(field_name)
        if allowed is not None:
            value = {
                key: [
                    _coerce(
                        "behaviours" if key == "behaviours" else "criteria",
                        item,
                        origin,
                    )
                    for item in inner
                ]
                if isinstance(inner := value[key], list)
                else inner
                for key in value
                if key in allowed
            }
    model = _LIST_TYPES.get(field_name)
    if model is not None and isinstance(value, dict):
        return model.model_validate(value)
    return value


def _apply_one(
    specification: Specification,
    patch: Patch,
    *,
    issued_ids: set[str],
    user_typed: set[str] | None,
    allowed_fixture_names: set[str] | None = None,
) -> None:
    # A model can pair a right, unique behaviour id with a wrong feature ancestor; correct the
    # ancestor against the behaviour it names before resolving. See `paths.normalise`.
    path = paths.normalise(specification, patch.path)
    parent, segment = paths.resolve_parent(specification, path)

    if patch.op is PatchOp.SET:
        if segment.key is None:
            setattr(
                parent, segment.field, _coerce(segment.field, patch.value, patch.origin)
            )
        else:
            # Replacing a whole element by id, e.g. SET features[F-1].behaviours[EB-4].
            items = getattr(parent, segment.field)
            replacement = _coerce(segment.field, patch.value, patch.origin)
            for i, item in enumerate(items):
                if getattr(item, "id", None) == segment.key:
                    items[i] = replacement
                    return
            raise paths.PathError(f"{patch.path!r}: nothing with id {segment.key!r}.")

    elif patch.op is PatchOp.ADD:
        items = getattr(parent, segment.field)
        if not isinstance(items, list):
            raise paths.PathError(f"{patch.path!r}: cannot ADD to a non-list.")
        value = patch.value
        if _draft(value, "FeatureDraft") and segment.field == "features":
            materializer.add_feature(
                specification,
                value,
                patch.origin,
                issued_ids=issued_ids,
                user_typed=user_typed,
            )
            return
        if _draft(value, "BehaviourDraft") and segment.field == "behaviours":
            items.append(
                materializer.add_behaviour(
                    specification,
                    value,
                    patch.origin,
                    issued_ids=issued_ids,
                    user_typed=user_typed,
                )
            )
            return
        if _draft(value, "CriterionDraft") and segment.field == "criteria":
            if not isinstance(parent, Behaviour):
                raise paths.PathError(
                    f"{patch.path!r}: criteria has no behaviour parent."
                )
            materializer.add_criterion(
                specification,
                parent,
                value,
                patch.origin,
                issued_ids=issued_ids,
                user_typed=user_typed,
            )
            return
        if _draft(value, "PersonaDraft") and segment.field == "personas":
            materializer.add_persona(
                specification,
                value,
                patch.origin,
                issued_ids=issued_ids,
                user_typed=user_typed,
            )
            return
        if _draft(value, "ScenarioDraft") and segment.field == "scenarios":
            materializer.add_scenario(
                specification,
                value,
                patch.origin,
                issued_ids=issued_ids,
                user_typed=user_typed,
                allowed_fixture_names=allowed_fixture_names,
            )
            return
        if _draft(value, "TaskDraft") and segment.field == "tasks":
            materializer.add_task(
                specification,
                value,
                patch.origin,
                issued_ids=issued_ids,
                user_typed=user_typed,
                allowed_fixture_names=allowed_fixture_names,
            )
            return
        items.append(_coerce(segment.field, value, patch.origin))

    elif patch.op is PatchOp.REMOVE:
        items = getattr(parent, segment.field)
        if segment.key is None:
            raise paths.PathError(f"{patch.path!r}: REMOVE needs an id.")
        remaining = [i for i in items if getattr(i, "id", None) != segment.key]
        if len(remaining) == len(items):
            raise paths.PathError(f"{patch.path!r}: nothing with id {segment.key!r}.")
        setattr(parent, segment.field, remaining)

    elif patch.op is PatchOp.REORDER:
        items = getattr(parent, segment.field)
        order = {id_: i for i, id_ in enumerate(patch.value or [])}
        setattr(
            parent,
            segment.field,
            sorted(items, key=lambda x: order.get(getattr(x, "id", None), len(order))),
        )


def apply(
    specification: Specification,
    patches: list[Patch],
    *,
    issued_ids: set[str] | None = None,
    user_typed: set[str] | None = None,
    allowed_fixture_names: set[str] | None = None,
) -> ApplyResult:
    """Apply what is allowed, report what was not.

    Patches are applied in order. Nothing here guards against a *set* of patches that
    conflict — that case is removed a level up instead: anything the user can click together
    is guaranteed not to conflict (see `multi`), and suggestion chips are one at a time.
    """
    result = ApplyResult()
    issued_ids = (
        issued_ids
        if issued_ids is not None
        else collect_specification_ids(specification)
    )

    for patch in patches:
        reason = _check(patch)
        if reason is not None:
            result.rejected.append(Rejection(patch, reason))
            continue
        try:
            _apply_one(
                specification,
                patch,
                issued_ids=issued_ids,
                user_typed=user_typed,
                allowed_fixture_names=allowed_fixture_names,
            )
        except paths.PathError as exc:
            result.rejected.append(Rejection(patch, f"I couldn't apply that: {exc}"))
            continue
        except ValidationError:
            # The value won't build the object its list holds — a bad enum, or a nested
            # field the wrong shape. `Patch.value` is `Any`, so this is the first point the
            # shape is checked; a malformed value must be a rejected patch, never a crash
            # partway through an interview.
            result.rejected.append(
                Rejection(patch, f"I couldn't apply that change to {patch.path}.")
            )
            continue
        except (ValueError, TypeError) as exc:
            result.rejected.append(
                Rejection(patch, f"I couldn't apply that change: {exc}")
            )
            continue
        result.applied.append(patch)

    return result


def sanitise(patches: Sequence[Any]) -> list[Patch]:
    """Force every patch to MODEL origin.

    Call this on anything that came out of a model. Origin is stamped by the code that builds
    a patch and is never carried in structured output, so a model claiming `wizard` is either
    confused or trying it on; either way the answer is the same.
    """
    return [
        p.model_copy(update={"origin": PatchOrigin.MODEL})
        if isinstance(p, Patch)
        else Patch(op=p.op, path=p.path, value=p.value, origin=PatchOrigin.MODEL)
        for p in patches
    ]


def validate_model_patches(
    specification: Specification,
    patches: Sequence[Any],
    *,
    allowed_fixture_names: set[str] | None = None,
) -> None:
    """Validate model patch values without touching the real specification.

    `Patch.value` is necessarily `Any`: its shape depends on the path. Structured output
    therefore validates only the patch envelope. Applying to a deep copy closes that gap and
    lets the gateway feed a domain validation error back through its normal retry loop.

    Policy and path rejections remain the applier's concern. They describe something the
    wizard refuses or cannot locate, not malformed structured output.
    """
    candidate = specification.model_copy(deep=True)
    issued_ids = collect_specification_ids(candidate)
    user_typed: set[str] = set()
    previous_persona_counts = _persona_description_counts(specification)

    for patch in sanitise(patches):
        if _check(patch) is not None:
            continue
        try:
            _apply_one(
                candidate,
                patch,
                issued_ids=issued_ids,
                user_typed=user_typed,
                allowed_fixture_names=allowed_fixture_names,
            )
            # Assignment itself is not validated on Pydantic models. Rebuilding after every
            # patch catches scalar SETs and list-shaped values as well as nested model errors.
            candidate = Specification.model_validate(
                candidate.model_dump(mode="python", warnings=False)
            )
        except paths.PathError:
            continue
        except (ValidationError, TypeError, AttributeError, ValueError) as exc:
            raise PatchValueError(
                f"The patch at {patch.path!r} has a value that does not fit there:\n{exc}"
            ) from exc

    # A model should update or remove an existing persona, not append the same prose under
    # another id. Check after the whole patch set so a legitimate add-then-remove replacement
    # is judged in its final state rather than halfway through.
    duplicate = next(
        (
            (description, ids)
            for description, ids in _persona_descriptions(candidate).items()
            if len(ids) > max(1, previous_persona_counts.get(description, 0))
        ),
        None,
    )
    if duplicate:
        _, ids = duplicate
        raise PatchValueError(
            "The proposed patches duplicate one persona description under "
            f"{', '.join(ids)}. Update or remove the existing persona instead of adding "
            "the same content again."
        )

    # A Test Case is unique by its Persona and Scenario pair. The check reads the whole
    # candidate, so a model cannot pair the same two items twice under two Test Cases.
    repeats = [
        repeat
        for repeat in duplicate_test_cases(candidate)
        if repeat not in duplicate_test_cases(specification)
    ]
    if repeats:
        later, earlier = repeats[0]
        raise PatchValueError(
            f"The proposed patches give {later} the same Persona and Scenario as {earlier}. "
            "Each Test Case needs its own Persona and Scenario pair. Change the pair, or "
            "update the existing Test Case."
        )


def _normalise_prose(value: str) -> str:
    return " ".join(value.split()).casefold()


def _persona_descriptions(specification: Specification) -> dict[str, list[str]]:
    descriptions: dict[str, list[str]] = {}
    for persona in specification.personas:
        descriptions.setdefault(_normalise_prose(persona.description), []).append(
            persona.id
        )
    return descriptions


def _persona_description_counts(specification: Specification) -> dict[str, int]:
    return {
        description: len(ids)
        for description, ids in _persona_descriptions(specification).items()
    }
