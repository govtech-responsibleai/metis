"""The CLI door.

Nothing in this file names a behaviour, a criterion, a feature, a persona or a step. It
branches on request type and on `CardComponentType` — a stepper is not a chip row — and on
nothing else. A web door replaces the prints with components and is otherwise the same
function.

Every string displayed here arrived as finished text. The door adds punctuation and layout;
it never composes a sentence about the domain.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from metis.wizard.application.trials import format_trials
from metis.wizard.contracts.conversation import (
    AnyCardComponent,
    AnyRequest,
    AnyResponse,
    Card,
    CardComponentType,
    CardDetails,
    CardNumberField,
    CardUploadField,
    ChatRequest,
    ChatResponse,
    ChoiceRequest,
    ChoiceResponse,
    FormField,
    FormRequest,
    FormResponse,
    Option,
    ReviewSection,
    Warning,
    card_components,
)

if TYPE_CHECKING:
    from metis.wizard.adapters.cli.keys import (
        Choice,
        Details,
        Item,
        KeyPrompter,
        Line,
        ReviewRow,
    )

Printer = Callable[[str], None]
Reader = Callable[[str], str]


def _header(request: AnyRequest, out: Printer) -> None:
    """Draw the step header, if the request carries one.

    The title and position are finished values the package stamped — the door formats them
    into a panel and composes no sentence about the domain. A request with no metadata (an
    older interview, or any unstamped request) draws nothing, so the body renders exactly as it
    did before this change.

    The panel is rendered to text through `out` rather than printed straight to a terminal,
    so a test that injects `out` still captures it and a redirected run degrades cleanly:
    a captured Rich console detects it is not a terminal and emits no control sequences. The
    console sizes the panel to the terminal rather than a fixed width.
    """
    if request.title is None and request.step is None:
        return

    from rich.console import Console
    from rich.panel import Panel

    position = (
        f"step {request.step} of {request.steps}"
        if request.step is not None and request.steps is not None
        else None
    )

    console = Console()
    with console.capture() as capture:
        console.print(Panel(request.title or "", subtitle=position))
    out(capture.get().rstrip("\n"))


def _divider(out: Printer) -> None:
    """Separate the per-card choices above from the interview choices below.

    Drawn only when a screen has cards — a screen that is nothing but replies has no two
    regions to hold apart.
    """
    from rich.console import Console
    from rich.rule import Rule

    console = Console()
    with console.capture() as capture:
        console.print(Rule())
    out(capture.get().rstrip("\n"))


def _checkbox(selected: bool | None) -> str:
    if selected is None:
        return ""
    return "[x] " if selected else "[ ] "


def _styled(text: str, code: str) -> str:
    """Bold or dim text on a terminal, plain text everywhere else.

    The layout alone must be clear, so a redirected run or a test reads the same lines with
    no control sequences. `NO_COLOR` turns the style off, as most terminal tools allow.
    """
    import os
    import sys

    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return text
    return f"\x1b[{code}m{text}\x1b[0m"


def _bold(text: str) -> str:
    return _styled(text, "1")


def _dim(text: str) -> str:
    return _styled(text, "2")


def _wrapped(text: str, indent: str, out: Printer) -> None:
    """Wrap long text under its title, so it does not run back to the left margin."""
    import shutil
    import textwrap

    width = max(60, shutil.get_terminal_size((100, 24)).columns - 2)
    for paragraph in text.splitlines() or [""]:
        out(
            textwrap.fill(
                paragraph,
                width=width,
                initial_indent=indent,
                subsequent_indent=indent,
            )
            or indent.rstrip()
        )


def _ref(option: Option) -> str:
    """The item a choice applies to, without the action verb.

    Displayed beside a choice so a user can see *which* item a choice applies to. The verb
    (`tick`, `cover`) is machinery the user never types — the number selects — so it is
    dropped from the display. Selection still keys on the full `str(option.id)`, so a typed
    key like `tick:EB-6` keeps working. A screen-level reply (`continue`, `back`) has no
    target and shows nothing.
    """
    return ":".join(p for p in (option.id.target, option.id.via) if p)


def _number(option: Option, selectable: dict[str, Option]) -> int:
    """Register an enabled choice and return its stable number."""
    key = str(option.id)
    if key not in selectable:
        selectable[key] = option
    return list(selectable).index(key) + 1


def _choice_line(
    option: Option,
    selectable: dict[str, Option],
    *,
    indent: str,
    mark: str = "",
) -> str:
    """Register an enabled choice and draw its stable number plus the item it applies to."""
    suffix = "" if option.enabled else "   (unavailable)"
    if not option.enabled:
        return f"{indent}— {mark}{option.label}{suffix}"

    number = _number(option, selectable)
    ref = _ref(option)
    tag = f"  ({ref})" if ref else ""
    # The terminal has no hover, so a hint is drawn after the label.
    hint = f" — {option.hint}" if option.hint else ""
    return f"{indent}{number}. {mark}{option.label}{hint}{tag}{suffix}"


def _short_label(option: Option, owner: str) -> str:
    """An icon action drawn beside the item it acts on does not repeat that item's name.

    "Edit Cites a source" under "Cites a source" reads as "Edit". The package label is
    unchanged where the action stands alone, so a full label still reaches the user there.
    """
    label = option.label
    if owner and label.endswith(owner) and len(label) > len(owner):
        label = label[: -len(owner)].rstrip()
        for joiner in (" to", " from", " in"):
            if label.endswith(joiner):
                label = label[: -len(joiner)]
    return label


def _actions_line(
    options: list[Option], owner: str, selectable: dict[str, Option], indent: str
) -> str:
    """Draw the actions of one item on one line: `Actions: 5. Edit   6. Delete`."""
    parts = []
    for option in options:
        label = _short_label(option, owner)
        if option.enabled:
            parts.append(f"{_number(option, selectable)}. {label}")
        else:
            parts.append(_dim(f"{label} (unavailable)"))
    return f"{indent}{_dim('Actions:')} " + "   ".join(parts)


def _toggle_of(options: list[Option]) -> Option | None:
    """The option that the item's checkbox stands for, if the item has one."""
    return next((option for option in options if option.selected is not None), None)


def _draw_components(
    components: list[AnyCardComponent],
    out: Printer,
    selectable: dict[str, Option],
    editable: dict[str, CardNumberField | CardUploadField] | None,
    field_numbers: dict[str, int] | None,
    *,
    indent: str,
    owner: str,
    trials: int | None = None,
    labels: bool = True,
) -> None:
    for component in components:
        match component.type:
            case CardComponentType.TEXT:
                if component.label:
                    _wrapped(f"{component.label}: {component.text}", indent, out)
                else:
                    _wrapped(component.text, indent, out)
            case CardComponentType.DETAILS:
                if component.expanded:
                    # An open group is a sub-item: its title, then its parts under it.
                    out("")
                    out(f"{indent}• {_bold(component.title)}")
                    _draw_components(
                        component.components,
                        out,
                        selectable,
                        editable,
                        field_numbers,
                        indent=indent + "  ",
                        owner=component.title,
                    )
                else:
                    # A closed group is supporting detail, as on the web: one quiet title line.
                    out(_dim(f"{indent}{component.title}"))
            case CardComponentType.DIVIDER:
                out("")
            case CardComponentType.OPTIONS:
                if component.options and all(o.icon for o in component.options):
                    out(_actions_line(component.options, owner, selectable, indent))
                    continue
                if labels and component.label:
                    out(f"{indent}{component.label}")
                for option in component.options:
                    mark = _checkbox(option.selected)  # a plain button has no box
                    out(
                        _choice_line(
                            option, selectable, indent=indent + "  ", mark=mark
                        )
                    )
            case CardComponentType.NUMBER:
                key = str(component.id)
                if editable is not None:
                    editable[key] = component
                number = (
                    f"{field_numbers[key]}. "
                    if field_numbers is not None and key in field_numbers
                    else ""
                )
                if labels and component.label:
                    out(f"{indent}{component.label}")
                out(
                    f"{indent}  {number}({component.id}) {component.value}   "
                    f"[{component.min}–{component.max}]"
                )
                if trials is not None:
                    out(f"{indent}  {format_trials(trials)}")
            case CardComponentType.UPLOAD:
                key = str(component.id)
                if editable is not None:
                    editable[key] = component
                number = (
                    f"{field_numbers[key]}. "
                    if field_numbers is not None and key in field_numbers
                    else ""
                )
                if labels and component.label:
                    out(f"{indent}{component.label}")
                out(
                    f"{indent}  {number}({component.id}) {', '.join(component.value) or '—'}"
                )


def _draw_card(
    card: Card,
    out: Printer,
    selectable: dict[str, Option],
    editable: dict[str, CardNumberField | CardUploadField] | None = None,
    field_numbers: dict[str, int] | None = None,
) -> None:
    # One item reads as: a title line (number, checkbox, bold name, id), its text indented
    # under it, then one line of actions. The toggle behind the checkbox is selected by the
    # number on the title line, so it is not drawn again as its own choice.
    toggle = _toggle_of(card.options)
    box = _checkbox(card.selected)
    if toggle is not None and toggle.enabled:
        lead = f"{_number(toggle, selectable)}. {box}"
    else:
        lead = box or "• "
    tag = _dim(f"  ({card.id})") if card.show_id and card.id != card.title else ""
    out(f"\n  {lead}{_bold(card.title)}{tag}")
    body = "       " if toggle is not None and toggle.enabled else "      "

    # A column is drawn once: its summary when it has nothing to edit, else its title and the
    # controls that edit it, so a value is not shown twice.
    for column in card.columns:
        if not column.components:
            out(f"{body}{column.title}: {column.summary}")
            continue
        out(f"{body}{column.title}")
        _draw_components(
            column.components,
            out,
            selectable,
            editable,
            field_numbers,
            indent=body,
            owner=card.title,
            labels=False,
        )
    components = list(card.components)
    # The item's own text, note and actions come first, then its open sub-items, so an action
    # line always sits under the item it acts on.
    own = [
        c
        for c in components
        if not (c.type is CardComponentType.DETAILS and c.expanded)
    ]
    nested = [c for c in components if c not in own]

    def draw(group: list[AnyCardComponent]) -> None:
        _draw_components(
            group,
            out,
            selectable,
            editable,
            field_numbers,
            indent=body,
            owner=card.title,
            trials=getattr(card, "trials", None),
        )

    draw(own)

    if card.note:
        out(_dim(f"{body}{card.note}"))
    actions = [option for option in card.options if option is not toggle]
    if actions and all(option.icon for option in actions):
        out(_actions_line(actions, card.title, selectable, body))
    else:
        for option in actions:
            out(_choice_line(option, selectable, indent=body))
    draw(nested)


def _option_keys(request: ChoiceRequest) -> list[str]:
    """Return enabled option keys in the same order the screen numbers them."""
    keys: list[str] = []

    def add(option: Option) -> None:
        key = str(option.id)
        if option.enabled and key not in keys:
            keys.append(key)

    for section in request.sections:
        for option in section.options:
            add(option)
    for card in request.cards:
        for component in card_components(card):
            for option in getattr(component, "options", []) or []:
                add(option)
        for option in card.options:
            add(option)
    for warning in request.warnings:
        for option in warning.options:
            add(option)
    for option in request.options:
        add(option)
    return keys


def _field_keys(request: ChoiceRequest) -> list[str]:
    keys: list[str] = []
    for card in request.cards:
        for component in card_components(card):
            # Only the value-bearing components carry an id; isinstance narrows to those so the
            # id access is type-safe as the component union grows (a divider, for one, has none).
            if isinstance(component, (CardNumberField, CardUploadField)):
                key = str(component.id)
                if key not in keys:
                    keys.append(key)
    return keys


def _warning_line(warning: Warning) -> str:
    """A warning as text: red for one that blocks, orange for advice.

    Rich renders the colour only to a terminal, so a redirected run gets plain text.
    """
    from rich.console import Console
    from rich.text import Text

    label = "STOP" if warning.blocking else "note"
    console = Console()
    with console.capture() as capture:
        console.print(
            Text(
                f"{label}  {warning.text}",
                style="red" if warning.blocking else "dark_orange",
            ),
            soft_wrap=True,
        )
    return capture.get().rstrip("\n")


def _draw(
    request: ChoiceRequest,
    out: Printer,
    editable: dict[str, CardNumberField | CardUploadField] | None = None,
) -> dict[str, Option]:
    """Draw a choice screen and return what may be selected."""
    selectable: dict[str, Option] = {}
    field_numbers = None
    if editable is not None:
        field_numbers = {
            key: len(_option_keys(request)) + index
            for index, key in enumerate(_field_keys(request), start=1)
        }

    # Headings come from `request.sections`, so a section with no cards still shows its
    # actions. A top-level heading is drawn before its first group or card; a group heading
    # is drawn above the cards that name it in `section_id`.
    tops = {
        section.id: section for section in request.sections if section.parent is None
    }
    groups = {section.id: section for section in request.sections if section.parent}
    drawn: set[str] = set()

    def heading(section: ReviewSection, rule: str) -> None:
        if section.id in drawn:
            return
        drawn.add(section.id)
        grouped = [item for item in request.cards if item.section_id == section.id]
        count = ""
        if section.parent and any(item.selected is not None for item in grouped):
            selected = sum(bool(item.selected) for item in grouped)
            count = _dim(f"   {selected} of {len(grouped)} selected")
        out(f"\n{_bold(section.title)}{count}")
        out(rule * len(section.title))
        if section.options and all(option.icon for option in section.options):
            out(_actions_line(section.options, section.title, selectable, "  "))
        else:
            for option in section.options:
                out(_choice_line(option, selectable, indent="  "))

    def open_top(top_id: str | None) -> None:
        if top_id in tops:
            heading(tops[top_id], "═")
            # Groups with no cards yet still show their actions, under their parent.
            for group in groups.values():
                if group.parent == top_id and not any(
                    card.section_id == group.id for card in request.cards
                ):
                    heading(group, "─")

    for card in request.cards:
        group = groups.get(card.section_id or "")
        open_top(group.parent if group else card.profile_section_id)
        if group is not None:
            heading(group, "─")
        _draw_card(card, out, selectable, editable, field_numbers)
    for top_id in tops:
        open_top(top_id)

    for warning in request.warnings:
        out(f"\n{_warning_line(warning)}")
        for option in warning.options:
            out(_choice_line(option, selectable, indent="      "))

    if request.footer:
        out(f"\n{request.footer}")
    if request.instruction:
        out(f"\n{request.instruction}")

    # A divider holds the per-card choices apart from the replies that advance the interview —
    # but only when there are cards to hold apart.
    if request.cards and request.options:
        _divider(out)

    if request.options:
        out("")
    for option in request.options:
        # A disabled option is still shown, marked unavailable — hiding it would leave the
        # user wondering where Continue went.
        out(_choice_line(option, selectable, indent="  "))

    return selectable


def _read_nonblank(read: Reader, out: Printer, prompt: str) -> str:
    """Keep the current text prompt active until the user supplies an answer."""
    while True:
        value = read(prompt).strip()
        if value:
            return value
        out("  Please enter a response.")


def _read_multiline(read: Reader, out: Printer) -> str:
    """Read comment lines until an explicit marker ends the response.

    The `.done` marker is this reader's own input mechanic — blank lines are content here, so
    Enter cannot submit — so the reader states it, not the package. A door with a Send button
    (the web door) never sees this line and shows only the package's neutral prompt.
    """
    out("  Enter or paste as many lines as you need, then type .done on a new line.")
    lines: list[str] = []
    while True:
        value = read("> " if not lines else "| ").rstrip()
        if value.strip().casefold() == ".done":
            if any(line.strip() for line in lines):
                return "\n".join(lines).strip()
            out("  Please enter a response.")
            continue
        # Blank lines are content here: pasted lists and YAML commonly use them between
        # entries, which is why submission needs an explicit marker rather than Enter.
        lines.append(value)


def _read_number_field(
    field: CardNumberField, key: str, read: Reader, out: Printer
) -> ChoiceResponse:
    while True:
        raw = read(f"{field.label or 'Value'} ({field.min}–{field.max})\n> ").strip()
        try:
            value = int(raw)
        except ValueError:
            out(f"  Enter an integer from {field.min} to {field.max}.")
            continue
        if not number_within(value, field.min, field.max):
            out(f"  Enter an integer from {field.min} to {field.max}.")
            continue
        return ChoiceResponse(values={key: value})


def _read_file_field(field: CardUploadField, key: str, read: Reader) -> ChoiceResponse:
    raw = read(f"{field.label or 'Names'} (comma-separated; blank clears)\n> ")
    if not raw.strip():
        values: list[str] = []
    else:
        values = []
        for item in raw.split(","):
            name = item.strip()
            if name not in values:
                values.append(name)
    return ChoiceResponse(values={key: values})


# Form commands. Each is typed alone in any field.
_CANCEL = "/cancel"
_BACK = "/back"
_CLEAR = "-"


def _read_form_choice(field: FormField, read: Reader, out: Printer) -> str:
    """Show a dropdown as a numbered list. Only listed numbers or a form command are accepted.

    A field with `multiple` takes several numbers, separated by commas, and sends the values
    as one comma-separated text. Enter keeps the current value.
    """
    current = set(field.value.split(",")) if field.multiple else {field.value}
    for index, choice in enumerate(field.choices, start=1):
        mark = "  (current)" if choice.value in current else ""
        hint = f" — {choice.hint}" if choice.hint else ""
        out(f"  {index}. {choice.label}{hint}{mark}")
    if not field.choices:
        out("  (none available)")
    prompt = f"{field.label}"
    if field.multiple:
        prompt += " (numbers separated by commas"
        prompt += f", {_CLEAR} for none)" if not field.required else ")"
    while True:
        raw = read(f"{prompt}\n> ").strip()
        if raw in (_CANCEL, _BACK):
            return raw
        if not raw and (field.value or not field.required):
            return field.value
        if field.multiple and raw == _CLEAR and not field.required:
            return ""
        parts = [part.strip() for part in raw.split(",")] if field.multiple else [raw]
        if parts and all(
            part.isdigit() and 1 <= int(part) <= len(field.choices) for part in parts
        ):
            return ",".join(
                dict.fromkeys(field.choices[int(part) - 1].value for part in parts)
            )
        out(f"  Enter a number from 1 to {len(field.choices)}.")


def _read_form_text(field: FormField, read: Reader, out: Printer) -> str:
    """Read one text field. Enter keeps the current value; "-" clears an optional field.

    A required field is asked again until it has text, so a blank answer never reaches the
    package, which refuses it.
    """
    prompt = f"{field.label}"
    if field.value:
        prompt += f" [{field.value}]"
    if field.placeholder:
        prompt += f" ({field.placeholder})"
    if field.value and not field.required:
        prompt += f" (enter {_CLEAR} to clear)"
    while True:
        raw = read(f"{prompt}\n> ").strip()
        if raw in (_CANCEL, _BACK):
            return raw
        if raw == _CLEAR and not field.required:
            return ""
        value = raw or field.value
        if value.strip() or not field.required:
            return value
        out("  This field is required.")


def _read_form_pairs(field: FormField, read: Reader, out: Printer) -> str:
    """Read a list of labelled details, one detail per answer, as `name: value`.

    Enter on an empty line keeps the current details; "-" clears them. The value goes back as
    the JSON list that the field carries, so the package reads one shape from every door.
    """
    import json

    current = [tuple(row) for row in json.loads(field.value or "[]")]
    out(f"{field.label}")
    for name, value in current:
        out(f"  {name}: {value}")
    if field.help:
        out(f"  {field.help}")
    out("  Enter one detail per line as name: value. Enter a blank line to finish.")
    if current:
        out(f"  Enter {_CLEAR} to remove them all.")
    rows: list[list[str]] = []
    while True:
        raw = read("> ").strip()
        if raw in (_CANCEL, _BACK):
            return raw
        if raw == _CLEAR:
            return "[]"
        if not raw:
            break
        name, sep, value = raw.partition(":")
        if not sep or not name.strip():
            out("  Write the name of the detail, a colon, then its value.")
            continue
        rows.append([name.strip(), value.strip()])
    return json.dumps(rows) if rows else field.value or "[]"


def _read_form(request: FormRequest, read: Reader, out: Printer) -> AnyResponse:
    can_go_back = request.stage is not None and request.stage != "clarify"
    if request.cancellable:
        out(f"Enter {_CANCEL} in any field to return without saving.")
    if can_go_back:
        # The package accepts Back while a form is open: it closes the form, then goes back.
        out(f"Enter {_BACK} in any field to close this form and go back.")
    values = {}
    for field in request.fields:
        if field.help:
            out(field.help)
        value = (
            _read_form_choice(field, read, out)
            if field.choices or field.multiple
            else _read_form_pairs(field, read, out)
            if field.input_type == "pairs"
            else _read_form_text(field, read, out)
        )
        if request.cancellable and value == _CANCEL:
            return FormResponse(cancelled=True)
        if can_go_back and value == _BACK:
            return ChoiceResponse(selected=["back"])
        values[field.id] = value
    return FormResponse(values=values)


def _confirmed(options: list[Option], read: Reader, out: Printer) -> bool:
    """Ask y/N for each option that asks the user to confirm before it is sent."""
    for option in options:
        if option.confirm:
            out(f"  {option.confirm}")
            if read("  Continue? [y/N] ").strip().casefold() not in ("y", "yes"):
                return False
    return True


def _discard_buffered_input(read: Reader) -> None:
    """Drop the rest of a mistaken multiline paste before showing the menu again."""
    if read is not input:
        return
    try:
        import sys
        import termios

        if sys.stdin.isatty():
            termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
    except (ImportError, AttributeError, OSError):
        # Non-POSIX and redirected input have no terminal queue to clear.
        return


# ── key mode ─────────────────────────────────────────────────────────────────
#
# In a terminal, a choice screen is one grouped list. Each item is one row. Space flips its
# checkbox here, Right opens its closed details, and Tab moves to the feedback line under it. The keys
# offer only select, details, feedback, Back, and Continue: the item actions (add, edit, delete,
# chips, and fields) stay in the text menu and the web, where a form fits them. The request
# decides everything: a row comes from a section, a card, a warning option, or a screen option,
# and a row with `columns` is a table row.


def _lines_of(
    components: list[AnyCardComponent], *, muted: bool
) -> tuple[list[Line], list[Details]]:
    """Split the components of a card into its text and its details. Options and fields are
    item actions, which the keys do not offer."""
    from metis.wizard.adapters.cli.keys import Details, Line

    lines: list[Line] = []
    details: list[Details] = []

    def text_of(component: AnyCardComponent, tone: bool) -> list[Line]:
        if component.type is not CardComponentType.TEXT:
            return []
        text = (
            f"{component.label}: {component.text}"
            if component.label
            else component.text
        )
        return [Line(text, "muted" if tone else "plain")]

    def walk(group: CardDetails, depth: int, quiet: bool) -> None:
        quiet = quiet or group.muted
        inner: list[Line] = []
        nested: list[CardDetails] = []
        for part in group.components:
            if isinstance(part, CardDetails):
                nested.append(part)
            else:
                inner.extend(text_of(part, quiet))
        details.append(Details(group.title, tuple(inner), group.expanded, depth))
        for part in nested:
            walk(part, depth + 1, quiet)

    for component in components:
        match component:
            case CardDetails():
                walk(component, 0, muted)
            case _:
                lines.extend(text_of(component, True))
    return lines, details


def _action(option: Option) -> Choice[str]:
    from metis.wizard.adapters.cli.keys import Choice

    mark = _checkbox(option.selected)
    return Choice(
        str(option.id),
        f"{mark}{option.label}",
        detail=option.hint or "",
        enabled=option.enabled,
    )


def _card_item(card: Card, indent: int) -> Item[str]:
    from metis.wizard.adapters.cli.keys import Item, Line

    toggle = _toggle_of(card.options)
    if toggle is not None and not toggle.enabled:
        toggle = None
    lines, details = _lines_of(list(card.components), muted=False)
    if card.note:
        lines.append(Line(card.note))
    label = card.title
    if card.show_id and card.id != card.title:
        label = f"{label}  ({card.id})"
    return Item(
        label,
        toggle=str(toggle.id) if toggle is not None else None,
        selected=bool(toggle.selected) if toggle is not None else False,
        lines=tuple(lines),
        details=tuple(details),
        cells=tuple(column.summary for column in card.columns),
        indent=indent,
    )


def _option_item(option: Option, *, indent: int = 0, count: bool = False) -> Item[str]:
    from metis.wizard.adapters.cli.keys import Item

    return Item(
        option.label,
        action=str(option.id),
        enabled=option.enabled,
        indent=indent,
        count=count,
    )


def _review_rows(request: ChoiceRequest) -> list[ReviewRow[str]]:
    """The screen as review rows, in the order of the text menu."""
    from metis.wizard.adapters.cli.keys import (
        Divider,
        Heading,
        Item,
        Note,
        TableHeader,
        Title,
    )

    rows: list[ReviewRow[str]] = []
    tops = {s.id: s for s in request.sections if s.parent is None}
    groups = {s.id: s for s in request.sections if s.parent}
    drawn: set[str] = set()

    def heading(section: ReviewSection, indent: int) -> None:
        if section.id in drawn:
            return
        drawn.add(section.id)
        rows.append(Heading(("  " * indent) + section.title))

    def open_top(top_id: str | None) -> None:
        if top_id in tops:
            heading(tops[top_id], 0)
            for group in groups.values():
                if group.parent == top_id and not any(
                    card.section_id == group.id for card in request.cards
                ):
                    heading(group, 1)

    for card in request.cards:
        group = groups.get(card.section_id or "")
        open_top(group.parent if group else card.profile_section_id)
        if group is not None:
            heading(group, 1)
        indent = 2 if group is not None else 1
        previous = rows[-1] if rows else None
        if card.columns and not (isinstance(previous, Item) and previous.cells):
            rows.append(TableHeader(tuple(column.title for column in card.columns)))
        rows.append(_card_item(card, indent))
    for top_id in tops:
        open_top(top_id)

    for warning in request.warnings:
        label = "STOP" if warning.blocking else "note"
        tone = "stop" if warning.blocking else "warning"
        rows.append(Note(f"{label}  {warning.text}", tone=tone))
        rows.extend(_option_item(o, indent=1) for o in warning.options)
    if request.footer:
        rows.append(Title(request.footer))
    if request.instruction:
        rows.append(Note(request.instruction))
    if rows and request.options:
        rows.append(Divider())
    rows.extend(_option_item(o, count=o.primary) for o in request.options)
    return rows


def _key_review(
    request: ChoiceRequest, prompter: KeyPrompter, out: Printer
) -> AnyResponse:
    """Read a choice screen with keys. Only the toggles that changed are sent, because each
    tick flips its current value in the package."""
    from metis.wizard.adapters.cli.keys import Review

    back = next(
        (str(o.id) for o in request.options if o.enabled and o.id.action == "back"),
        None,
    )
    # Enter on an item that has no action of its own sends Continue (the primary option).
    default = next(
        (str(o.id) for o in request.options if o.enabled and o.primary), None
    )
    review = Review(
        _review_rows(request),
        back=back,
        default=default,
        feedback=request.feedback_placeholder is not None,
    )
    answer = prompter.review(review, placeholder=request.feedback_placeholder or "")
    if answer.feedback is not None:
        return ChoiceResponse(feedback=answer.feedback)
    if answer.changed:
        return ChoiceResponse(selected=list(answer.changed))
    assert answer.action is not None
    return ChoiceResponse(selected=[answer.action])


def _free(
    field: FormField, values: dict[str, str], used: list[dict[str, str]], value: str
) -> bool:
    """False when this value would complete a combination that an item already uses."""
    for combination in used:
        if combination.get(field.id) != value:
            continue
        others = {k: v for k, v in combination.items() if k != field.id}
        if others and all(values.get(k) == v for k, v in others.items()):
            return False
    return True


def _key_form(
    request: FormRequest, prompter: KeyPrompter, out: Printer, read: Reader
) -> AnyResponse:
    """Read a form with keys. Esc in a cancellable form returns without saving. In a form that
    offers Back, Esc on the first field goes back; Esc on a later field asks the one before."""
    from metis.wizard.adapters.cli.keys import BACK, Choice

    can_go_back = request.stage is not None and request.stage != "clarify"
    if request.cancellable:
        out("Press Esc to return without saving.")
    values: dict[str, str] = {}
    index = 0
    while index < len(request.fields):
        field = request.fields[index]
        escape = request.cancellable or can_go_back or index > 0
        if field.help:
            out(field.help)
        value: object
        if field.multiple and not field.choices:
            out(f"{field.label}: (none available)")
            value = field.value
        elif field.multiple:
            current = set(filter(None, field.value.split(",")))
            choices = [
                Choice(
                    c.value, c.label, detail=c.hint or "", selected=c.value in current
                )
                for c in field.choices
            ]
            out(field.label)
            value = prompter.choose_many(choices, name=field.label, back=escape)
            if value is not BACK:
                assert isinstance(value, list)
                if field.required and not value:
                    out("  Select at least one.")
                    continue
                value = ",".join(value)
        elif field.choices:
            choices = [
                Choice(
                    c.value,
                    c.label,
                    detail=c.hint or "",
                    enabled=_free(field, values, request.used_combinations, c.value),
                )
                for c in field.choices
            ]
            if not field.required:
                choices.append(Choice("", "None"))
            out(field.label)
            value = prompter.choose(
                choices, name=field.label, default=field.value, back=escape
            )
        elif field.input_type == "pairs":
            value = _read_form_pairs(field, read, out)
        else:
            value = prompter.text(
                field.label, field.value, back=escape, placeholder=field.placeholder
            )
            if value is not BACK and field.required and not str(value).strip():
                out("  This field is required.")
                continue
        if value is BACK:
            if request.cancellable:
                return FormResponse(cancelled=True)
            if index == 0:
                return ChoiceResponse(selected=["back"])
            index -= 1
            continue
        values[field.id] = str(value)
        index += 1
    return FormResponse(values=values)


def render(
    request: AnyRequest,
    *,
    out: Printer = print,
    read: Reader = input,
    show_header: bool = True,
    prompter: KeyPrompter | None = None,
) -> AnyResponse:
    """Draw a request, collect input, return the matching response.

    `show_header` lets the caller suppress the panel when this request is a further screen of
    the step already on the terminal — several clarify questions, or a mid-step form, all sit
    under one step and repeating "step 1 of 6" above each adds noise. The default is to draw
    it, so a web door or a test that renders one request in isolation is unaffected.
    """
    # The header is drawn once, above the prompt. The choice loop below re-prompts on a bad
    # entry without coming back through here, so a correction never redraws the panel.
    if show_header:
        _header(request, out)
    out(f"\n{request.prompt}")

    if isinstance(request, ChatRequest):
        if request.target_label:
            out(f"Changing: {request.target_label}")
        text = (
            _read_multiline(read, out)
            if request.multiline
            else _read_nonblank(read, out, "> ")
        )
        return ChatResponse(text=text)

    if isinstance(request, FormRequest):
        if prompter is not None:
            return _key_form(request, prompter, out, read)
        return _read_form(request, read, out)

    if prompter is not None:
        return _key_review(request, prompter, out)

    editable: dict[str, CardNumberField | CardUploadField] = {}
    selectable = _draw(request, out, editable)
    ordered_keys = [*selectable, *editable]
    numbers = {str(index): key for index, key in enumerate(ordered_keys, start=1)}

    while True:
        prompt = (
            "\nChoose one or more (comma-separated numbers or names): "
            if request.multi
            else "\nChoose one (number or name): "
        )
        if request.feedback_placeholder:
            out(f"  /feedback: {request.feedback_placeholder}")
        raw = read(prompt).strip()
        if request.feedback_placeholder and raw == "/feedback":
            return ChoiceResponse(feedback=_read_nonblank(read, out, "> "))
        entered = [k for k in (part.strip() for part in raw.split(",")) if k]
        keys = list(dict.fromkeys(numbers.get(key, key) for key in entered))

        known = set(ordered_keys)
        unknown = [key for key in entered if numbers.get(key, key) not in known]
        if unknown:
            out("  This screen only accepts one of the menu choices above.")
            if request.instruction:
                out(f"  {request.instruction}")
            _discard_buffered_input(read)
            continue
        # Enforced door-side because the package said so on the wire: options composed by
        # the model can contradict each other, so only one may be sent.
        if not request.multi and len(keys) > 1:
            out("  Just one of those, please.")
            continue
        if not keys:
            out("  Pick one.")
            continue

        field_keys = [key for key in keys if key in editable]
        if field_keys:
            if len(keys) != 1:
                out(
                    "  Edit one field at a time; do not combine it with another choice."
                )
                continue
            key = field_keys[0]
            field = editable[key]
            if isinstance(field, CardNumberField):
                return _read_number_field(field, key, read, out)
            return _read_file_field(field, key, read)

        if not _confirmed(
            [selectable[key] for key in keys if key in selectable], read, out
        ):
            out("  Nothing was changed.")
            continue
        return ChoiceResponse(selected=keys)


def number_within(value: int, low: int, high: int) -> bool:
    """Stepper bounds, checked without contacting the package."""
    return low <= value <= high
