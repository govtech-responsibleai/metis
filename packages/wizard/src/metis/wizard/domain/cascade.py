"""Transport-neutral impact rules for edits to a wizard specification.

This module deliberately knows nothing about screens, requests, or terminal/web UI.  It
answers the domain question: which derived nodes are affected by a set of edits, and what
derived state can be discarded when a user asks for regeneration?
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from metis.wizard.domain.patch import Patch
    from metis.wizard.domain.specification import Specification

BEHAVIOUR_DESCRIPTION = "description"
TARGET_WIDE = ("target.description", "target.detail")


@dataclass(frozen=True)
class Impact:
    """A derived specification node whose current value may need a user decision."""

    subject: str
    kind: str  # "criteria" | "scenario" | "tree"
    related_to: str | None = None


def impacts_for(specification: Specification, patches: list[Patch]) -> list[Impact]:
    """Return derived nodes affected by ``patches``, in user-facing order."""
    impacts: list[Impact] = []
    seen: set[tuple[str, str]] = set()

    for patch in patches:
        path = patch.path

        if path in TARGET_WIDE:
            has_derived_work = bool(specification.features) or bool(
                specification.scenarios
            )
            if not has_derived_work:
                continue
            key = ("tree", "target")
            if key not in seen:
                seen.add(key)
                impacts.append(Impact(subject=path, kind="tree"))
            continue

        if (
            path.startswith("features[")
            and path.endswith("].description")
            and ".behaviours[" not in path
        ):
            feature_id = path.split("[", 1)[1].split("]", 1)[0]
            feature = specification.feature(feature_id)
            if feature is not None and ("feature", feature_id) not in seen:
                seen.add(("feature", feature_id))
                impacts.append(Impact(subject=feature_id, kind="feature"))
            continue

        if not path.endswith(f".{BEHAVIOUR_DESCRIPTION}"):
            continue

        behaviour_id = _behaviour_id(path)
        behaviour = specification.behaviour(behaviour_id) if behaviour_id else None
        if behaviour is None:
            continue

        if behaviour.criteria and ("criteria", behaviour.id) not in seen:
            seen.add(("criteria", behaviour.id))
            impacts.append(Impact(subject=behaviour.id, kind="criteria"))

        for scenario in specification.scenarios_covering(behaviour.id):
            if ("scenario", scenario.id) in seen:
                continue
            seen.add(("scenario", scenario.id))
            impacts.append(
                Impact(subject=scenario.id, kind="scenario", related_to=behaviour.id)
            )

    return impacts


def clear_for_regeneration(
    specification: Specification,
    impact: Impact,
    user_typed: set[str] | None = None,
) -> None:
    """Discard only model-derived state represented by ``impact``."""
    if impact.kind == "criteria":
        behaviour = specification.behaviour(impact.subject)
        if behaviour is not None:
            if user_typed is None:
                user_typed = set()
            behaviour.criteria = [c for c in behaviour.criteria if c.id in user_typed]

    elif impact.kind == "scenario":
        scenario = specification.scenario(impact.subject)
        if scenario is not None and (
            user_typed is None or scenario.id not in user_typed
        ):
            specification.scenarios = [
                s for s in specification.scenarios if s.id != impact.subject
            ]

    elif impact.kind == "tree":
        keep = user_typed or set()
        specification.features = [
            feature for feature in specification.features if feature.id in keep
        ]
        specification.scenarios = [
            scenario for scenario in specification.scenarios if scenario.id in keep
        ]


def _behaviour_id(path: str) -> str | None:
    """Extract ``EB-*`` from ``features[F-1].behaviours[EB-4].description``."""
    marker = "behaviours["
    if marker not in path:
        return None
    return path.split(marker, 1)[1].split("]", 1)[0]
