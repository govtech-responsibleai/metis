"""Application-owned construction of persisted specification entities."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from metis.wizard.domain.documents import (
    fixture_name_identity,
    normalize_fixture_name,
)
from metis.wizard.domain.patch import PatchOrigin
from metis.wizard.domain.specification import (
    Behaviour,
    Criterion,
    Feature,
    Persona,
    Scenario,
    Specification,
    Task,
)


def _next_numeric(ids: set[str], prefix: str) -> str:
    numbers = [
        int(match.group(1))
        for value in ids
        if (match := re.fullmatch(re.escape(prefix) + r"-(\d+)", value))
    ]
    return f"{prefix}-{max(numbers, default=0) + 1}"


def _slug(name: str) -> str:
    value = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value or "persona"


def _persona_id(issued_ids: set[str], name: str, *, manual: bool) -> str:
    if manual:
        return _next_numeric(issued_ids, "P")
    base = _slug(name)
    candidate = base
    suffix = 2
    while candidate in issued_ids:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _record(
    issued_ids: set[str], user_typed: set[str] | None, node_id: str, origin: PatchOrigin
) -> None:
    """Record identity before the caller inserts the node into the specification."""
    issued_ids.add(node_id)
    if origin is PatchOrigin.WIZARD and user_typed is not None:
        user_typed.add(node_id)


def add_feature(
    specification: Specification,
    draft: Any,
    origin: PatchOrigin,
    *,
    issued_ids: set[str],
    user_typed: set[str] | None = None,
) -> Feature:
    feature = Feature(
        id=_next_numeric(issued_ids, "F"),
        name=draft.name,
        description=draft.description,
        behaviours=[],
    )
    _record(issued_ids, user_typed, feature.id, origin)
    for behaviour_draft in draft.behaviours:
        feature.behaviours.append(
            add_behaviour(
                specification,
                behaviour_draft,
                origin,
                issued_ids=issued_ids,
                user_typed=user_typed,
            )
        )
    specification.features.append(feature)
    return feature


def add_behaviour(
    specification: Specification,
    draft: Any,
    origin: PatchOrigin,
    *,
    issued_ids: set[str],
    user_typed: set[str] | None = None,
) -> Behaviour:
    behaviour = Behaviour(
        id=_next_numeric(issued_ids | {b.id for b in specification.behaviours()}, "EB"),
        name=draft.name,
        description=draft.description,
        measured=True,
    )
    _record(issued_ids, user_typed, behaviour.id, origin)
    return behaviour


def add_criterion(
    specification: Specification,
    behaviour: Behaviour,
    draft: Any,
    origin: PatchOrigin,
    *,
    issued_ids: set[str],
    user_typed: set[str] | None = None,
) -> Criterion:
    # Criterion ids keep the parent number, so this assumes a Behaviour id ends in a number.
    number = re.search(r"(\d+)$", behaviour.id)
    stem = number.group(1) if number else behaviour.id
    prefix = f"AC-{stem}"
    criterion = Criterion(
        id=_next_numeric(issued_ids, prefix),
        name=draft.name,
        description=draft.description,
    )
    _record(issued_ids, user_typed, criterion.id, origin)
    behaviour.criteria.append(criterion)
    return criterion


def add_persona(
    specification: Specification,
    draft: Any,
    origin: PatchOrigin,
    *,
    issued_ids: set[str],
    user_typed: set[str] | None = None,
) -> Persona:
    persona = Persona(
        id=_persona_id(issued_ids, draft.name, manual=origin is PatchOrigin.WIZARD),
        name=draft.name,
        description=draft.description,
        metadata=draft.metadata,
    )
    _record(issued_ids, user_typed, persona.id, origin)
    specification.personas.append(persona)
    return persona


def add_scenario(
    specification: Specification,
    draft: Any,
    origin: PatchOrigin,
    *,
    issued_ids: set[str],
    user_typed: set[str] | None = None,
    allowed_fixture_names: set[str] | None = None,
) -> Scenario:
    scenario = Scenario(
        id=_next_numeric(issued_ids, "S"),
        name=draft.name,
        description=draft.description,
        metadata=draft.metadata,
    )
    _record(issued_ids, user_typed, scenario.id, origin)
    specification.scenarios.append(scenario)
    return scenario


def _task(
    specification: Specification,
    draft: Any,
    scenario_id: str,
    issued_ids: set[str],
    allowed_fixture_names: set[str] | None,
    *,
    offset: int = 0,
) -> Task:
    if specification.persona(draft.persona_ref) is None or any(
        specification.behaviour(ref) is None for ref in draft.behaviour_refs
    ):
        raise ValueError("Task references unknown Persona or Behaviour IDs.")
    available = {
        fixture_name_identity(name): normalize_fixture_name(name)
        for name in (allowed_fixture_names or set())
    }
    fixtures = []
    for raw in draft.fixtures:
        name = normalize_fixture_name(raw)
        if name != raw or fixture_name_identity(name) not in available:
            raise ValueError(f"Task fixture {raw!r} is not available.")
        fixtures.append(available[fixture_name_identity(name)])
    if len(set(fixtures)) != len(fixtures):
        raise ValueError("Task fixtures must be unique.")
    number = int(_next_numeric(issued_ids, "TC").split("-")[-1]) + offset
    return Task(
        id=f"TC-{number:03}",
        scenario_ref=scenario_id,
        persona_ref=draft.persona_ref,
        behaviour_refs=list(draft.behaviour_refs),
        fixtures=fixtures,
    )


def add_task(
    specification: Specification,
    draft: Any,
    origin: PatchOrigin,
    *,
    issued_ids: set[str],
    user_typed: set[str] | None = None,
    allowed_fixture_names: set[str] | None = None,
) -> Task:
    if specification.scenario(draft.scenario_ref) is None:
        raise ValueError("Task references an unknown Scenario.")
    task = _task(
        specification,
        draft,
        draft.scenario_ref,
        issued_ids | {t.id for t in specification.tasks},
        allowed_fixture_names,
    )
    _record(issued_ids, user_typed, task.id, origin)
    specification.tasks.append(task)
    return task


def assign_task_ids(specification: Specification) -> None:
    """Assign IDs to new manual Tasks; retain every ID supplied by the client."""
    issued = {task.id for task in specification.tasks if task.id}
    for task in specification.tasks:
        if not task.id:
            number = int(_next_numeric(issued, "TC").split("-")[-1])
            task.id = f"TC-{number:03}"
            issued.add(task.id)
