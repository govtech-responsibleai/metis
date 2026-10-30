"""Key input in an interactive terminal: each key maps to something the screen already offers."""

from __future__ import annotations

import io
import re
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import pytest
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output.vt100 import Vt100_Output

from metis.wizard.adapters.cli import commands
from metis.wizard.adapters.cli import render as cli
from metis.wizard.adapters.cli.keys import KeyPrompter
from metis.wizard.adapters.cli.opening import read_capability_evidence
from metis.wizard.application import screens
from metis.wizard.contracts import (
    ChoiceResponse,
    FormChoice,
    FormField,
    FormRequest,
    FormResponse,
)
from metis.wizard.contracts.interview_state import CapabilityConfidence, Perspective
from metis.wizard.domain.permissions import InterviewStep
from metis.wizard.domain.specification import Behaviour
from tests.fixtures.wizard.specifications import research_assistant

UP, DOWN, LEFT, RIGHT = "\x1b[A", "\x1b[B", "\x1b[D", "\x1b[C"
ENTER, ESC, SPACE, TAB = "\r", "\x1b", " ", "\t"


@contextmanager
def keyboard(
    *questions: str, columns: int = 120, rows: int = 40
) -> Iterator[tuple[KeyPrompter, io.StringIO]]:
    """A KeyPrompter that gets the keys of one question each time a question starts."""
    screen = io.StringIO()
    output = Vt100_Output(
        screen, lambda: Size(rows=rows, columns=columns), term="xterm"
    )
    keys = iter(questions)
    with create_pipe_input() as pipe:
        attach = pipe.attach

        def start(callback):  # noqa: ANN001, ANN202
            attached = attach(callback)
            # A question with no keys left gets Ctrl-C, so a wrong key list fails the test
            # with KeyboardInterrupt and does not wait for ever.
            pipe.send_text(next(keys, "\x03"))
            return attached

        pipe.attach = start  # type: ignore[method-assign]
        yield KeyPrompter(input=pipe, output=output), screen


def plain(screen: io.StringIO) -> str:
    """What the terminal showed, one line for each run of text between control sequences."""
    text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "\n", screen.getvalue())
    return "\n".join(line for line in text.replace("\r", "").splitlines() if line)


def hints(screen: io.StringIO) -> list[str]:
    """The hint lines that the terminal showed, without colour codes."""
    starts = ("Esc ", "↑↓ move", "Enter ")
    return [
        line.strip() for line in plain(screen).splitlines() if line.startswith(starts)
    ]


def review(name: str):  # noqa: ANN201
    specification = research_assistant()
    build = {
        "behaviours": screens.behaviours_screen,
        "criteria": screens.criteria_screen,
        "test-cases": screens.task_review_screen,
    }[name]
    return build(specification, "Review.")


def answer(screen, *questions: str, typed: str = "", columns: int = 120):  # noqa: ANN001, ANN201
    with keyboard(*questions, columns=columns) as (prompter, drawn):
        response = cli.render(
            screen, out=lambda _: None, read=lambda _: typed, prompter=prompter
        )
    return response, plain(drawn)


# The cursor starts on the first item. Headings and text are not rows the cursor stops on. On
# Behaviours the items are EB-1, EB-2, EB-3, then Back and Continue; on Test Cases they are the
# Test Case rows, then Back and Continue.
@pytest.mark.parametrize(
    ("screen", "questions", "expected"),
    [
        # Space flips a tick here, and a second Space flips it back; Enter sends only the
        # tick that changed
        (
            "behaviours",
            [SPACE + SPACE + DOWN * 2 + SPACE + ENTER],
            ChoiceResponse(selected=["tick:EB-3"]),
        ),
        # Enter on an item with no pending change continues
        ("behaviours", [ENTER], ChoiceResponse(selected=["continue"])),
        ("behaviours", [ESC], ChoiceResponse(selected=["back"])),
        # Space includes a Test Case here; Enter sends the include alone
        ("test-cases", [SPACE + ENTER], ChoiceResponse(selected=["tick:TC-001"])),
        # Tab moves to the feedback line under the list; Enter sends what was typed
        (
            "behaviours",
            [TAB + "Make it shorter" + ENTER],
            ChoiceResponse(feedback="Make it shorter"),
        ),
        # Esc on the feedback line returns to the list, where Esc goes back
        ("behaviours", [TAB + "Mak" + ESC + ESC], ChoiceResponse(selected=["back"])),
        # a letter on the list does nothing, so typing never starts feedback by accident
        ("behaviours", ["M" + ENTER], ChoiceResponse(selected=["continue"])),
    ],
    ids=[
        "only-changed-ticks",
        "enter-continues",
        "esc-goes-back",
        "space-includes-test-case",
        "tab-sends-feedback",
        "esc-leaves-feedback",
        "letter-does-nothing",
    ],
)
def test_review_keys_map_to_the_screen_options(
    screen: str, questions: list[str], expected: ChoiceResponse
) -> None:
    response, _ = answer(review(screen), *questions)

    assert response == expected


def test_tab_moves_between_the_list_and_the_feedback_line() -> None:
    from metis.wizard.adapters.cli.keys import Review

    state = Review(
        cli._review_rows(review("behaviours")),
        back="back",
        default="continue",
        feedback=True,
    )
    state.write()

    # while the user writes, the list stays on the screen with no cursor on it
    drawn = "".join(text for _, text in state.lines(200, 120))
    assert "Cite factual claims" in drawn
    assert "›" not in drawn
    assert state.hint() == "Esc or Tab back to the list | Enter send feedback"
    state.write()
    assert "› [x] Cite factual claims" in "".join(
        text for _, text in state.lines(200, 120)
    )


def test_the_key_review_offers_no_item_actions() -> None:
    _, drawn = answer(review("behaviours"), ESC)

    # add, edit, delete and the other item actions stay in the text menu and the web
    for word in ("Edit ", "Delete ", "Add a Feature", "Add a Behaviour", "Actions:"):
        assert word not in drawn


def test_the_key_review_shows_each_item_once_in_its_group() -> None:
    specification = research_assistant()
    _, drawn = answer(review("behaviours"), ESC)

    lines = drawn.splitlines()
    for behaviour in specification.behaviours():
        assert sum(behaviour.name in line for line in lines) == 1
    # headings show no counts; the total is beside Continue
    assert "  Answer quality" in lines
    assert "  Continue (2 selected)" in lines


@pytest.mark.parametrize(
    ("columns", "expected"),
    [
        (
            120,
            [
                "        Persona                Scenario                     "
                "Behaviours  Trials  Files",
                "  › [x] Cooperative delegator  Supported literature review  "
                "EB-1        3       None",
            ],
        ),
        (
            70,
            [
                "        Persona                Scenario",
                "  › [x] Cooperative delegator  Supported literature review",
                "        Behaviours: EB-1  Trials: 3  Files: None",
            ],
        ),
    ],
    ids=["wide", "narrow"],
)
def test_test_cases_draw_as_a_table_that_fits_the_terminal(
    columns: int, expected: list[str]
) -> None:
    _, drawn = answer(review("test-cases"), ESC, columns=columns)

    lines = drawn.splitlines()
    start = lines.index(expected[0])
    assert lines[start : start + len(expected)] == expected


def test_right_opens_details_and_left_closes_them() -> None:
    from metis.wizard.adapters.cli.keys import Review

    state = Review(cli._review_rows(review("criteria")), back="back")

    def drawn() -> str:
        return "".join(text for _, text in state.lines(200, 120))

    assert "▸ Grader: FixedScoreGrader" in drawn()
    state.right()
    assert "▾ Grader: FixedScoreGrader" in drawn()
    assert "threshold: 0.5" in drawn()
    state.left()
    assert "threshold: 0.5" not in drawn()


@pytest.mark.parametrize(
    ("screen", "moves", "hint"),
    [
        (
            "behaviours",
            0,
            "Esc back | ↑↓ move | Space select | Enter Continue | Tab feedback",
        ),
        (
            "test-cases",
            0,
            "Esc back | ↑↓ move | Space select | Enter Continue | Tab feedback",
        ),
        (
            "criteria",
            0,
            "Esc back | ↑↓ move | → details | Enter Continue | Tab feedback",
        ),
    ],
    ids=["item-with-tick", "table-row", "item-with-details"],
)
def test_the_hint_lists_only_the_keys_of_the_highlighted_row(
    screen: str, moves: int, hint: str
) -> None:
    from metis.wizard.adapters.cli.keys import Review

    state = Review(
        cli._review_rows(review(screen)),
        back="back",
        default="continue",
        feedback=True,
    )
    state.move(moves)

    assert state.hint() == hint


@pytest.mark.parametrize("measured", [5, 6], ids=["at-the-suggestion", "too-many"])
def test_a_warning_that_does_not_block_is_orange_in_both_modes(
    monkeypatch: pytest.MonkeyPatch, measured: int
) -> None:
    specification = research_assistant()
    specification.features[0].behaviours.extend(
        Behaviour(id=f"EB-{n}", name=f"B{n}", description="d") for n in range(4, 7)
    )
    for index, behaviour in enumerate(specification.behaviours()):
        behaviour.measured = index < measured
    screen = screens.behaviours_screen(specification, "Review.")
    warned = measured > 5

    with keyboard(ESC) as (prompter, drawn):
        cli.render(screen, out=lambda _: None, prompter=prompter)
    # 208 is the 256-colour code of #ff8700
    assert ("38;5;208mnote  You selected" in drawn.getvalue()) is warned

    monkeypatch.setenv("FORCE_COLOR", "1")
    out: list[str] = []
    cli.render(screen, out=out.append, read=lambda _: "back")
    assert ("\x1b[38;5;208mnote  You selected" in "\n".join(out)) is warned


def a_pair_form(*, cancellable: bool) -> FormRequest:
    def choice(field: str, *values: str) -> FormField:
        return FormField(
            id=field,
            label=field.title(),
            choices=[FormChoice(value=v, label=v) for v in values],
            required=True,
        )

    return FormRequest(
        prompt="Pair them.",
        stage=InterviewStep.TEST_CASES,
        cancellable=cancellable,
        fields=[choice("persona", "P-1", "P-2"), choice("scenario", "S-1", "S-2")],
        used_combinations=[{"persona": "P-1", "scenario": "S-1"}],
    )


@pytest.mark.parametrize(
    ("cancellable", "questions", "expected"),
    [
        # P-1 with S-1 is in use, so the scenario cursor starts on S-2
        (
            True,
            [ENTER, ENTER],
            FormResponse(values={"persona": "P-1", "scenario": "S-2"}),
        ),
        (
            True,
            [ENTER, UP + ENTER],
            FormResponse(values={"persona": "P-1", "scenario": "S-2"}),
        ),
        (
            True,
            [DOWN + ENTER, ENTER],
            FormResponse(values={"persona": "P-2", "scenario": "S-1"}),
        ),
        (True, [ENTER, ESC], FormResponse(cancelled=True)),
        # a form that offers Back: Esc on a later field asks the field before, and Esc on
        # the first field goes back
        (False, [ENTER, ESC, ESC], ChoiceResponse(selected=["back"])),
    ],
    ids=[
        "used-pair-skipped",
        "used-pair-unavailable",
        "free-pair",
        "esc-cancels",
        "esc-back",
    ],
)
def test_a_form_reads_choices_with_keys(
    cancellable: bool, questions: list[str], expected: object
) -> None:
    with keyboard(*questions) as (prompter, _):
        response = cli.render(
            a_pair_form(cancellable=cancellable), out=lambda _: None, prompter=prompter
        )

    assert response == expected


def test_esc_goes_back_through_the_opening_questions_and_keeps_the_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from metis.wizard.application import connection as connection_module

    monkeypatch.setattr(
        connection_module,
        "_default_client",
        lambda _tls: httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, text="<html></html>")
            )
        ),
    )
    questions = [
        DOWN + ENTER,  # Perspective: Engineer
        ESC,  # mode: back to the Perspective
        ENTER,  # Perspective: Engineer is kept
        DOWN + ENTER,  # mode: Build Spec and Run Evals
        ENTER,  # binding: fill in the fields
        DOWN + ENTER,  # transport: Browser
        "Policy assistant" + ENTER,  # target name
        ESC,  # start page URL: back to the target name
        ESC,  # target name: back to the transport
        ESC,  # transport: back to the binding source
        ESC,  # binding source: back to the mode
        ENTER,  # mode: the run answer is kept
        ENTER,  # binding: fill in the fields
        ENTER,  # transport: Browser is kept
        ENTER,  # target name: the name is kept
        "https://app.example" + ENTER,  # start page URL
        ENTER,  # no sign-in steps
        ENTER,  # no notes
        ENTER,  # continue
    ]
    with keyboard(*questions) as (prompter, drawn):
        monkeypatch.setattr(commands, "_terminal", lambda: True)
        monkeypatch.setattr(commands, "_key_prompter", lambda: prompter)
        opening = commands._read_opening(None, None, perspective=True)

    assert opening.perspective is Perspective.ENGINEER
    assert opening.connection_skipped is False
    connection = opening.connection
    assert connection is not None
    assert connection.binding.transport == "browser"
    assert connection.binding.identity.name == "Policy assistant"
    # the Perspective is the first question, so its hint offers no Esc
    assert hints(drawn)[:2] == [
        "↑↓ move | Enter End user",
        "Esc back | ↑↓ move | Enter Build Spec only",
    ]


@pytest.mark.parametrize(
    ("questions", "expected"),
    [
        # the cursor starts on Continue. Space selects the first capability, Enter on
        # Continue, then Esc on the confidence asks the capabilities again with the
        # selection kept
        (
            [UP * 99 + SPACE + DOWN * 99 + UP + ENTER, ESC, ENTER, DOWN + ENTER],
            (1, CapabilityConfidence.MEDIUM),
        ),
        ([DOWN * 99 + ENTER], (None, None)),
    ],
    ids=["select-then-back", "skip"],
)
def test_the_capability_keys_select_skip_and_go_back(
    questions: list[str], expected: tuple[int | None, CapabilityConfidence | None]
) -> None:
    with keyboard(*questions) as (prompter, _):
        selected, confidence = read_capability_evidence(
            out=lambda _: None, prompter=prompter
        )

    assert (None if selected is None else len(selected), confidence) == expected


class _Stream(io.StringIO):
    def __init__(self, tty: bool) -> None:
        super().__init__()
        self.tty = tty

    def isatty(self) -> bool:
        return self.tty


@pytest.mark.parametrize(
    ("stdin", "stdout", "term", "keys"),
    [
        (True, True, "xterm-256color", True),
        (False, True, "xterm-256color", False),
        (True, False, "xterm-256color", False),
        (True, True, "dumb", False),
    ],
    ids=["terminal", "redirected-input", "redirected-output", "dumb-terminal"],
)
def test_keys_are_read_only_in_an_interactive_terminal(
    monkeypatch: pytest.MonkeyPatch, stdin: bool, stdout: bool, term: str, keys: bool
) -> None:
    monkeypatch.setattr("sys.stdin", _Stream(stdin))
    monkeypatch.setattr("sys.stdout", _Stream(stdout))
    monkeypatch.setenv("TERM", term)

    assert isinstance(commands._key_prompter(), KeyPrompter) is keys
