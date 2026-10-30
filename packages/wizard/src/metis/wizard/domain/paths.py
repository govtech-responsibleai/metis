"""Resolving a patch path against the specification tree.

Paths address nodes by id, not by index — `features[F-2].behaviours[EB-4].criteria[AC-4.1]`.
Ids rather than positions because a list can be reordered between the model composing a
patch and the applier running it, and an index would then point at the wrong node silently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from metis.wizard.domain.specification import Specification

# Bracket contents are opaque. Ids are not supposed to contain a dot — `AC-1-1`, not
# `AC-1.1` — precisely because a dot separates path segments. But ids are written by a model,
# so the scan below walks segment by segment rather than splitting on `.`, and `[^\]]*`
# swallows whatever is inside the brackets whole. A model that ignores the naming rule then
# produces an addressable path rather than a silently mangled one.
_SEGMENT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)(?:\[([^\]]*)\])?")


class PathError(Exception):
    """The path is malformed, or names a node that is not there."""


@dataclass(frozen=True)
class Segment:
    field: str
    key: str | None = None  # an id when this segment indexes a list


def parse(path: str) -> list[Segment]:
    segments: list[Segment] = []
    position = 0

    while position < len(path):
        match = _SEGMENT.match(path, position)
        if not match:
            raise PathError(f"Malformed path {path!r} at offset {position}.")
        segments.append(Segment(match.group(1), match.group(2)))
        position = match.end()

        if position < len(path):
            if path[position] != ".":
                raise PathError(f"Malformed path {path!r} at offset {position}.")
            position += 1  # step over the separator
            if position == len(path):
                raise PathError(f"Path {path!r} ends with a separator.")

    if not segments:
        raise PathError(f"Empty path {path!r}.")
    return segments


def _step_into(node: Any, segment: Segment, path: str) -> Any:
    if not hasattr(node, segment.field):
        raise PathError(
            f"{path!r}: no field {segment.field!r} on {type(node).__name__}."
        )
    value = getattr(node, segment.field)

    if segment.key is None:
        return value

    if not isinstance(value, list):
        raise PathError(f"{path!r}: {segment.field!r} is not a list, so it has no ids.")
    for item in value:
        if getattr(item, "id", None) == segment.key:
            return item

    raise PathError(f"{path!r}: no {segment.field[:-1]} with id {segment.key!r}.")


def _render(segments: list[Segment]) -> str:
    """The inverse of `parse` — segments back to a path string."""
    return ".".join(
        segment.field if segment.key is None else f"{segment.field}[{segment.key}]"
        for segment in segments
    )


def _deposition(specification: Specification, segments: list[Segment]) -> list[Segment]:
    """Rewrite any positional bracket (`features[0]`) to the real id at that index.

    Paths are meant to address by id, and a numeric bracket is a model mistake — a user
    tick or edit is always built with real ids. But it is a recoverable one: walking the
    tree top-down, an integer key names the element at that index, whose id we can read and
    substitute. A key that is not a plain integer, or an index off the end, is left as-is so
    it fails downstream exactly as before.
    """
    node: Any = specification
    rewritten: list[Segment] = []
    for segment in segments:
        key = segment.key
        if key is not None and key.lstrip("-").isdigit():
            value = getattr(node, segment.field, None)
            if isinstance(value, list) and -len(value) <= int(key) < len(value):
                real_id = getattr(value[int(key)], "id", None)
                if real_id is not None:
                    segment = Segment(segment.field, real_id)
        rewritten.append(segment)
        try:
            node = _step_into(node, segment, "")
        except PathError:
            # The rest cannot be walked (unknown id, non-list); leave the tail untouched and
            # let apply() report it. Positional keys deeper down simply do not get resolved.
            rewritten.extend(segments[len(rewritten) :])
            return rewritten
    return rewritten


def normalise(specification: Specification, path: str) -> str:
    """Repair a drafted path so a recoverable model mistake does not reach the user.

    Two mistakes, both of which name a node that is plainly there:

    * A positional bracket — `features[0].behaviours[0]` — where the contract is to address by
      id. `_deposition` reads the id at each index and substitutes it.
    * A right, unique behaviour id under the wrong feature ancestor — `features[F-3].behaviours[EB-6]`
      when EB-6 lives under F-4. A behaviour id is unique across the whole specification, so the
      feature segment is redundant for locating it; rewrite it to the feature that truly owns it.

    Anything else is returned unchanged — an unknown id still fails downstream, as it should.
    """
    segments = _deposition(specification, parse(path))
    if (
        len(segments) >= 2
        and segments[0].field == "features"
        and segments[1].field == "behaviours"
        and segments[1].key is not None
    ):
        owner = specification.feature_of(segments[1].key)
        if owner is not None and owner.id != segments[0].key:
            segments[0] = Segment("features", owner.id)
    return _render(segments)


def resolve(specification: Specification, path: str) -> Any:
    """The node a path names."""
    node: Any = specification
    for segment in parse(path):
        node = _step_into(node, segment, path)
    return node


def resolve_parent(specification: Specification, path: str) -> tuple[Any, Segment]:
    """The node *containing* what the path names, plus the final segment.

    What ADD, REMOVE and SET need: to change something you have to hold the thing holding it.
    """
    segments = parse(path)
    node: Any = specification
    for segment in segments[:-1]:
        node = _step_into(node, segment, path)
    return node, segments[-1]
