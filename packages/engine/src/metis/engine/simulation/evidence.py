"""Pointers into the transport log: how code copies a fact the runner agent cites.

The agent never writes a fact into the record. It points at a logged response, and
:func:`resolve` copies the value out of it. Every refusal is a :class:`PointerError`
whose message says what to change, so the agent can correct its pointer and try again.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Collection

    from .transport_log import LogEntry, TransportLog

_STEP = re.compile(r"\.([A-Za-z_][\w-]*)|\[(\d+)\]|\[\"([^\"]+)\"\]")


class PointerError(ValueError):
    """A pointer that cannot be resolved, worded for the agent that wrote it."""


@dataclass(frozen=True)
class Pointer:
    """Where a fact is: a logged entry, a path into its body, and a narrowing pattern."""

    entry: str
    path: str | None = None
    """``$``, ``.key``, ``["key"]`` and ``[n]`` steps; no wildcards."""
    pattern: str | None = None
    """A regular expression applied to the text; its one group, else the whole match."""
    ref: str | None = None
    """An element of a page capture's snapshot (``e12``), instead of a path."""


def _steps(path: str) -> list[str | int]:
    if not path.startswith("$"):
        raise PointerError(f"a path starts with '$': {path!r}")
    steps: list[str | int] = []
    pos = 1
    while pos < len(path):
        match = _STEP.match(path, pos)
        if match is None:
            raise PointerError(
                f'cannot read path {path!r} at {path[pos:]!r}; use .key, ["key"] or [n]'
            )
        key, index, quoted = match.groups()
        steps.append(int(index) if index is not None else key or quoted)
        pos = match.end()
    return steps


def _walk(document: Any, path: str, entry_id: str) -> Any:
    value = document
    for step in _steps(path):
        if (
            isinstance(step, int)
            and isinstance(value, list)
            and step < len(value)
            or isinstance(step, str)
            and isinstance(value, dict)
            and step in value
        ):
            value = value[step]
        else:
            raise PointerError(f"{path!r} is not in the body of entry {entry_id}")
    return value


def resolve(
    pointer: Pointer, log: TransportLog, allowed: Collection[str] | None = None
) -> tuple[Any, LogEntry]:
    """The value a pointer names, and the entry it was copied from.

    :param allowed: When given, the only entry IDs that may be cited.
    :raises PointerError: When the entry is unknown, outside ``allowed`` or an action,
        or the path or pattern leads nowhere.
    """
    if pointer.ref is not None and pointer.path is not None:
        raise PointerError("point at a ref or a path, not both")
    if allowed is not None and pointer.entry not in allowed:
        raise PointerError(
            f"entry {pointer.entry} is not one of the entries you may cite here: "
            f"{', '.join(sorted(allowed)) or 'none'}"
        )
    try:
        entry = log.get(pointer.entry)
    except ValueError:
        raise PointerError(f"no entry {pointer.entry} in the log") from None
    if entry.role != "result":
        raise PointerError(
            f"entry {pointer.entry} is an action you took; cite a result instead"
        )
    try:
        raw = log.body_bytes(entry)
    except (ValueError, OSError) as exc:
        raise PointerError(
            f"the body of entry {pointer.entry} is unreadable: {exc}"
        ) from None

    value: Any
    try:
        if pointer.ref is not None:
            value = _element(raw, pointer.ref, pointer.entry)
        elif pointer.path is None:
            value = raw.decode("utf-8")
        else:
            value = _walk(json.loads(raw), pointer.path, pointer.entry)
    except UnicodeDecodeError:
        raise PointerError(f"the body of entry {pointer.entry} is not text") from None
    except json.JSONDecodeError:
        raise PointerError(
            f"entry {pointer.entry} is not JSON, so a path cannot apply; omit the path"
        ) from None

    if pointer.pattern is not None:
        value = _narrow(value, pointer.pattern)
    return value, entry


def _element(raw: bytes, ref: str, entry_id: str) -> str:
    """The snapshot line marked ``[ref=<ref>]`` and the lines nested under it."""
    try:
        capture = json.loads(raw)
    except ValueError:
        capture = None
    snapshot = capture.get("snapshot") if isinstance(capture, dict) else None
    if not isinstance(snapshot, str):
        raise PointerError(
            f"entry {entry_id} is not a page capture, so a ref cannot apply"
        )
    lines = snapshot.splitlines()
    marker = f"[ref={ref}]"
    for i, line in enumerate(lines):
        if marker in line:
            indent = len(line) - len(line.lstrip())
            block = [line]
            for nested in lines[i + 1 :]:
                if nested.strip() and len(nested) - len(nested.lstrip()) <= indent:
                    break
                block.append(nested)
            return "\n".join(text[indent:] for text in block)
    raise PointerError(f"no element {ref} in the snapshot of entry {entry_id}")


def _narrow(value: Any, pattern: str) -> str:
    if not isinstance(value, str):
        raise PointerError("a pattern applies only to text, but the value is not text")
    try:
        match = re.search(pattern, value)
    except re.error as exc:
        raise PointerError(f"pattern {pattern!r} does not compile: {exc}") from None
    if match is None:
        raise PointerError(f"pattern {pattern!r} does not match the value")
    return match.group(1) if match.groups() else match.group(0)
