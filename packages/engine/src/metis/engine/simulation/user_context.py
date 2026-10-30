"""Persona and scenario text for the user agent's system prompt."""

from __future__ import annotations


def with_metadata(description: str, metadata: dict[str, str], heading: str) -> str:
    """Append ``metadata`` under ``heading``, one ``- key: value`` line per entry.

    Keys are the Specification author's own names and are shown as written. None is
    read as an Engine setting. Empty metadata returns ``description`` unchanged.
    """
    if not metadata:
        return description
    lines = "\n".join(f"- {key}: {value}" for key, value in metadata.items())
    return f"{description}\n\n{heading}\n{lines}"


def persona_text(description: str, metadata: dict[str, str]) -> str:
    return with_metadata(
        description,
        metadata,
        "More about you (use this to shape how you write and act):",
    )


def scenario_text(description: str, metadata: dict[str, str]) -> str:
    return with_metadata(description, metadata, "More about the situation:")
