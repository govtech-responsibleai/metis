"""Shared definitions for grading scopes: which part of a session each grader result is about.

A grader declares its scopes in ``taxonomy.scopes``, and ``Grader.scope`` is the one set
for a criterion. ``SCOPE_DEFINITIONS[grader.scope]`` holds what to tell the judge about that
scope, the trace processor function that selects what to judge, and the one that renders each
selected piece. A grader judges each piece and returns one result for each.

The ``*Args`` classes here are the settings a scope reads. A grader's args model inherits the
ones for its declared scopes, as ``SCOPE_SETTINGS`` lists; ``Grader`` checks that they match.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from metis.core.trace_processing import (
    FileInput,
    render_artifact,
    render_session,
    select_by_artifact,
    select_by_turn,
    select_by_window,
    select_session,
    turns,
)
from metis.library.taxonomy import Scope
from metis.library.text import NonEmptyText  # noqa: TC001 — a Pydantic field type

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from metis.core.trace_processing import Problem
    from metis.core.traces import GradingInput


class TraceArgs(BaseModel):
    """The setting of the ``trace`` scope."""

    turn: Literal["each", "last"] = "each"
    """``each`` judges every recorded turn, each on its own. ``last`` judges only the final
    recorded turn."""


class SubsessionArgs(BaseModel):
    """The settings of the ``subsession`` scope."""

    turn: Literal["each", "last"] = "each"
    """The recorded turn each subsession ends at: ``each`` recorded turn, or only the ``last``
    one."""
    window: int | None = Field(default=None, ge=1, strict=True)
    """How many recorded turns one subsession holds: its end turn and the recorded turns just
    before it. ``None`` holds every recorded turn before it, so the judge has the whole
    conversation so far. The recorded turns before the subsession are not shown to the judge."""


class ArtifactArgs(BaseModel):
    """The setting of the ``artifact`` scope."""

    artifact: NonEmptyText | None = None
    """The name of the file to judge. When the target revised the file, the judge reads the
    latest version."""


SCOPE_SETTINGS: dict[Scope, type[BaseModel]] = {
    Scope.TRACE: TraceArgs,
    Scope.SUBSESSION: SubsessionArgs,
    Scope.ARTIFACT: ArtifactArgs,
}
"""The settings class that a grader's args model inherits for each scope it declares."""


@dataclass(frozen=True)
class ScopeDefinition:
    """What the judge is told about one scope, the trace processor function that selects what
    to judge, and the one that renders each selected piece for the judge.

    In ``instructions``, and in every prompt a grader sends the judge, "turn" means a
    **recorded turn** (``GLOSSARY.md``): one trace, shown to the judge under a ``## Turn N``
    heading. The judge never sees the glossary, so the prompts keep the word the transcript
    uses. Do not write "recorded turn" in a prompt, and never mean a simulated turn there.
    """

    instructions: str
    select: Callable[[GradingInput, Any], Mapping[str, Any] | Problem]
    render: Callable[[Any], str | FileInput | Problem]


SCOPE_DEFINITIONS: dict[Scope, ScopeDefinition] = {
    Scope.TRACE: ScopeDefinition(
        instructions=(
            "Judge the one turn in the evidence: the user's message, what the assistant "
            "did, and its reply."
        ),
        select=lambda input, args: select_by_turn(
            turns(input.traces), last_only=args.turn == "last"
        ),
        render=lambda turn: render_session(turn, tool_results=True),
    ),
    Scope.SUBSESSION: ScopeDefinition(
        instructions=(
            "Judge the assistant's reply in the LAST turn of the evidence. Use the earlier "
            "turns only as context for that reply. Do not judge the earlier replies."
        ),
        select=lambda input, args: select_by_window(
            turns(input.traces), args.window, last_only=args.turn == "last"
        ),
        render=lambda window: render_session(window, tool_results=True),
    ),
    Scope.SESSION: ScopeDefinition(
        instructions=(
            "Judge the whole conversation as one unit. Read every turn before you decide. "
            "In your reason, name the turns that support the judgment."
        ),
        select=lambda input, _: select_session(turns(input.traces)),
        render=lambda session: render_session(session, tool_results=True),
    ),
    Scope.ARTIFACT: ScopeDefinition(
        instructions=("Judge only the attached file."),
        select=lambda input, args: select_by_artifact(input, args.artifact),
        render=render_artifact,
    ),
}
