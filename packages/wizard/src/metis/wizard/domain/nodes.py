"""Find a Specification node by id, and remove it with what depends on it.

Review actions name the node they act on by id only ("EB-1", "P-2"). These helpers find what
the id names, so a door never has to say which kind of node it clicked, and the same `edit` or
`remove` works at every step.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from metis.wizard.domain.specification import (
        Behaviour,
        Criterion,
        Feature,
        Persona,
        Scenario,
        Specification,
        Task,
    )

NodeKind = Literal["feature", "behaviour", "criterion", "persona", "scenario", "task"]

# The keys a screen-level add names, mapped to the kind of node it creates.
COLLECTIONS: dict[str, NodeKind] = {
    "features": "feature",
    "personas": "persona",
    "scenarios": "scenario",
    "tasks": "task",
}


@dataclass(frozen=True)
class Located:
    """What an id names: its kind, the node, and its patch path."""

    kind: NodeKind
    node: Feature | Behaviour | Criterion | Persona | Scenario | Task
    path: str


def locate(specification: Specification, node_id: str) -> Located | None:
    """Return the node with this id, or None. Ids are unique across the Specification."""
    for feature in specification.features:
        if feature.id == node_id:
            return Located("feature", feature, f"features[{feature.id}]")
        for behaviour in feature.behaviours:
            prefix = f"features[{feature.id}].behaviours[{behaviour.id}]"
            if behaviour.id == node_id:
                return Located("behaviour", behaviour, prefix)
            for criterion in behaviour.criteria:
                if criterion.id == node_id:
                    return Located(
                        "criterion", criterion, f"{prefix}.criteria[{criterion.id}]"
                    )
    for persona in specification.personas:
        if persona.id == node_id:
            return Located("persona", persona, f"personas[{persona.id}]")
    for scenario in specification.scenarios:
        if scenario.id == node_id:
            return Located("scenario", scenario, f"scenarios[{scenario.id}]")
    for task in specification.tasks:
        if task.id == node_id:
            return Located("task", task, f"tasks[{task.id}]")
    return None


@dataclass(frozen=True)
class Dependants:
    """What a removal takes with it, besides the node itself."""

    behaviours: int = 0
    criteria: int = 0
    tasks: int = 0  # Test Cases removed with the node
    covering_tasks: int = 0  # Test Cases that only lose a Behaviour reference

    def __bool__(self) -> bool:
        return bool(
            self.behaviours or self.criteria or self.tasks or self.covering_tasks
        )


def _behaviours_of(found: Located) -> list[Behaviour]:
    if found.kind == "feature":
        return list(found.node.behaviours)  # type: ignore[union-attr]
    if found.kind == "behaviour":
        return [found.node]  # type: ignore[list-item]
    return []


def dependants(specification: Specification, found: Located) -> Dependants:
    """Count what `remove` deletes with this node."""
    behaviours = _behaviours_of(found)
    if behaviours:
        ids = {behaviour.id for behaviour in behaviours}
        return Dependants(
            behaviours=len(behaviours) if found.kind == "feature" else 0,
            criteria=sum(len(behaviour.criteria) for behaviour in behaviours),
            covering_tasks=sum(
                1 for task in specification.tasks if ids & set(task.behaviour_refs)
            ),
        )
    if found.kind in ("persona", "scenario"):
        field = "persona_ref" if found.kind == "persona" else "scenario_ref"
        return Dependants(
            tasks=sum(
                1
                for task in specification.tasks
                if getattr(task, field) == found.node.id
            )
        )
    return Dependants()


def remove(specification: Specification, found: Located) -> None:
    """Remove the node and everything that cannot exist without it.

    A Feature takes its Behaviours, and a Behaviour takes its Criteria, because they are
    nested in it. A Test Case keeps running when a Behaviour goes, so only the reference is
    removed. A Test Case cannot run without its Persona or Scenario, so it goes with them.
    """
    node_id = found.node.id
    behaviour_ids = {behaviour.id for behaviour in _behaviours_of(found)}
    if found.kind == "feature":
        specification.features = [f for f in specification.features if f.id != node_id]
    elif found.kind == "behaviour":
        for feature in specification.features:
            feature.behaviours = [b for b in feature.behaviours if b.id != node_id]
    elif found.kind == "criterion":
        for behaviour in specification.behaviours():
            behaviour.criteria = [c for c in behaviour.criteria if c.id != node_id]
    elif found.kind == "persona":
        specification.personas = [p for p in specification.personas if p.id != node_id]
        specification.tasks = [
            t for t in specification.tasks if t.persona_ref != node_id
        ]
    elif found.kind == "scenario":
        specification.scenarios = [
            s for s in specification.scenarios if s.id != node_id
        ]
        specification.tasks = [
            t for t in specification.tasks if t.scenario_ref != node_id
        ]
    else:
        specification.tasks = [t for t in specification.tasks if t.id != node_id]

    for task in specification.tasks:
        if behaviour_ids & set(task.behaviour_refs):
            task.behaviour_refs = [
                ref for ref in task.behaviour_refs if ref not in behaviour_ids
            ]


def duplicate_test_cases(
    specification: Specification, tasks: list[Task] | None = None
) -> list[tuple[str, str]]:
    """Each Test Case that repeats an earlier one's Persona and Scenario, as (later, earlier).

    A Test Case is unique by its Persona and Scenario pair. Two with the same pair would run
    the same problem twice under two ids. `tasks` limits the check, for example to the
    selected Test Cases.
    """
    first: dict[tuple[str, str], str] = {}
    repeats: list[tuple[str, str]] = []
    for task in specification.tasks if tasks is None else tasks:
        pair = (task.persona_ref, task.scenario_ref)
        if pair in first:
            repeats.append((task.id, first[pair]))
        else:
            first[pair] = task.id
    return repeats


def emptied(before: Specification, after: Specification) -> list[str]:
    """What a removal emptied that a review needs, as finished text. Empty means allowed.

    A review drafts a new set when its collection is empty, so the last Feature, Behaviour,
    Persona or Scenario must stay. A measured Behaviour keeps at least one Criterion.
    """
    lost: list[str] = []
    for label, was, now in (
        ("Feature", before.features, after.features),
        ("Behaviour", before.behaviours(), after.behaviours()),
        ("Persona", before.personas, after.personas),
        ("Scenario", before.scenarios, after.scenarios),
    ):
        if was and not now:
            lost.append(f"the last {label}")
    for behaviour in after.measured_behaviours():
        previous = before.behaviour(behaviour.id)
        if previous is not None and previous.criteria and not behaviour.criteria:
            lost.append(f"the last Criterion of {behaviour.name}")
    return lost


def follow_removals(before: Specification, after: Specification) -> list[str]:
    """Remove what depends on nodes that a patch removed directly. Return removed Task ids.

    A model REMOVE on `personas[P-1]` deletes only that list item. The Test Cases that used it,
    and the Behaviour references to deleted Behaviours, are cleaned up here, the same as a
    user's Delete.
    """
    personas = {p.id for p in after.personas}
    scenarios = {s.id for s in after.scenarios}
    behaviours = {b.id for b in after.behaviours()}
    gone_behaviours = {b.id for b in before.behaviours()} - behaviours
    removed = [
        task.id
        for task in after.tasks
        if task.persona_ref not in personas or task.scenario_ref not in scenarios
    ]
    # Only references that this change broke are followed. A Test Case that was already
    # broken stays visible, so readiness can name it.
    removed = [
        task_id
        for task_id in removed
        if (task := before.task(task_id)) is not None
        and task.persona_ref in {p.id for p in before.personas}
        and task.scenario_ref in {s.id for s in before.scenarios}
    ]
    after.tasks = [task for task in after.tasks if task.id not in removed]
    for task in after.tasks:
        if gone_behaviours & set(task.behaviour_refs):
            task.behaviour_refs = [
                r for r in task.behaviour_refs if r not in gone_behaviours
            ]
    return removed
