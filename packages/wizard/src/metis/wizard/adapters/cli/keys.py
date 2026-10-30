"""Terminal input for the CLI: keys in an interactive terminal, typed text in all other runs.

A question is data: a list of rows, a label, and a default. A `Choice` row can be selected. A
`Heading`, `Title`, `Note`, or `Divider` row is screen text between the choices, and the cursor
skips it. A `Prompter` is the input
mode. `KeyPrompter` reads arrow keys, Space, Enter, and Esc, and shows a grey hint line under the
question with only the keys that the question accepts. `TextPrompter` prints numbered menus and
reads typed lines, as a run with redirected input always did. `key_input_available` decides
which mode a run uses.

The picker is not a full-screen application. It draws under the question, and when the user
answers, it leaves one short line with the answer in the scrollback.
"""

from __future__ import annotations

import os
import sys
import textwrap
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Generic, Literal, Protocol, TypeVar

if TYPE_CHECKING:
    from prompt_toolkit.formatted_text import StyleAndTextTuples
    from prompt_toolkit.input import Input
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.output import Output

T = TypeVar("T")
Printer = Callable[[str], None]
Reader = Callable[[str], str]


class Nav(Enum):
    """A navigation answer. `BACK` means the user pressed Esc to go to the question before."""

    BACK = "back"


BACK = Nav.BACK


@dataclass(frozen=True)
class Choice(Generic[T]):
    """One row of a question.

    `selected` is `None` for an action row, which Enter accepts, and a bool for a toggle row,
    which Space turns on or off. `indent` is in steps of two columns, after the two columns
    of the cursor mark, so a row at `indent` 0 lines up with a text row at `indent` 1. `detail` is longer text: the text menu prints it after the
    label, and the picker shows it under the list for the highlighted row only. `aliases` are
    the words that the text menu also accepts.
    """

    value: T
    label: str
    detail: str = ""
    enabled: bool = True
    selected: bool | None = None
    aliases: tuple[str, ...] = ()
    section: str | None = None
    indent: int = 0


@dataclass(frozen=True)
class Heading:
    """A section heading."""

    text: str


@dataclass(frozen=True)
class Title:
    """A line that names an item that has no row of its own to select."""

    text: str
    indent: int = 0


@dataclass(frozen=True)
class Note:
    """A line of text under an item. `tone` sets its colour: grey, orange, or red."""

    text: str
    indent: int = 0
    tone: Literal["muted", "warning", "stop"] = "muted"


@dataclass(frozen=True)
class Divider:
    """A rule between two groups of rows."""


Row = Choice[T] | Heading | Title | Note | Divider


@dataclass(frozen=True)
class Picked(Generic[T]):
    """The answer of a picker with toggle rows.

    `on` holds the toggle values that are on at the end, in row order. `changed` holds the
    toggle values whose state differs from the start. `action` is the action row that Enter
    accepted, or `None` when Enter was on a toggle row.
    """

    on: tuple[T, ...]
    changed: tuple[T, ...]
    action: T | None


@dataclass(frozen=True)
class Typed:
    """The text mode of a question that reads one typed word in place of a numbered menu.

    Each choice's first alias is the word. `prompt` is the line to type it on, and `error` is
    the line after a word that no choice has.
    """

    prompt: str
    error: str


class Prompter(Protocol):
    def choose(
        self,
        choices: Sequence[Choice[T]],
        *,
        name: str,
        default: T | None = None,
        back: bool = False,
        typed: Typed | None = None,
        title: str | None = None,
    ) -> T | Nav:
        """Ask for one row. `back` allows Esc. `typed` replaces the numbered text menu with one
        typed word. `title` is a line above the picker rows."""
        ...

    def choose_many(
        self, choices: Sequence[Choice[T]], *, name: str, back: bool = False
    ) -> list[T] | Nav:
        """Ask for any number of toggle rows. Returns the values that are on."""
        ...

    def text(self, label: str, default: str = "", *, back: bool = False) -> str | Nav:
        """Ask for a line of text. Enter with no change keeps `default`."""
        ...

    def confirm(self, label: str, default: bool, *, back: bool = False) -> bool | Nav:
        """Ask a yes or no question."""
        ...


def key_input_available() -> bool:
    """Whether this run can read keys: stdin and stdout are a terminal that can draw."""
    return (
        sys.stdin.isatty()
        and sys.stdout.isatty()
        and os.environ.get("TERM", "") != "dumb"
    )


def _or(words: Sequence[str]) -> str:
    """`1 or 2`, or `low, medium, or high`."""
    if len(words) <= 2:
        return " or ".join(words)
    return f"{', '.join(words[:-1])}, or {words[-1]}"


# ── typed text ──────────────────────────────────────────────────────────────


class TextPrompter:
    """Numbered menus and typed lines. This mode never returns `BACK`."""

    def __init__(self, out: Printer, read: Reader = input) -> None:
        self._out = out
        self._read = read

    def choose(
        self,
        choices: Sequence[Choice[T]],
        *,
        name: str,
        default: T | None = None,
        back: bool = False,
        typed: Typed | None = None,
        title: str | None = None,
    ) -> T:
        if typed is not None:
            return self._choose_typed(choices, typed)
        numbers = [str(index) for index in range(1, len(choices) + 1)]
        for number, choice in zip(numbers, choices, strict=True):
            detail = f": {choice.detail}" if choice.detail else ""
            self._out(f"  {number}. {choice.label}{detail}")
        values = [choice.value for choice in choices]
        blank = numbers[values.index(default)] if default in values else numbers[0]
        options = _or(numbers)
        while True:
            raw = self._read(f"{name} ({options}, blank for {blank}): ")
            raw = raw.strip().casefold() or blank
            for number, choice in zip(numbers, choices, strict=True):
                if choice.enabled and raw in (number, *choice.aliases):
                    return choice.value
            self._out(f"  Enter {options}.")

    def _choose_typed(self, choices: Sequence[Choice[T]], typed: Typed) -> T:
        """One typed word. A one-letter alias also matches a word that starts with it."""
        while True:
            raw = self._read(f"{typed.prompt}: ").strip().casefold()
            for choice in choices:
                if choice.enabled and (
                    raw in choice.aliases or raw[:1] in choice.aliases
                ):
                    return choice.value
            self._out(typed.error)

    def choose_many(
        self, choices: Sequence[Choice[T]], *, name: str, back: bool = False
    ) -> list[T]:
        by_word: dict[str, T] = {}
        section = None
        for number, choice in enumerate(choices, start=1):
            if choice.section != section and choice.section:
                section = choice.section
                self._out(f"\n{section}")
                self._out("─" * len(section))
            detail = f" — {choice.detail}" if choice.detail else ""
            self._out(f"  {number}. {choice.label}{detail}")
            for word in (str(number), *choice.aliases):
                by_word[word.casefold()] = choice.value
        while True:
            raw = self._read(
                f"\n{name} (comma-separated numbers or names; blank for none): "
            )
            tokens = [token.strip() for token in raw.split(",") if token.strip()]
            unknown = [token for token in tokens if token.casefold() not in by_word]
            if unknown:
                self._out(
                    "  Choose only the numbered, named, or id values shown above."
                )
                continue
            return list(dict.fromkeys(by_word[token.casefold()] for token in tokens))

    def text(self, label: str, default: str = "", *, back: bool = False) -> str:
        shown = f" [{default}]" if default else ""
        return self._read(f"{label}{shown}: ").strip() or default

    def confirm(self, label: str, default: bool, *, back: bool = False) -> bool:
        raw = self.text(f"{label} (y/n)", "y" if default else "n")
        return not raw.casefold().startswith("n")


# ── keys ─────────────────────────────────────────────────────────────────────

_STYLE = {
    "hint": "fg:#8a8a8a",
    "muted": "fg:#8a8a8a",
    "cursor": "bold",
    "section": "bold",
    "warning": "fg:#ff8700",
    "stop": "fg:ansired bold",
}
# Rows for the hint, the selected count, the detail line, and one spare line.
_RESERVED_ROWS = 4
_SEPARATOR = " | "


class _Picker(Generic[T]):
    """The state of one picker: the highlighted row and the toggles that are on.

    Indexes point into `items`, the rows in screen order. Only a `Choice` row takes the cursor.
    """

    def __init__(
        self,
        rows: Sequence[Row[T]],
        *,
        default: T | None,
        back: bool,
    ) -> None:
        self.items = list(rows)
        self.choices = {i: row for i, row in enumerate(rows) if isinstance(row, Choice)}
        self.back = back
        self.initial = {i for i, choice in self.choices.items() if choice.selected}
        self.on: set[int] = set(self.initial)
        self.rows = [i for i, choice in self.choices.items() if choice.enabled]
        start = next(
            (i for i, choice in self.choices.items() if choice.value == default), -1
        )
        self.cursor: int | None = (
            start if start in self.rows else (self.rows[0] if self.rows else None)
        )

    def _toggle_row(self, index: int | None) -> bool:
        return index in self.choices and self.choices[index].selected is not None

    @property
    def has_toggles(self) -> bool:
        return any(choice.selected is not None for choice in self.choices.values())

    def move(self, step: int) -> None:
        if self.cursor is None:
            return
        position = self.rows.index(self.cursor) + step
        if 0 <= position < len(self.rows):
            self.cursor = self.rows[position]

    def toggle(self) -> None:
        if self.cursor is not None and self._toggle_row(self.cursor):
            self.on ^= {self.cursor}

    def _values(self, indexes: set[int]) -> tuple[T, ...]:
        return tuple(self.choices[i].value for i in sorted(indexes))

    def enter_label(self) -> str | None:
        """What Enter does on the highlighted row, or `None` when Enter does nothing there."""
        if self.cursor is None:
            return None
        if not self._toggle_row(self.cursor):
            return self.choices[self.cursor].label
        return "Continue"

    def enter(self) -> Picked[T] | None:
        if self.enter_label() is None or self.cursor is None:
            return None
        action = None
        if not self._toggle_row(self.cursor):
            action = self.choices[self.cursor].value
        return Picked(
            on=self._values(self.on),
            changed=self._values(self.on ^ self.initial),
            action=action,
        )

    def hint(self) -> str:
        """The keys that the highlighted row accepts, in a fixed order."""
        parts: list[str] = []
        if self.back:
            parts.append("Esc back")
        if len(self.rows) > 1:
            parts.append("↑↓ move")
        if self._toggle_row(self.cursor):
            parts.append("Space select")
        enter = self.enter_label()
        if enter is not None:
            parts.append(f"Enter {enter}")
        return _SEPARATOR.join(parts)

    def summary(self, picked: Picked[T] | Nav) -> str:
        """The short line that stays in the scrollback after the answer."""
        if picked is BACK:
            return "back"
        assert isinstance(picked, Picked)
        labels = {choice.value: choice.label for choice in self.choices.values()}
        if picked.action is not None:
            changed = f" ({len(picked.changed)} changed)" if picked.changed else ""
            return f"{labels[picked.action]}{changed}"
        if len(picked.on) > 3:
            return f"{len(picked.on)} selected"
        return ", ".join(labels[value] for value in picked.on) or "none"

    def _choice_line(self, index: int, choice: Choice[T]) -> list[tuple[str, str]]:
        pad = "  " * choice.indent
        box = ""
        if choice.selected is not None:
            box = "[x] " if index in self.on else "[ ] "
        label = choice.label
        if not choice.enabled:
            return [("class:muted", f"{pad}  {box}{label}   (unavailable)")]
        if index == self.cursor:
            return [("class:cursor", f"{pad}› {box}{label}")]
        return [("", f"{pad}  {box}{label}")]

    def lines(self, height: int, width: int = 80) -> StyleAndTextTuples:
        """The rows to draw, cut to `height` lines around the highlighted row.

        Text rows wrap to `width`, so the cut counts the lines that the terminal shows.
        """

        def wrapped(style: str, text: str, indent: int) -> list[list[tuple[str, str]]]:
            pad = "  " * indent
            # a wrapped "- item" line continues under the item text, not under the dash
            hang = "  " if text.startswith("- ") else ""
            parts = textwrap.wrap(
                text, max(width - len(pad) - 1, 20), subsequent_indent=hang
            )
            return [[(style, f"{pad}{part}")] for part in parts or [""]]

        drawn: list[list[tuple[str, str]]] = []
        cursor_line = 0
        for index, item in enumerate(self.items):
            match item:
                case Heading():
                    drawn.append([("class:section", item.text)])
                case Title():
                    drawn.extend(wrapped("", item.text, item.indent))
                case Note():
                    drawn.extend(wrapped(f"class:{item.tone}", item.text, item.indent))
                case Divider():
                    drawn.append([("class:muted", "─" * max(width - 1, 1))])
                case Choice():
                    if index == self.cursor:
                        cursor_line = len(drawn)
                    drawn.append(self._choice_line(index, item))

        height = max(height, 3)
        if len(drawn) > height:
            start = min(max(cursor_line - height // 2, 0), len(drawn) - height)
            end = start + height
            above, below = start, len(drawn) - end
            shown = drawn[start:end]
            if above:
                shown[0] = [("class:muted", f"  ↑ {above + 1} more")]
            if below:
                shown[-1] = [("class:muted", f"  ↓ {below + 1} more")]
            drawn = shown

        if self.has_toggles:
            drawn.append([("class:muted", f"  {len(self.on)} selected")])
        detail = self.choices[self.cursor].detail if self.cursor is not None else ""
        if detail:
            drawn.append([("class:muted", f"  {detail}")])

        fragments: StyleAndTextTuples = []
        for number, line in enumerate(drawn):
            if number:
                fragments.append(("", "\n"))
            fragments.extend(line)
        return fragments


def _with_headings(choices: Sequence[Choice[T]]) -> list[Row[T]]:
    """The choices with a heading row before each new `section`."""
    rows: list[Row[T]] = []
    section = None
    for choice in choices:
        if choice.section != section and choice.section:
            section = choice.section
            rows.append(Heading(section))
        rows.append(choice)
    return rows


# ── a review screen ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Line:
    """A line of text under an item. `tone` sets its colour."""

    text: str
    tone: Literal["plain", "muted", "warning", "stop"] = "muted"


@dataclass(frozen=True)
class Details:
    """Supporting text under an item. It is closed unless `expanded`."""

    title: str
    lines: tuple[Line, ...] = ()
    expanded: bool = False
    indent: int = 0


@dataclass(frozen=True)
class Item(Generic[T]):
    """One selectable row of a review: an item or a screen action.

    Enter sends the `action` of the row. A row with no action is an item to read, select, or
    open, and Enter on it sends the review's default action (Continue). With a `toggle`, Space
    turns the checkbox on or off on this side. `cells` makes the item a table row under the
    `TableHeader` before it. `count` shows the number of toggles that are on.
    """

    label: str
    action: T | None = None
    toggle: T | None = None
    selected: bool = False
    lines: tuple[Line, ...] = ()
    details: tuple[Details, ...] = ()
    cells: tuple[str, ...] = ()
    enabled: bool = True
    indent: int = 0
    count: bool = False


@dataclass(frozen=True)
class TableHeader:
    """The column titles of the table rows that come after it."""

    titles: tuple[str, ...]


ReviewRow = Item[T] | Heading | Title | Note | Divider | TableHeader


@dataclass(frozen=True)
class Reviewed(Generic[T]):
    """The answer of a review.

    `changed` holds the toggles whose state differs from the start. `action` is the action that
    Enter sent. `feedback` is the text that the user typed on the feedback line.
    """

    changed: tuple[T, ...] = ()
    action: T | None = None
    feedback: str | None = None


def _cut(text: str, width: int) -> str:
    return text if len(text) <= width else text[: max(width - 1, 0)] + "…"


class Review(Generic[T]):
    """The state of one review: the cursor, the toggles that are on, and the open details.

    Tab moves the focus to the feedback line under the screen options, and Tab or Esc moves it
    back to the list. The list stays on the screen while the user types.
    """

    def __init__(
        self,
        rows: Sequence[ReviewRow[T]],
        *,
        back: T | None = None,
        default: T | None = None,
        feedback: bool = False,
    ) -> None:
        self.rows = list(rows)
        self.back = back
        self.default = default
        self.feedback = feedback
        self.items = [
            i for i, row in enumerate(rows) if isinstance(row, Item) and row.enabled
        ]
        self.on = {
            i
            for i, row in enumerate(rows)
            if isinstance(row, Item) and row.toggle is not None and row.selected
        }
        self.initial = set(self.on)
        self.open: set[int] = set()
        self.cursor: int | None = self.items[0] if self.items else None
        self.writing = False

    def _item(self, index: int | None) -> Item[T] | None:
        row = self.rows[index] if index is not None else None
        return row if isinstance(row, Item) else None

    @property
    def changed(self) -> tuple[T, ...]:
        values = []
        for i in sorted(self.on ^ self.initial):
            item = self._item(i)
            if item is not None and item.toggle is not None:
                values.append(item.toggle)
        return tuple(values)

    @property
    def has_toggles(self) -> bool:
        return any(
            isinstance(row, Item) and row.toggle is not None for row in self.rows
        )

    def move(self, step: int) -> None:
        if self.cursor is None:
            return
        position = self.items.index(self.cursor) + step
        if 0 <= position < len(self.items):
            self.cursor = self.items[position]

    def toggle(self) -> None:
        item = self._item(self.cursor)
        if self.cursor is not None and item is not None and item.toggle is not None:
            self.on ^= {self.cursor}

    def _closed_details(self) -> bool:
        item = self._item(self.cursor)
        return (
            item is not None
            and self.cursor not in self.open
            and any(not d.expanded for d in item.details)
        )

    def right(self) -> None:
        if self.cursor is not None and self._closed_details():
            self.open.add(self.cursor)

    def left(self) -> None:
        if self.cursor is not None:
            self.open.discard(self.cursor)

    def _target(self) -> T | None:
        """What Enter sends on the highlighted row: its own action, or the default action."""
        item = self._item(self.cursor)
        if item is not None and item.action is not None:
            return item.action
        return self.default

    def _label_of(self, value: T) -> str:
        for row in self.rows:
            if isinstance(row, Item) and row.action == value:
                return row.label
        return ""

    def enter_label(self) -> str | None:
        """What Enter does on the highlighted row, or `None` when Enter does nothing there."""
        if self.changed:
            count = len(self.changed)
            return f"apply {count} {'change' if count == 1 else 'changes'}"
        target = self._target()
        return None if target is None else self._label_of(target)

    def enter(self) -> Reviewed[T] | None:
        """Send the changed toggles, or the action of the highlighted row."""
        if self.changed:
            return Reviewed(changed=self.changed)
        target = self._target()
        return None if target is None else Reviewed(action=target)

    def escape(self) -> Reviewed[T] | None:
        """Go back when the screen offers Back."""
        return None if self.back is None else Reviewed(action=self.back)

    def can_write(self) -> bool:
        """Whether Tab opens the feedback line. Pending toggles are sent first."""
        return self.feedback and not self.changed

    def write(self) -> None:
        """Move the focus to the feedback line, or back to the list."""
        self.writing = not self.writing and self.can_write()

    def hint(self) -> str:
        """The keys that the focused context accepts, in a fixed order."""
        if self.writing:
            return _SEPARATOR.join(
                ["Esc or Tab back to the list", "Enter send feedback"]
            )
        parts: list[str] = []
        item = self._item(self.cursor)
        if self.back is not None:
            parts.append("Esc back")
        if len(self.items) > 1:
            parts.append("↑↓ move")
        if item is not None and item.toggle is not None:
            parts.append("Space select")
        if self._closed_details():
            parts.append("→ details")
        elif self.cursor in self.open:
            parts.append("← hide details")
        enter = self.enter_label()
        if enter is not None:
            parts.append(f"Enter {enter}")
        if self.can_write():
            parts.append("Tab feedback")
        return _SEPARATOR.join(parts)

    def summary(self, answer: Reviewed[T]) -> str:
        """The short line that stays in the scrollback after the answer."""
        if answer.feedback is not None:
            return "feedback"
        if answer.changed:
            return f"{len(answer.changed)} changed"
        return "" if answer.action is None else self._label_of(answer.action)

    # ── drawing ──

    def _table(self, start: int, width: int) -> tuple[str, list[int], bool]:
        """The lead space, the column widths, and whether a row fits on one line, for the
        table that starts at `start`. A row that does not fit takes two lines."""
        header = self.rows[start]
        assert isinstance(header, TableHeader)
        rows: list[Item[T]] = []
        for row in self.rows[start + 1 :]:
            if not (isinstance(row, Item) and row.cells):
                break
            rows.append(row)
        indent = rows[0].indent if rows else 0
        # The cursor mark and the checkbox come before the first cell.
        lead = "  " * indent + "  " + "    "
        widths = [
            max([len(title), *(len(r.cells[j]) for r in rows if j < len(r.cells))])
            for j, title in enumerate(header.titles)
        ]
        available = width - len(lead) - 1
        if sum(widths) + 2 * (len(widths) - 1) <= available:
            return lead, widths, True
        first = min(widths[0], max((available - 2) // 2, 8))
        return lead, [first, max(available - 2 - first, 8)], False

    def lines(self, height: int, width: int = 80) -> StyleAndTextTuples:
        """The rows to draw, cut to `height` lines around the highlighted row."""

        def wrapped(style: str, text: str, pad: str) -> list[list[tuple[str, str]]]:
            parts = textwrap.wrap(text, max(width - len(pad) - 1, 20))
            return [[(style, f"{pad}{part}")] for part in parts or [""]]

        drawn: list[list[tuple[str, str]]] = []
        cursor_line = 0
        table: tuple[tuple[str, ...], list[int], bool] = ((), [], True)
        lead = ""
        for index, row in enumerate(self.rows):
            if (
                isinstance(row, (Heading, TableHeader))
                and drawn
                and not isinstance(row, TableHeader)
            ):
                drawn.append([("", "")])
            match row:
                case Heading():
                    drawn.append([("class:section", row.text)])
                case Title():
                    drawn.extend(wrapped("", row.text, "  " * row.indent))
                case Note():
                    drawn.extend(
                        wrapped(f"class:{row.tone}", row.text, "  " * row.indent)
                    )
                case Divider():
                    drawn.append([("class:muted", "─" * max(width - 1, 1))])
                case TableHeader():
                    lead, widths, one_line = self._table(index, width)
                    table = (row.titles, widths, one_line)
                    titles = row.titles if one_line else row.titles[:2]
                    text = "  ".join(
                        _cut(t, w).ljust(w)
                        for t, w in zip(titles, widths, strict=False)
                    )
                    drawn.append([("class:muted", f"{lead}{text}".rstrip())])
                case Item():
                    if index == self.cursor and not self.writing:
                        cursor_line = len(drawn)
                    drawn.extend(self._item_lines(index, row, table, width, wrapped))

        height = max(height, 3)
        if len(drawn) > height:
            start = min(max(cursor_line - height // 2, 0), len(drawn) - height)
            end = start + height
            above, below = start, len(drawn) - end
            shown = drawn[start:end]
            if above:
                shown[0] = [("class:muted", f"  ↑ {above + 1} more")]
            if below:
                shown[-1] = [("class:muted", f"  ↓ {below + 1} more")]
            drawn = shown

        fragments: StyleAndTextTuples = []
        for number, line in enumerate(drawn):
            if number:
                fragments.append(("", "\n"))
            fragments.extend(line)
        return fragments

    def _item_lines(
        self,
        index: int,
        item: Item[T],
        table: tuple[tuple[str, ...], list[int], bool],
        width: int,
        wrapped: Callable[[str, str, str], list[list[tuple[str, str]]]],
    ) -> list[list[tuple[str, str]]]:
        pad = "  " * item.indent
        mark = "› " if index == self.cursor and not self.writing else "  "
        box = ""
        if item.toggle is not None:
            box = "[x] " if index in self.on else "[ ] "
        style = (
            "class:muted"
            if not item.enabled
            else "class:cursor"
            if mark.strip()
            else ""
        )
        out: list[list[tuple[str, str]]] = []
        under = pad + "    " + ("    " if box else "")
        if item.cells:
            titles, widths, one_line = table
            cells = item.cells if one_line else item.cells[:2]
            text = "  ".join(
                _cut(c, w).ljust(w) for c, w in zip(cells, widths, strict=False)
            )
            out.append([(style, f"{pad}{mark}{box or '    '}{text}".rstrip())])
            if not one_line:
                rest = "  ".join(
                    f"{t}: {c}"
                    for t, c in zip(titles[2:], item.cells[2:], strict=False)
                )
                out.append([("class:muted", _cut(f"{pad}      {rest}", width - 1))])
        else:
            label = item.label
            if item.count and self.has_toggles:
                label = f"{label} ({len(self.on)} selected)"
            if not item.enabled:
                label = f"{label}   (unavailable)"
            out.append([(style, f"{pad}{mark}{box}{label}")])
        for line in item.lines:
            out.extend(wrapped(f"class:{line.tone}", line.text, under))
        for details in item.details:
            inset = under + "  " * details.indent
            if details.expanded:
                # An open group is part of the item: its title, then its text.
                out.append([("", f"{inset}{details.title}")])
                for line in details.lines:
                    out.extend(wrapped(f"class:{line.tone}", line.text, inset + "  "))
            elif index in self.open:
                out.append([("class:muted", f"{inset}▾ {details.title}")])
                for line in details.lines:
                    out.extend(wrapped(f"class:{line.tone}", line.text, inset + "  "))
            else:
                out.append([("class:muted", f"{inset}▸ {details.title}")])
        return out


class KeyPrompter:
    """Arrow keys, Space, Enter, and Esc, with a grey hint line under each question.

    Tests give `input` and `output` (a pipe input and a dummy output). A real run uses the
    terminal.
    """

    def __init__(
        self, *, input: Input | None = None, output: Output | None = None
    ) -> None:
        self._input = input
        self._output = output

    def _run(
        self,
        body: Any,
        hint: Callable[[], str],
        bindings: KeyBindings,
        done: Callable[[], StyleAndTextTuples] | None = None,
        focus: Any = None,
    ) -> Any:
        from prompt_toolkit.application import Application
        from prompt_toolkit.filters import is_done
        from prompt_toolkit.key_binding import merge_key_bindings
        from prompt_toolkit.layout import (
            ConditionalContainer,
            FormattedTextControl,
            HSplit,
            Layout,
            Window,
        )
        from prompt_toolkit.styles import Style

        # A picker swaps its rows for one answer line when it is done. A text line stays as
        # typed, so it is its own answer line.
        containers: list[Any] = [body]
        if done is not None:
            containers = [
                ConditionalContainer(body, filter=~is_done),
                ConditionalContainer(
                    Window(FormattedTextControl(done), dont_extend_height=True),
                    filter=is_done,
                ),
            ]
        containers.append(
            ConditionalContainer(
                Window(
                    FormattedTextControl(lambda: [("class:hint", hint())]),
                    height=1,
                ),
                filter=~is_done,
            )
        )
        common = _common_bindings()
        app: Application[Any] = Application(
            layout=Layout(HSplit(containers), focused_element=focus),
            key_bindings=merge_key_bindings([common, bindings]),
            style=Style.from_dict(_STYLE),
            full_screen=False,
            input=self._input,
            output=self._output,
        )
        # Esc is also the first byte of an arrow key. A short wait keeps Esc fast.
        app.ttimeoutlen = 0.05
        app.timeoutlen = 0.05
        return app.run()

    def pick(
        self,
        rows: Sequence[Row[T]],
        *,
        name: str | None = None,
        default: T | None = None,
        back: bool = False,
        title: str | None = None,
    ) -> Picked[T] | Nav:
        """Run a picker over action rows, toggle rows, and the text rows between them.

        Enter on an action row returns that row. Enter on a toggle row returns the toggles.
        The selected count has its own line under the rows.
        """
        from prompt_toolkit.application import get_app
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import FormattedTextControl, Window

        picker = _Picker(
            rows,
            default=default,
            back=back,
        )
        result: list[Picked[T] | Nav] = []
        bindings = KeyBindings()

        @bindings.add("up")
        def _up(_event: Any) -> None:
            picker.move(-1)

        @bindings.add("down")
        def _down(_event: Any) -> None:
            picker.move(1)

        @bindings.add(" ")
        def _space(_event: Any) -> None:
            picker.toggle()

        @bindings.add("enter")
        def _enter(event: Any) -> None:
            picked = picker.enter()
            if picked is not None:
                result.append(picked)
                event.app.exit(result=picked)

        if back:

            @bindings.add("escape", eager=True)
            def _back(event: Any) -> None:
                result.append(BACK)
                event.app.exit(result=BACK)

        def body() -> StyleAndTextTuples:
            size = get_app().output.get_size()
            height = size.rows - _RESERVED_ROWS - (1 if title else 0)
            lines = picker.lines(height, size.columns)
            if title:
                return [("", f"{title}\n"), *lines]
            return lines

        def done() -> StyleAndTextTuples:
            prefix = (
                "› "
                if not name
                else f"{name} "
                if name.endswith(("?", "."))
                else f"{name}: "
            )
            return [("class:muted", f"{prefix}{picker.summary(result[-1])}")]

        return self._run(
            Window(FormattedTextControl(body), dont_extend_height=True),
            picker.hint,
            bindings,
            done=done,
        )

    def review(self, review: Review[T], *, placeholder: str = "") -> Reviewed[T]:
        """Run a review until the user sends an action, the changed toggles, or feedback.

        The feedback line sits under the list, so the list stays on the screen while the user
        types. It shows only when the review accepts feedback.
        """
        from prompt_toolkit.application import get_app
        from prompt_toolkit.buffer import Buffer
        from prompt_toolkit.filters import Condition
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import (
            BufferControl,
            ConditionalContainer,
            FormattedTextControl,
            HSplit,
            Window,
        )
        from prompt_toolkit.layout.processors import (
            AfterInput,
            BeforeInput,
            ConditionalProcessor,
        )

        result: list[Reviewed[T]] = []
        bindings = KeyBindings()
        listing = Condition(lambda: not review.writing)
        writing = Condition(lambda: review.writing)

        def finish(event: Any, answer: Reviewed[T] | None) -> None:
            if answer is not None:
                result.append(answer)
                event.app.exit(result=answer)

        def accept(buffer: Buffer) -> bool:
            # A blank line sends nothing and keeps the focus on the feedback line.
            if buffer.text.strip():
                answer = Reviewed(feedback=buffer.text.strip())
                result.append(answer)
                get_app().exit(result=answer)
            return True

        buffer = Buffer(multiline=False, accept_handler=accept)
        line = BufferControl(
            buffer,
            focusable=True,
            input_processors=[
                BeforeInput("Feedback: "),
                ConditionalProcessor(
                    AfterInput(placeholder, style="class:muted"),
                    filter=Condition(lambda: not buffer.text),
                ),
            ],
        )
        lines = FormattedTextControl(
            lambda: review.lines(
                get_app().output.get_size().rows - _RESERVED_ROWS - 1,
                get_app().output.get_size().columns,
            ),
            focusable=True,
        )

        def focus(event: Any) -> None:
            review.write()
            event.app.layout.focus(line if review.writing else lines)

        bindings.add("up", filter=listing)(lambda _event: review.move(-1))
        bindings.add("down", filter=listing)(lambda _event: review.move(1))
        bindings.add(" ", filter=listing)(lambda _event: review.toggle())
        bindings.add("right", filter=listing)(lambda _event: review.right())
        bindings.add("left", filter=listing)(lambda _event: review.left())
        bindings.add("enter", filter=listing)(
            lambda event: finish(event, review.enter())
        )
        bindings.add("escape", eager=True, filter=listing)(
            lambda event: finish(event, review.escape())
        )
        bindings.add("tab")(focus)
        bindings.add("escape", eager=True, filter=writing)(focus)

        feedback_row = ConditionalContainer(
            Window(line, dont_extend_height=True, wrap_lines=True),
            filter=Condition(lambda: review.feedback),
        )
        body = HSplit(
            [Window(lines, dont_extend_height=True), feedback_row],
        )

        def done() -> StyleAndTextTuples:
            return [("class:muted", f"› {review.summary(result[-1])}")]

        return self._run(body, review.hint, bindings, done=done, focus=lines)

    def choose(
        self,
        choices: Sequence[Choice[T]],
        *,
        name: str,
        default: T | None = None,
        back: bool = False,
        typed: Typed | None = None,
        title: str | None = None,
    ) -> T | Nav:
        rows = [Choice(c.value, c.label, c.detail, c.enabled) for c in choices]
        picked = self.pick(rows, name=name, default=default, back=back, title=title)
        if isinstance(picked, Picked):
            assert picked.action is not None
            return picked.action
        return picked

    def choose_many(
        self, choices: Sequence[Choice[T]], *, name: str, back: bool = False
    ) -> list[T] | Nav:
        picked = self.pick(_with_headings(choices), name=name, back=back)
        return list(picked.on) if isinstance(picked, Picked) else picked

    def text(
        self,
        label: str,
        default: str = "",
        *,
        back: bool = False,
        placeholder: str = "",
    ) -> str | Nav:
        """Read one line. `placeholder` shows in grey while the line is empty."""
        from prompt_toolkit.application import get_app
        from prompt_toolkit.buffer import Buffer
        from prompt_toolkit.document import Document
        from prompt_toolkit.filters import Condition
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import BufferControl, Window
        from prompt_toolkit.layout.processors import (
            AfterInput,
            BeforeInput,
            ConditionalProcessor,
        )

        def accept(buffer: Buffer) -> bool:
            get_app().exit(result=buffer.text.strip())
            return True

        # The current value is already in the line, so Enter keeps it and the user can edit it.
        buffer = Buffer(
            document=Document(default, len(default)),
            multiline=False,
            accept_handler=accept,
        )
        bindings = KeyBindings()
        if back:

            @bindings.add("escape", eager=True)
            def _back(event: Any) -> None:
                event.app.exit(result=BACK)

        hint = _SEPARATOR.join([*(["Esc back"] if back else []), "Enter accept"])
        empty = Condition(lambda: not buffer.text)
        control = BufferControl(
            buffer,
            input_processors=[
                BeforeInput(f"{label}: "),
                ConditionalProcessor(
                    AfterInput(placeholder, style="class:muted"), filter=empty
                ),
            ],
        )
        return self._run(
            Window(control, dont_extend_height=True, wrap_lines=True),
            lambda: hint,
            bindings,
        )

    def confirm(self, label: str, default: bool, *, back: bool = False) -> bool | Nav:
        choices = [Choice(True, "Yes"), Choice(False, "No")]
        return self.choose(choices, name=label, default=default, back=back, title=label)


def _common_bindings() -> KeyBindings:
    from prompt_toolkit.key_binding import KeyBindings

    bindings = KeyBindings()

    @bindings.add("c-c")
    def _interrupt(event: Any) -> None:
        event.app.exit(exception=KeyboardInterrupt)

    @bindings.add("c-d")
    def _end(event: Any) -> None:
        event.app.exit(exception=EOFError)

    return bindings


# ── a sequence of questions ──────────────────────────────────────────────────


def _always(_answers: dict[str, Any]) -> bool:
    return True


@dataclass(frozen=True)
class Step:
    """One question in a sequence.

    `ask` gets the answers so far and whether Esc may go back, and returns a value or `BACK`.
    `applies` says whether the question is asked, from the answers so far.
    """

    name: str
    ask: Callable[[dict[str, Any], bool], Any]
    applies: Callable[[dict[str, Any]], bool] = _always


def walk(steps: Sequence[Step], answers: dict[str, Any], *, back: bool = False) -> bool:
    """Ask each step that applies, in order, and store its answer under its name.

    `BACK` on a step asks the step before it again, with the answer already given as the
    default. Returns `False` when the user goes back from the first step, which `back` allows.
    """

    def previous(index: int) -> int | None:
        for earlier in range(index - 1, -1, -1):
            if steps[earlier].applies(answers):
                return earlier
        return None

    index = 0
    while index < len(steps):
        step = steps[index]
        if not step.applies(answers):
            index += 1
            continue
        before = previous(index)
        value = step.ask(answers, back or before is not None)
        if value is BACK:
            if before is None:
                return False
            index = before
            continue
        answers[step.name] = value
        index += 1
    return True


__all__ = [
    "BACK",
    "Choice",
    "Details",
    "Divider",
    "Heading",
    "Item",
    "KeyPrompter",
    "Line",
    "Nav",
    "Note",
    "Picked",
    "Prompter",
    "Review",
    "ReviewRow",
    "Reviewed",
    "Row",
    "Step",
    "TableHeader",
    "TextPrompter",
    "Title",
    "Typed",
    "key_input_available",
    "walk",
]
