"""CLI input for the interview opening fields."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from metis.wizard.adapters.cli.connection import panel
from metis.wizard.adapters.cli.keys import (
    Choice,
    Divider,
    Heading,
    Nav,
    Picked,
    Step,
    walk,
)
from metis.wizard.application.config import load_config
from metis.wizard.contracts.interview_state import CapabilityConfidence, Perspective

if TYPE_CHECKING:
    from rich.panel import Panel

    from metis.wizard.adapters.cli.keys import KeyPrompter, Row
    from metis.wizard.contracts.capabilities import CapabilityId

Printer = Callable[[str], None]
Reader = Callable[[str], str]


def welcome() -> Panel:
    """The greeting before the first opening question.

    The welcome is a heavy, coloured box with a centred title, so it reads as the start of the
    run. The step headers that follow are plain rounded boxes. A console that is not a terminal
    draws the box with no colour.
    """
    from rich import box
    from rich.console import Group
    from rich.panel import Panel
    from rich.text import Text

    body = Group(
        Text("Welcome to the METIS Wizard!", style="bold", justify="center"),
        Text(""),
        Text(
            "Tell me about your product, and we will build an evaluation together.\n"
            "You can review and change each part before it is saved.",
            justify="center",
        ),
    )
    return Panel(body, box=box.DOUBLE, border_style="cyan", padding=(1, 2))


def read_description(*, out: Printer, read: Reader = input) -> str:
    """Ask the package opening question until the user gives a description."""
    out(panel("Your product", load_config().opening_question))
    while True:
        description = read("> ").strip()
        if description:
            return description
        out("  Enter a description of the target.")


def read_capability_evidence(
    *, out: Printer, read: Reader = input, prompter: KeyPrompter | None = None
) -> tuple[list[CapabilityId] | None, CapabilityConfidence | None]:
    """Show the capability catalogue and read the required opening evidence.

    With a `prompter`, Space selects a capability and Enter on Continue or Skip answers. Esc on
    the confidence asks the capabilities again, with the selection kept.
    """
    if prompter is not None:
        return _pick_capability_evidence(out, prompter)
    categories = load_config().capability_categories
    choices: list[tuple[CapabilityId, str]] = []
    out(panel("Capabilities", "Select any that you know the target has."))
    for category in categories:
        out(f"\n{category.name}")
        out("─" * len(category.name))
        for capability in category.capabilities:
            choices.append((capability.id, capability.name))
            out(
                f"  {len(choices)}. {capability.name} ({capability.id.value})"
                f" — {capability.description}"
            )

    by_number = {
        str(index): capability_id for index, (capability_id, _) in enumerate(choices, 1)
    }
    by_name = {name.casefold(): capability_id for capability_id, name in choices}
    by_id = {
        capability_id.value.casefold(): capability_id for capability_id, _ in choices
    }
    while True:
        raw = read(
            "\nKnown capabilities (comma-separated numbers or names; blank for none; skip to omit): "
        ).strip()
        if raw.casefold() == "skip":
            return None, None
        if not raw:
            selected: list[CapabilityId] = []
            break
        selected = []
        unknown: list[str] = []
        for token in (part.strip() for part in raw.split(",")):
            if not token:
                continue
            capability_id = (
                by_number.get(token)
                or by_name.get(token.casefold())
                or by_id.get(token.casefold())
            )
            if capability_id is None:
                unknown.append(token)
            elif capability_id not in selected:
                selected.append(capability_id)
        if unknown:
            out("  Choose only the numbered, named, or id values shown above.")
            continue
        break

    while True:
        raw = (
            read(
                "How confident are you that this selection covers all capabilities? "
                "(low/medium/high): "
            )
            .strip()
            .casefold()
        )
        try:
            confidence = CapabilityConfidence(raw)
        except ValueError:
            out("  Enter low, medium, or high.")
            continue
        return selected, confidence


_CONTINUE = "continue"
_SKIP = "skip"


def _pick_capability_evidence(
    out: Printer, prompter: KeyPrompter
) -> tuple[list[CapabilityId] | None, CapabilityConfidence | None]:
    answers: dict[str, Any] = {}

    def capabilities(answers: dict[str, Any], _back: bool) -> Any:
        kept = set(answers.get("capabilities") or [])
        rows: list[Row[Any]] = []
        for category in load_config().capability_categories:
            rows.append(Heading(category.name))
            rows.extend(
                Choice(
                    capability.id,
                    f"{capability.name} ({capability.id.value})",
                    detail=capability.description,
                    selected=capability.id in kept,
                )
                for capability in category.capabilities
            )
        rows += [
            Divider(),
            Choice(_CONTINUE, "Continue"),
            Choice(_SKIP, "Skip (leave the capabilities unspecified)"),
        ]
        out(panel("Capabilities", "Select any that you know the target has."))
        picked = prompter.pick(rows, name="Known capabilities", default=_CONTINUE)
        assert isinstance(picked, Picked)
        if picked.action == _SKIP:
            return None
        return list(picked.on)

    def confidence(answers: dict[str, Any], back: bool) -> Any:
        return prompter.choose(
            [Choice(level, level.value) for level in CapabilityConfidence],
            name="Confidence",
            default=answers.get("confidence"),
            back=back,
            title="How confident are you that this selection covers all capabilities?",
        )

    walk(
        [
            Step("capabilities", capabilities),
            Step("confidence", confidence, lambda a: a["capabilities"] is not None),
        ],
        answers,
    )
    if answers["capabilities"] is None:
        return None, None
    return answers["capabilities"], answers["confidence"]


def read_perspective(
    *,
    out: Printer,
    read: Reader = input,
    prompter: KeyPrompter | None = None,
    default: Perspective = Perspective.END_USER,
    back: bool = False,
) -> Perspective | Nav:
    """Ask which Perspective guides the Interview, in the order of the package config.

    With a `prompter`, the picker shows each label and the question of the highlighted one, and
    Esc returns `BACK` when `back` allows it. The text menu reads a number, an id, or a label.
    """
    choices = load_config().perspectives
    out(panel("Perspective", "Which Perspective should guide this evaluation?"))
    if prompter is not None:
        return prompter.choose(
            [Choice(c.id, c.label, detail=c.question) for c in choices],
            name="Perspective",
            default=default,
            back=back,
        )
    for index, choice in enumerate(choices, 1):
        out(f"  {index}. {choice.label}: {choice.question}")
    while True:
        raw = read("Perspective (number or name): ").strip().casefold()
        for index, choice in enumerate(choices, 1):
            if raw in {str(index), choice.id.value, choice.label.casefold()}:
                return choice.id
        out("Choose one of the Perspectives shown above.")
