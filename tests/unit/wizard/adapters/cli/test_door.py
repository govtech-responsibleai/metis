"""The door: it draws what it is handed, and knows nothing about the domain."""

import inspect
import re

import pytest

from metis.wizard.adapters.cli import render as cli
from metis.wizard.contracts import (
    BehaviourCard,
    CardNumberField,
    CardOptionGroup,
    CardText,
    CardUploadField,
    ChatRequest,
    ChoiceRequest,
    Option,
    OptionId,
    ReviewSection,
    ScenarioCard,
    Warning,
)

DOMAIN_WORDS = [
    "behaviour",
    "criterion",
    "criteria",
    "feature",
    "persona",
    "scenario",
    "measured",
    "specification",
]


def a_screen(**overrides) -> ChoiceRequest:
    defaults = dict(
        prompt="Here's what I have.",
        multi=True,
        cards=[
            BehaviourCard(
                id="EB-1",
                section="Answer quality",
                section_id="F-1",
                title="Cites a source",
                selected=True,
                components=[CardText(text="Given x, when y, then z")],
                options=[
                    Option(
                        id=OptionId(action="tick", target="EB-1"),
                        label="Measure",
                        selected=True,
                    ),
                    Option(id=OptionId(action="chat", target="EB-1"), label="Chat"),
                ],
            ),
            ScenarioCard(
                id="S-1",
                title="Ask for a review",
                trials=6,
                components=[
                    CardOptionGroup(
                        label="Covers",
                        options=[
                            Option(
                                id=OptionId(action="cover", target="S-1", via="EB-1"),
                                label="Cites a source",
                                selected=True,
                            )
                        ],
                    ),
                    CardNumberField(
                        label="Trials",
                        id=OptionId(action="trials", target="S-1"),
                        value=3,
                    ),
                    CardUploadField(
                        label="Files",
                        id=OptionId(action="files", target="S-1"),
                        value="a.pdf",
                    ),
                ],
            ),
        ],
        warnings=[
            Warning(text="EB-4 is covered by no scenario.", blocking=True),
            Warning(text="EB-2 has no acceptance criteria yet.", blocking=False),
        ],
        sections=[
            ReviewSection(
                id="F-1",
                title="Answer quality",
                parent="behaviours",
                options=[
                    Option(
                        id=OptionId(action="add", target="F-1"),
                        label="Add one to Answer quality",
                        icon="plus",
                    )
                ],
            ),
            ReviewSection(
                id="empty",
                title="Nothing yet",
                options=[
                    Option(
                        id=OptionId(action="add", target="empty"),
                        label="Add the first one",
                        icon="plus",
                    )
                ],
            ),
        ],
        footer="Total: 9 trials",
        options=[
            Option(id=OptionId(action="back"), label="← Back"),
            Option(id=OptionId(action="continue"), label="Continue", enabled=False),
        ],
    )
    return ChoiceRequest(**{**defaults, **overrides})


def draw(request: ChoiceRequest) -> tuple[str, dict]:
    lines: list[str] = []
    selectable = cli._draw(request, lines.append)
    return "\n".join(lines), selectable


# ── the door knows nothing ─────────────────────────────────────────────────


def test_the_renderer_names_no_domain_concept() -> None:
    """It branches on request type and component shape, and on nothing else.

    The day the door needs to tell a behaviour card from a scenario card is the day it has
    started learning the domain.
    """
    source = inspect.getsource(cli)
    # strip docstrings and comments — those explain the contract, they do not branch on it
    code = re.sub(r'"""(?:.|\n)*?"""', "", source)
    code = re.sub(r"#.*", "", code)

    for word in DOMAIN_WORDS:
        assert word not in code.lower(), f"the door should not mention {word!r}"


def test_both_card_kinds_go_through_one_path() -> None:
    """A BehaviourCard and a ScenarioCard render through the same code."""
    text, _ = draw(a_screen())

    assert "Cites a source" in text
    assert "Ask for a review" in text
    assert "6 trials" in text


# ── every screen shape draws ───────────────────────────────────────────────


def test_selection_state_and_components_draw() -> None:
    """One authoritative check that a screen's pieces render as the layout intends.

    Covers the section heading, its count and underline, the item block (number, checkbox,
    title, id, indented text), the chip's target-without-verb tag, the stepper bounds,
    filenames, the `Actions:` line, and that a screen-level reply carries no `(target)`. Kept as one test because these are all one behaviour — "the
    door draws a screen" — not separate contracts.
    """
    text, selectable = draw(a_screen())
    section = "Answer quality"

    # The heading is finished text the door does not interpret, underlined to its own width so
    # a group stands apart from the items nested under it. Its selected count sits beside it.
    assert f"{section}   1 of 1 selected\n{'─' * len(section)}" in text

    # One item reads as one block: the number of its checkbox, the box, the title, its id, and
    # its text indented under it. The toggle is chosen by that number, not drawn again.
    assert "  2. [x] Cites a source  (EB-1)\n       Given x, when y, then z" in text
    assert selectable["tick:EB-1"].label == "Measure"
    assert "Measure" not in text

    # The chip shows the item it applies to, without the `cover` verb: the number selects and
    # the verb is machinery the user never types.
    assert "[x] Cites a source  (S-1:EB-1)" in text
    assert "(cover:" not in text

    assert "3   [1–20]" in text  # stepper with its bounds
    assert "a.pdf" in text  # filenames

    assert "← Back" in text and "(back)" not in text  # a reply applies to nothing

    # Icons are not drawn: icon actions sit on one `Actions:` line under their owner, and a
    # section with no cards still shows its heading and its actions.
    assert "  Actions: 1. Add one\n" in text
    assert "Nothing yet" in text and "Add the first one" in text


def test_a_checkbox_less_card_gets_a_bullet_and_indent() -> None:
    """A behaviour with no checkbox still reads as a list item under its section.

    A distinct fixture from the screen above (no `selected`), so it earns its own case: the
    bullet is what carries the list shape when there is no checkbox to do it.
    """
    text, _ = draw(a_screen(cards=[BehaviourCard(id="EB-9", title="Does a thing")]))

    assert "  • Does a thing" in text


def test_blocking_and_advisory_warnings_read_differently() -> None:
    text, _ = draw(a_screen())

    assert "STOP  EB-4 is covered by no scenario." in text
    assert "note  EB-2 has no acceptance criteria yet." in text


def test_a_disabled_option_is_shown_but_not_selectable() -> None:
    """Hiding it would leave the user wondering where Continue went."""
    text, selectable = draw(a_screen())

    assert "Continue   (unavailable)" in text
    assert "continue" not in selectable
    assert "back" in selectable


def test_warning_fixes_are_selectable() -> None:
    screen = a_screen(
        warnings=[
            Warning(
                text="EB-4 is covered by no scenario.",
                blocking=True,
                options=[
                    Option(
                        id=OptionId(action="cover", target="S-1", via="EB-4"),
                        label="add to S-1",
                    )
                ],
            )
        ]
    )
    text, selectable = draw(screen)

    assert "add to S-1" in text
    assert "cover:S-1:EB-4" in selectable


# ── the door enforces what it was told ─────────────────────────────────────


def test_a_single_select_screen_refuses_two() -> None:
    """Both keys are real and selectable — what is refused is sending them together.

    That is the rule that keeps a set of model-composed patches from being applied half-way:
    where two things can be clicked together, they cannot conflict.
    """
    replies = iter(["back, chat:EB-1", "back"])
    out: list[str] = []

    response = cli.render(
        a_screen(multi=False), out=out.append, read=lambda _: next(replies)
    )

    assert any("Just one" in line for line in out)
    assert response.selected == ["back"]


def test_a_multi_select_screen_accepts_several() -> None:
    screen = a_screen(multi=True)
    response = cli.render(screen, out=lambda _: None, read=lambda _: "back, chat:EB-1")

    assert set(response.selected) == {"back", "chat:EB-1"}


def _number(label: str, request: ChoiceRequest) -> str:
    """The number the door printed in front of `label`."""
    text, _ = draw(request)
    line = next(line for line in text.splitlines() if f". {label}" in line)
    return line.strip().split(".", 1)[0]


def test_numbered_choices_are_shown_and_selectable() -> None:
    prompts: list[str] = []
    number = _number("Chat", a_screen(multi=False))

    response = cli.render(
        a_screen(multi=False),
        out=lambda _: None,
        read=lambda prompt: prompts.append(prompt) or number,
    )

    assert response.selected == ["chat:EB-1"]
    assert "number or name" in prompts[0]


def test_a_number_field_is_selectable_and_reprompts_until_bounded() -> None:
    replies = iter(["trials:S-1", "0", "21", "8"])
    out: list[str] = []

    response = cli.render(a_screen(), out=out.append, read=lambda _: next(replies))

    assert response.values == {"trials:S-1": 8}
    assert sum("Enter an integer from 1 to 20." in line for line in out) == 2


def test_a_file_field_returns_a_normalized_list_and_blank_clears() -> None:
    replies = iter(["files:S-1", "  "])
    response = cli.render(a_screen(), out=lambda _: None, read=lambda _: next(replies))

    assert response.values == {"files:S-1": []}


def test_a_field_cannot_be_combined_with_an_option() -> None:
    replies = iter(["trials:S-1,back", "trials:S-1", "4"])
    out: list[str] = []

    response = cli.render(a_screen(), out=out.append, read=lambda _: next(replies))

    assert response.values == {"trials:S-1": 4}
    assert any("Edit one field at a time" in line for line in out)


def test_multi_select_accepts_comma_separated_numbers() -> None:
    numbers = f"{_number('Chat', a_screen())},{_number('← Back', a_screen())}"
    response = cli.render(
        a_screen(multi=True), out=lambda _: None, read=lambda _: numbers
    )

    assert response.selected == ["chat:EB-1", "back"]


def test_an_unknown_key_is_refused() -> None:
    replies = iter(["nonsense", "back"])
    out: list[str] = []

    cli.render(a_screen(), out=out.append, read=lambda _: next(replies))

    assert any("only accepts one of the menu choices" in line for line in out)


def test_a_choice_screen_explains_how_to_leave_comments() -> None:
    text, _ = draw(
        a_screen(
            instruction=(
                'To leave comments, choose "Chat about it" first; '
                "the next prompt accepts text."
            )
        )
    )

    assert 'choose "Chat about it" first' in text


def test_stepper_bounds_are_checked_without_the_package() -> None:
    assert cli.number_within(3, 1, 20)
    assert not cli.number_within(0, 1, 20)
    assert not cli.number_within(21, 1, 20)


def test_chat_and_form_return_their_matching_response() -> None:
    from metis.wizard.contracts import FormField, FormRequest

    chat = cli.render(
        ChatRequest(prompt="What would you change?"),
        out=lambda _: None,
        read=lambda _: "make it shorter",
    )
    assert chat.text == "make it shorter"

    form = cli.render(
        FormRequest(
            prompt="Type it", fields=[FormField(id="description", label="Words")]
        ),
        out=lambda _: None,
        read=lambda _: "typed by hand",
    )
    assert form.values == {"description": "typed by hand"}


def test_chat_reprompts_instead_of_submitting_a_blank_answer() -> None:
    replies = iter(["", "   ", "an actual answer"])
    prompts: list[str] = []
    out: list[str] = []

    response = cli.render(
        ChatRequest(prompt="Tell me more"),
        out=out.append,
        read=lambda prompt: prompts.append(prompt) or next(replies),
    )

    assert response.text == "an actual answer"
    assert prompts == ["> ", "> ", "> "]
    assert out.count("  Please enter a response.") == 2


def test_multiline_chat_preserves_blank_lines_until_done() -> None:
    replies = iter(
        [
            "The data analyst should produce useful charts.",
            "",
            "The slide deck should remain grounded in the data.",
            ".done",
        ]
    )

    response = cli.render(
        ChatRequest(prompt="What should change?", multiline=True),
        out=lambda _: None,
        read=lambda _: next(replies),
    )

    assert response.text == (
        "The data analyst should produce useful charts.\n\n"
        "The slide deck should remain grounded in the data."
    )


@pytest.mark.parametrize(
    "selected,expected", [(True, "[x] "), (False, "[ ] "), (None, "")]
)
def test_checkbox_states(selected, expected) -> None:
    assert cli._checkbox(selected) == expected


# ── the header and divider ─────────────────────────────────────────────────


def test_a_stamped_screen_draws_its_header_and_divider_pipe_safely() -> None:
    """A stamped screen shows its panel and a card/reply divider, with no escapes captured.

    One test for "the chrome renders": the header carries title and `step N of M`, a screen
    with cards draws a rule between them and the replies, and — the boundary that matters for
    a redirected run — a captured console emits no ANSI control sequences.
    """
    out: list[str] = []

    cli.render(
        a_screen(title="Behaviours", step=2, steps=6),
        out=out.append,
        read=lambda _: "back",
    )
    text = "\n".join(out)

    assert "Behaviours" in text
    assert "step 2 of 6" in text
    assert "─" in text  # Rich draws the rule; the door composes no such glyph itself
    assert "\x1b[" not in text  # nothing leaked into the transcript


@pytest.mark.parametrize(
    ("kwargs", "absent"),
    [
        ({}, "step"),  # an unstamped request draws no header — old interviews, web door
        ({"cards": []}, "─"),  # a screen with no cards has no two regions to divide
    ],
)
def test_chrome_is_omitted_when_there_is_nothing_to_draw(kwargs, absent) -> None:
    text, _ = draw(a_screen(**kwargs))

    assert absent not in text


def test_the_header_is_drawn_once_and_only_when_the_step_changes() -> None:
    """The two ways the panel is *not* repeated, which is the whole point of the metadata.

    A re-prompt on a bad entry stays in the choice loop and never redraws the panel; and the
    run loop passes `show_header=False` for a further screen of the same step (several clarify
    questions, a mid-step form), so the prompt shows with no header above it.
    """
    replies = iter(["nonsense", "back"])
    out: list[str] = []
    cli.render(
        a_screen(title="Scenarios", step=6, steps=6),
        out=out.append,
        read=lambda _: next(replies),
    )
    text = "\n".join(out)
    assert text.count("step 6 of 6") == 1  # not redrawn on the correction
    assert any("only accepts one of the menu choices" in line for line in out)

    suppressed: list[str] = []
    cli.render(
        a_screen(title="Behaviours", step=2, steps=6),
        out=suppressed.append,
        read=lambda _: "back",
        show_header=False,
    )
    body = "\n".join(suppressed)
    assert "step 2 of 6" not in body and "Behaviours" not in body
    assert body.lstrip().startswith(a_screen().prompt)


def test_a_confirm_option_asks_first_and_a_dropdown_sends_the_value() -> None:
    from metis.wizard.contracts import FormChoice, FormField, FormRequest
    from metis.wizard.domain.permissions import InterviewStep

    screen = a_screen(
        multi=False,
        options=[
            Option(
                id=OptionId(action="remove", target="EB-1"),
                label="Delete Cites a source",
                icon="trash",
                confirm="Delete Cites a source? This also deletes 2 Criteria.",
            )
        ],
    )
    replies = iter(["remove:EB-1", "n", "remove:EB-1", "y"])
    out: list[str] = []
    response = cli.render(screen, out=out.append, read=lambda _: next(replies))
    assert response.selected == ["remove:EB-1"]
    assert sum("This also deletes 2 Criteria." in line for line in out) == 2
    assert any("Nothing was changed." in line for line in out)

    form = FormRequest(
        prompt="Pair them.",
        stage=InterviewStep.SCENARIOS,
        fields=[
            FormField(
                id="persona",
                label="Persona",
                choices=[
                    FormChoice(value="P-1", label="Careful reviewer"),
                    FormChoice(value="P-2", label="Impatient executive"),
                ],
            )
        ],
    )
    out = []
    replies = iter(["7", "/help", "2"])  # only a listed number is a value
    response = cli.render(form, out=out.append, read=lambda _: next(replies))
    assert response.values == {"persona": "P-2"}
    assert "  2. Impatient executive" in out
    # Back is offered in any form after the first step, and closes it.
    back = cli.render(form, out=lambda _: None, read=lambda _: "/back")
    assert back.selected == ["back"]


def test_a_multiple_choice_field_takes_listed_numbers_and_shows_hints() -> None:
    from metis.wizard.contracts import FormChoice, FormField, FormRequest

    form = FormRequest(
        prompt="Edit it.",
        fields=[
            FormField(
                id="behaviours",
                label="Behaviours",
                multiple=True,
                required=True,
                value="EB-1",
                choices=[
                    FormChoice(value="EB-1", label="EB-1", hint="Cites sources"),
                    FormChoice(value="EB-2", label="EB-2", hint="Keeps it short"),
                ],
            ),
            FormField(id="files", label="Files", multiple=True, value="a.pdf"),
        ],
    )
    out: list[str] = []
    replies = iter(["1,9", "2,1,2", "-"])
    response = cli.render(form, out=out.append, read=lambda _: next(replies))
    assert response.values == {"behaviours": "EB-2,EB-1", "files": ""}
    assert "  2. EB-2 — Keeps it short" in out
    assert "  (none available)" in out


def test_a_form_asks_again_for_a_required_field_and_clears_an_optional_one() -> None:
    """Enter keeps the current value. A required field is asked again until it has text, so
    the package never refuses the answer. "-" clears an optional field."""
    from metis.wizard.contracts import FormField, FormRequest

    form = FormRequest(
        prompt="Edit it.",
        fields=[
            FormField(id="name", label="Name", required=True),
            FormField(id="note", label="Note", value="old"),
            FormField(id="tag", label="Tag", value="kept"),
        ],
    )
    out: list[str] = []
    replies = iter(["", " ", "New name", "-", ""])
    response = cli.render(form, out=out.append, read=lambda _: next(replies))
    assert response.values == {"name": "New name", "note": "", "tag": "kept"}
    assert out.count("  This field is required.") == 2


def test_cancellable_form_returns_without_sending_draft_values() -> None:
    from metis.wizard.contracts import FormField, FormRequest

    replies = iter(["Draft name", "/cancel"])
    response = cli.render(
        FormRequest(
            prompt="Write a check",
            cancellable=True,
            fields=[
                FormField(id="name", label="Name"),
                FormField(id="description", label="Assessment"),
            ],
        ),
        out=lambda _: None,
        read=lambda _: next(replies),
    )
    assert response.cancelled
    assert response.values == {}


@pytest.mark.parametrize("screen", ["behaviours_screen", "personas_screen"])
def test_back_is_a_numbered_choice_on_each_review_screen(screen: str) -> None:
    from metis.wizard.application import screens
    from tests.fixtures.wizard.specifications import research_assistant

    request = getattr(screens, screen)(research_assistant(), "Review this.")
    text, selectable = draw(request)

    assert "back" in selectable
    assert re.search(r"\d+\. ← Back", text)
