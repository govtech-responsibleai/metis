"""Applying patches to the specification.

The order of the checks is the whole design:

    1. origin: did the package compose this? then it is trusted
    2. the permission tables: `permissions.refusal` says whether a model patch may make this change
    3. construction: strict drafts are materialized with code-owned fields.

Origin comes first because an address check alone cannot tell the user's tick from the
model's attempt at one: the two patches are byte-identical. See `PatchOrigin`.

The model-facing contract is validated before this module sees provider JSON. Bundled values
are strict drafts, and this module materializes ids, defaults and authorship before constructing
the persisted domain object.

A rejected patch carries a reason key from `PatchReason`. The application turns reason keys into
sentences from the prompt catalogue, so this layer never writes text for the user.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from metis.wizard.domain import materializer, paths
from metis.wizard.domain.patch import Patch, PatchOp, PatchOrigin
from metis.wizard.domain.permissions import PatchReason, refusal
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
    """One patch that did not happen, and why."""

    patch: Patch
    reason: PatchReason
    # What went wrong in more detail, for the model. It can name internal paths.
    detail: str = ""


class PatchValueError(Exception):
    """A model result carries data that the wizard cannot use."""


@dataclass
class ApplyResult:
    applied: list[Patch] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)

    @property
    def any_rejected(self) -> bool:
        return bool(self.rejected)


def check(patch: Patch, *, user_message: bool = False) -> PatchReason | None:
    """Return the reason the permission tables refuse the patch, or None if it may be applied."""
    # The package composed it, and knows it did, at the moment it drew the option.
    if patch.origin is PatchOrigin.WIZARD:
        return None
    return refusal(patch.path, patch.op, patch.value, user_message=user_message)


def rejection_for(patch: Patch, exc: Exception) -> Rejection:
    """Name the reason an exception from `apply_one` stands for."""
    if isinstance(exc, paths.OperationError):
        return Rejection(patch, PatchReason.WRONG_OPERATION, str(exc))
    if isinstance(exc, paths.PathError):
        return Rejection(patch, PatchReason.UNKNOWN_ADDRESS, str(exc))
    # The value will not build the object its list holds: a bad enum, or a nested field the
    # wrong shape. `Patch.value` is `Any`, so this is the first point the shape is checked.
    return Rejection(patch, PatchReason.BAD_VALUE, str(exc))


# What `apply_one` raises for a patch that cannot be applied.
APPLY_ERRORS = (paths.PathError, ValidationError, ValueError, TypeError, AttributeError)


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


def apply_one(
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
        if isinstance(parent, dict):
            # A key inside a mapping, such as one grader setting under `grader_args`.
            if segment.key is not None:
                raise paths.PathError(f"{patch.path!r}: a setting has no ids.")
            parent[segment.field] = patch.value
        elif segment.key is None:
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
            raise paths.OperationError(f"{patch.path!r}: cannot ADD to a non-list.")
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
            raise paths.OperationError(f"{patch.path!r}: REMOVE needs an id.")
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
    user_message: bool = False,
) -> ApplyResult:
    """Apply what is allowed, report what was not.

    Patches are applied in order. Nothing here guards against a *set* of patches that
    conflict: the patch review judges a model result as a whole before it reaches this point,
    and anything the user can click together is guaranteed not to conflict (see `multi`).
    `user_message` is True only for a chat that answers the user's own message.
    """
    result = ApplyResult()
    issued_ids = (
        issued_ids
        if issued_ids is not None
        else collect_specification_ids(specification)
    )

    for patch in patches:
        reason = check(patch, user_message=user_message)
        if reason is not None:
            result.rejected.append(Rejection(patch, reason))
            continue
        try:
            apply_one(
                specification,
                patch,
                issued_ids=issued_ids,
                user_typed=user_typed,
                allowed_fixture_names=allowed_fixture_names,
            )
        except APPLY_ERRORS as exc:
            result.rejected.append(rejection_for(patch, exc))
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
