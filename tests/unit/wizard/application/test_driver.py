"""The interview state machine: the clarify cap, the gates, and model failure."""

import json
from dataclasses import dataclass

import pytest

from metis.wizard.adapters.llm.gateway import ModelOutputError
from metis.wizard.application import InterviewMessage
from metis.wizard.application.config import clarify_turn_cap, opening_question
from metis.wizard.application.driver import DriverState as ApplicationDriverState
from metis.wizard.application.driver import StepDriver
from metis.wizard.application.readiness import scenario_readiness
from metis.wizard.contracts import (
    ChatRequest,
    ChatResponse,
    ChoiceResponse,
    FormRequest,
    InterviewDocument,
    Patch,
    PatchOp,
    Perspective,
    ScenarioCard,
    Specification,
    StepResult,
    Target,
    WarningSource,
)
from metis.wizard.domain.permissions import InterviewStep
from metis.wizard.domain.specification import Behaviour, collect_specification_ids
from tests.fixtures.wizard.context import interview_context
from tests.fixtures.wizard.scripted import ScriptedInterviewer
from tests.fixtures.wizard.specifications import research_assistant


def driver_state(**values: object) -> ApplicationDriverState:
    """Build a driver state with the required opening context."""
    return ApplicationDriverState(context=interview_context(), **values)


def offered(request, action: str, target: str | None = None):
    """The option a review offers for `action`, on any card, heading or screen."""
    from metis.wizard.contracts.conversation import options_of

    return next(
        option
        for option in options_of(request).values()
        if option.id.action == action and (target is None or option.id.target == target)
    )


def empty_state(step=InterviewStep.CLARIFY, history=None) -> ApplicationDriverState:
    return driver_state(
        specification=Specification(target=Target(name="X", description="", users="")),
        step=step,
        history=history or [],
    )


# ── the clarify cap ────────────────────────────────────────────────────────


@dataclass
class NeverDone(ScriptedInterviewer):
    """A model that always says it needs one more question."""

    def clarify(self, specification, history, context=None):
        self.calls.append("clarify")
        from metis.wizard.contracts import ClarifyResult

        return ClarifyResult(message="One more thing?", done=False)


def after_opening(*model_questions: str) -> list[InterviewMessage]:
    return [
        InterviewMessage(role="assistant", text=opening_question()),
        InterviewMessage(role="user", text="It answers research questions."),
        *(InterviewMessage(role="assistant", text=q) for q in model_questions),
    ]


def test_the_opening_question_costs_no_model_call() -> None:
    interviewer = NeverDone()
    driver = StepDriver(interviewer=interviewer)

    request = driver.compose(empty_state())

    assert isinstance(request, ChatRequest)
    assert request.prompt == opening_question()
    assert interviewer.calls == []


def test_a_model_that_never_stops_is_stopped() -> None:
    """Clarification ends at the cap, even if required details still need a form."""
    driver = StepDriver(interviewer=NeverDone())
    history = after_opening(*(f"q{i}" for i in range(clarify_turn_cap())))
    state = empty_state(history=history)

    request = driver.compose(state)

    assert state.step is InterviewStep.BEHAVIOURS
    # the form for the missing Target fields still belongs to Clarify, so it keeps that header
    assert isinstance(request, FormRequest)
    assert request.title == "Understanding your target"


def test_below_the_cap_it_keeps_asking() -> None:
    driver = StepDriver(interviewer=NeverDone())
    state = empty_state(history=after_opening("q1"))

    request = driver.compose(state)

    assert request.prompt == "One more thing?"
    assert state.step is InterviewStep.CLARIFY


def test_clarify_commits_target_but_not_behaviours() -> None:
    """Clarify writes the target before the next question, but never drafts behaviours."""
    driver = StepDriver(interviewer=ScriptedInterviewer(clarify_questions=5))
    state = empty_state(history=after_opening())

    request = driver.compose(state)

    assert request.prompt
    assert state.specification.target.name == "Research assistant"
    assert state.specification.target.users == "Policy analysts"
    assert state.specification.target.description
    assert state.specification.target.detail
    assert state.specification.features == []
    assert state.specification.scenarios == []


def test_a_thin_answer_writes_no_target_fields() -> None:
    @dataclass
    class ThinInterviewer(ScriptedInterviewer):
        def clarify(self, specification, history, context=None):
            from metis.wizard.contracts import ClarifyResult

            return ClarifyResult(message="Tell me a little more.", done=False)

    state = empty_state(history=after_opening())
    driver = StepDriver(interviewer=ThinInterviewer())

    request = driver.compose(state)

    assert request.prompt == "Tell me a little more."
    assert state.specification.target.description == ""
    assert state.specification.target.users == ""
    assert state.step is InterviewStep.CLARIFY


def test_clarify_rejects_a_non_target_patch() -> None:
    @dataclass
    class WritesABehaviour(NeverDone):
        def clarify(self, specification, history, context=None):
            from metis.wizard.contracts import ClarifyResult

            return ClarifyResult(
                message="One more thing?",
                done=False,
                patches=[
                    {
                        "op": "set",
                        "path": "features[F-1].name",
                        "value": "Not during clarify",
                    }
                ],
            )

    state = empty_state(history=after_opening())
    driver = StepDriver(interviewer=WritesABehaviour())

    driver.compose(state)

    assert state.specification.features == []


def test_model_drafts_cannot_change_interview_context() -> None:
    state = empty_state(step=InterviewStep.BEHAVIOURS)
    state.context = interview_context(
        perspective=Perspective.SECURITY,
        known_capability_ids=["tool_use"],
    )
    before = state.context.model_copy(deep=True)
    driver = StepDriver(interviewer=ScriptedInterviewer())

    driver._run(
        state,
        StepResult(
            message="",
            patches=[
                {
                    "op": "set",
                    "path": "context.perspective",
                    "value": "engineer",
                },
                {
                    "op": "set",
                    "path": "context.capability_evidence.confidence",
                    "value": "high",
                },
            ],
        ),
    )

    assert state.context.perspective is Perspective.SECURITY
    assert state.context == before


def test_a_later_target_edit_does_not_move_the_step() -> None:
    driver = StepDriver(interviewer=ScriptedInterviewer())
    state = empty_state(step=InterviewStep.CRITERIA)

    driver._run(
        state,
        StepResult(
            message="",
            patches=[
                {
                    "op": "set",
                    "path": "target.description",
                    "value": "A corrected description",
                }
            ],
        ),
    )

    assert state.specification.target.description == "A corrected description"
    assert state.step is InterviewStep.CRITERIA


def test_the_configured_cap_is_positive() -> None:
    assert clarify_turn_cap() > 0


# ── the step header ────────────────────────────────────────────────────────


def _compose_at(step: InterviewStep):
    """Compose the screen for one step over a fully-drafted specification, no model call needed."""
    driver = StepDriver(interviewer=ScriptedInterviewer())
    state = driver_state(specification=research_assistant(), step=step)
    return driver.compose(state)


def test_every_screen_reports_a_position_consistent_with_its_step() -> None:
    """The header is stamped once, from the step, so no screen can disagree with another.

    Positions are one-based and total six. Behaviours is the second of the six interview
    steps because clarify is the first, even though a chat rather than a screen composes it.
    """
    expected = {
        InterviewStep.CLARIFY: ("Understanding your target", 1),
        InterviewStep.BEHAVIOURS: ("Features / Expected Behaviours", 2),
        InterviewStep.CRITERIA: ("Acceptance criteria", 3),
        InterviewStep.PERSONAS: ("Personas", 4),
        InterviewStep.SCENARIOS: ("Scenarios", 5),
        InterviewStep.TEST_CASES: ("Test Cases", 6),
    }

    for step, (title, position) in expected.items():
        request = _compose_at(step)
        assert request.title == title, step
        assert request.step == position, step
        assert request.steps == 6, step


def test_criteria_cards_carry_no_grader_annotation() -> None:
    request = _compose_at(InterviewStep.CRITERIA)

    components = [component for card in request.cards for component in card.components]
    assert components
    assert all("note" not in component.model_dump() for component in components)
    assert all(
        "measured by:" not in component.text
        for component in components
        if hasattr(component, "text")
    )


def test_criteria_keep_feature_groups_and_expandable_grader_controls() -> None:
    from metis.wizard.contracts.conversation import CardDetails, CardText, options_of

    request = _compose_at(InterviewStep.CRITERIA)
    card = next(card for card in request.cards if card.id == "EB-1")
    assert card.section_id == "F-1"
    criteria = [
        component for component in card.components if isinstance(component, CardDetails)
    ]
    assert len(criteria) == 2
    first, grader, _actions = criteria[0].components
    assert criteria[0].expanded
    assert isinstance(first, CardText)
    assert first.text == research_assistant().criterion("AC-1-1").description
    assert isinstance(grader, CardDetails)
    assert not grader.expanded and grader.muted
    assert any(getattr(item, "label", None) == "Grader" for item in grader.components)
    offered = options_of(request)
    assert {"edit:AC-1-1", "remove:AC-1-1", "add:EB-1"} <= set(offered)
    # The Criteria review has no checkboxes: a selected Behaviour supplies all its Criteria.
    assert all(card.selected is None for card in request.cards)


def test_the_terminal_step_carries_no_header() -> None:
    """DONE is off the interview list, so a request stamped there draws no header."""
    from metis.wizard.application import screens
    from metis.wizard.contracts import ChatRequest

    request = ChatRequest(prompt="done")
    screens.stamp_step(request, InterviewStep.DONE)

    assert (request.title, request.step, request.steps) == (None, None, None)


def test_a_mid_step_form_inherits_the_parent_steps_header() -> None:
    """Adding a persona mid-step keeps the personas header, not a new one."""
    from metis.wizard.contracts import ChoiceResponse

    driver = StepDriver(interviewer=ScriptedInterviewer())
    state = driver_state(
        specification=research_assistant(), step=InterviewStep.PERSONAS
    )
    screen = driver.compose(state)
    state.pending = screen

    add = offered(screen, "add", "personas")
    driver.handle(state, screen, ChoiceResponse(selected=[str(add.id)]))

    form = state.pending
    assert form is not None
    assert (form.title, form.step, form.steps) == ("Personas", 4, 6)


def test_the_persona_add_form_keeps_the_name_and_description_and_generates_an_id() -> (
    None
):
    """One submission adds one Persona with a generated id."""
    from metis.wizard.contracts import ChoiceResponse, FormResponse

    driver = StepDriver(interviewer=ScriptedInterviewer())
    specification = research_assistant()
    before = len(specification.personas)
    state = driver_state(
        specification=specification,
        step=InterviewStep.PERSONAS,
        issued_ids=collect_specification_ids(specification),
    )
    screen = driver.compose(state)
    state.pending = screen

    add = offered(screen, "add", "personas")
    driver.handle(state, screen, ChoiceResponse(selected=[str(add.id)]))
    form = state.pending
    assert form is not None
    assert [f.id for f in form.fields] == ["name", "description", "metadata"]

    driver.handle(
        state,
        form,
        FormResponse(
            values={
                "name": "Careful reviewer",
                "description": "Second-guesses each decision.",
                # A row left empty in both parts is a row the user did not fill.
                "metadata": json.dumps(
                    [["Role", "Policy reviewer"], ["", ""], ["Patience", "low"]]
                ),
            }
        ),
    )

    added = specification.personas[-1]
    assert len(specification.personas) == before + 1
    assert added.id == "P-1"
    assert added.name == "Careful reviewer"
    assert added.description == "Second-guesses each decision."
    assert added.metadata == {"Role": "Policy reviewer", "Patience": "low"}
    assert added.id in state.user_typed

    # Every stored value survives the form, including a line break or ": " in a detail.
    added.metadata = {"goals": "Find sources\nCompare them", "a: b": "c\\d"}
    screen = driver.compose(state)
    driver.handle(state, screen, ChoiceResponse(selected=[f"edit:{added.id}"]))
    form = state.pending
    values = {f.id: f.value for f in form.fields}
    driver.handle(state, form, FormResponse(values={**values, "name": "Renamed"}))
    assert added.name == "Renamed"
    assert added.metadata == {"goals": "Find sources\nCompare them", "a: b": "c\\d"}
    added.name = "Careful reviewer"

    # A detail with a value but no name keeps the form open with the typed text.
    screen = driver.compose(state)
    driver.handle(state, screen, ChoiceResponse(selected=[f"edit:{added.id}"]))
    form = state.pending
    driver.handle(
        state,
        form,
        FormResponse(
            values={
                "name": "X",
                "description": "Y",
                "metadata": json.dumps([["", "a value with no name"]]),
            }
        ),
    )
    assert state.pending is not form and state.pending.fields[0].value == "X"
    assert added.name == "Careful reviewer"


def test_the_behaviour_add_form_is_scoped_to_the_selected_feature() -> None:
    """A manual Behaviour keeps the Feature target from the screen through submission."""
    from metis.wizard.contracts import FormResponse

    driver = StepDriver(interviewer=ScriptedInterviewer())
    specification = research_assistant()
    state = driver_state(
        specification=specification,
        step=InterviewStep.BEHAVIOURS,
        issued_ids=collect_specification_ids(specification),
    )
    screen = driver.compose(state)
    state.pending = screen
    add = offered(screen, "add", "F-2")
    driver.handle(state, screen, ChoiceResponse(selected=[str(add.id)]))

    form = state.pending
    assert form is not None and form.target == "F-2"
    assert [field.id for field in form.fields] == ["name", "description"]
    before_t1 = [behaviour.id for behaviour in specification.feature("F-1").behaviours]  # type: ignore[union-attr]
    driver.handle(
        state,
        form,
        FormResponse(
            values={
                "name": "Recover gracefully",
                "description": "Stops safely after a failed search.",
            }
        ),
    )

    added = specification.feature("F-2").behaviours[-1]  # type: ignore[union-attr]
    assert (added.id, added.name, added.description) == (
        "EB-4",
        "Recover gracefully",
        "Stops safely after a failed search.",
    )
    assert added.measured is True
    assert [
        behaviour.id for behaviour in specification.feature("F-1").behaviours
    ] == before_t1  # type: ignore[union-attr]
    assert {"EB-4"} <= state.issued_ids
    assert {"EB-4"} <= state.user_typed


def test_a_behaviour_form_with_a_stale_or_missing_feature_target_changes_nothing() -> (
    None
):
    from metis.wizard.contracts import FormField, FormRequest, FormResponse

    driver = StepDriver(interviewer=ScriptedInterviewer())
    specification = research_assistant()
    state = driver_state(specification=specification, step=InterviewStep.BEHAVIOURS)
    before = specification.model_copy(deep=True)
    form = FormRequest(
        prompt="Add a Behaviour",
        target="F-404",
        fields=[
            FormField(id="name", label="Name"),
            FormField(id="description", label="Description"),
        ],
    )
    driver.handle(
        state,
        form,
        FormResponse(values={"name": "Orphan", "description": "Must not land."}),
    )
    assert specification == before
    assert driver.pending_warnings

    driver.pending_warnings.clear()
    no_target = form.model_copy(update={"target": None})
    driver.handle(
        state,
        no_target,
        FormResponse(values={"name": "Orphan", "description": "Must not land."}),
    )
    assert specification == before
    assert driver.pending_warnings


# ── persona ids are the visible and referenced labels ───────────────────────


def test_a_persona_name_is_visible_and_its_id_is_the_reference() -> None:
    """Cards and chips show Persona names while scenario references keep ids."""
    driver = StepDriver(interviewer=ScriptedInterviewer())
    specification = research_assistant()

    personas = driver.compose(
        driver_state(specification=specification, step=InterviewStep.PERSONAS)
    )
    titles = {c.id: c.title for c in personas.cards}
    assert titles == {
        "cooperative-delegator": "Cooperative delegator",
        "impatient-executive": "Impatient executive",
    }

    test_cases = driver.compose(
        driver_state(specification=specification, step=InterviewStep.TEST_CASES)
    )
    row = next(card for card in test_cases.cards if card.id == "TC-001")
    assert row.columns[0].summary == "Cooperative delegator"
    assert specification.task("TC-001").persona_ref == "cooperative-delegator"  # type: ignore[union-attr]

    # The Test Case form shows names and sends ids.
    from metis.wizard.application.screens import task_form

    form = task_form(specification, "TC-001")
    persona = form.fields[0]
    assert (persona.id, persona.value) == ("persona", "cooperative-delegator")
    assert {c.value: c.label for c in persona.choices}["impatient-executive"] == (
        "Impatient executive"
    )


def test_shared_review_screens_show_names_and_descriptions() -> None:
    driver = StepDriver(interviewer=ScriptedInterviewer())
    specification = research_assistant()

    behaviours = driver.compose(
        driver_state(specification=specification, step=InterviewStep.BEHAVIOURS)
    )
    assert behaviours.cards[0].title == "Cite factual claims"
    assert (
        behaviours.cards[0].components[0].text
        == "Cites a source for every factual claim"
    )  # type: ignore[union-attr]

    personas = driver.compose(
        driver_state(specification=specification, step=InterviewStep.PERSONAS)
    )
    assert personas.cards[0].title == "Cooperative delegator"
    assert personas.cards[0].components[0].text.startswith("A policy analyst")  # type: ignore[union-attr]

    scenarios = driver.compose(
        driver_state(specification=specification, step=InterviewStep.SCENARIOS)
    )
    scenario = next(c for c in scenarios.cards if c.profile_section_id == "scenarios")
    assert scenario.title == "Supported literature review"
    # A Persona or Scenario id only repeats its name, so the card asks for no id chip.
    assert not scenario.show_id and not personas.cards[0].show_id
    assert scenario.components[0].text.startswith("Ask for a literature review")  # type: ignore[union-attr]
    # The Scenario review shows no Test Case: they are matched on the next review.
    assert all(c.profile_section_id == "scenarios" for c in scenarios.cards)
    test_cases = driver.compose(
        driver_state(specification=specification, step=InterviewStep.TEST_CASES)
    )
    row = test_cases.cards[0]
    assert [column.title for column in row.columns] == [
        "Persona",
        "Scenario",
        "Behaviours",
        "Trials",
        "Files",
    ]
    assert row.columns[1].summary == "Supported literature review"
    # The Behaviour chips show ids, with the description as the hint.
    chips = row.columns[2].components[0].options  # type: ignore[union-attr]
    assert (chips[0].label, chips[0].hint) == (
        "EB-1",
        "Cite factual claims: Cites a source for every factual claim",
    )
    assert row.show_id and not row.components


def test_drafted_behaviours_start_measured_on_the_behaviour_screen() -> None:
    """The combined Behaviour screen reviews the draft and asks which to measure in one place:
    every drafted behaviour starts measured, so each card draws a ticked measurement box, and
    the screen carries the measurement instruction rather than a bare review prompt."""
    specification = Specification(
        target=Target(name="Agent", description="An agent.", users="Operators")
    )
    driver = StepDriver(interviewer=ScriptedInterviewer())
    state = driver_state(specification=specification, step=InterviewStep.BEHAVIOURS)

    request = driver.compose(state)

    assert all(behaviour.measured for behaviour in specification.behaviours())
    assert all(card.selected for card in request.cards)
    assert all(card.options[0].selected for card in request.cards)
    assert request.instruction is not None
    assert request.instruction.strip()


# ── the test case gates ─────────────────────────────────────────────────────


def _test_cases_screen(specification):
    driver = StepDriver(interviewer=ScriptedInterviewer())
    state = driver_state(specification=specification, step=InterviewStep.TEST_CASES)
    return driver.compose(state)


def test_task_cards_show_planned_trials() -> None:
    specification = research_assistant()
    request = _test_cases_screen(specification)
    assert request.footer == "3 of 3 Test Cases selected, 9 trials"
    assert [
        (card.id, card.trials)
        for card in request.cards
        if isinstance(card, ScenarioCard)
    ] == [
        ("TC-001", 3),
        ("TC-002", 3),
        ("TC-003", 3),
    ]


@pytest.mark.parametrize(
    "fault", ["persona", "scenario", "behaviour", "trials", "coverage"]
)
def test_task_readiness_blocks_incomplete_inputs(fault: str) -> None:
    specification = research_assistant()
    if fault == "persona":
        specification.tasks[0].persona_ref = "missing"
    elif fault == "scenario":
        specification.tasks[0].scenario_ref = "missing"
    elif fault == "behaviour":
        specification.tasks[0].behaviour_refs = ["missing"]
    elif fault == "trials":
        specification.tasks[0].num_trials = 0
    else:
        specification.tasks = specification.tasks[:2]
    request = _test_cases_screen(specification)
    assert any(w.blocking for w in request.warnings)
    assert not next(o for o in request.options if o.id.action == "continue").enabled


def test_task_readiness_clears_after_correction() -> None:
    specification = research_assistant()
    specification.tasks[0].behaviour_refs = []
    assert any(w.blocking for w in _test_cases_screen(specification).warnings)
    specification.tasks[0].behaviour_refs = ["EB-1"]
    assert not _test_cases_screen(specification).warnings


def _cell(card, title):
    """The components in one Test Case table cell."""
    return next(column for column in card.columns if column.title == title).components


def _test_case_edit_state():
    specification = research_assistant()
    driver = StepDriver(interviewer=ScriptedInterviewer())
    state = driver_state(specification=specification, step=InterviewStep.TEST_CASES)
    return driver, state, driver.compose(state)


def test_task_behaviour_choices_select_all_owned_criteria() -> None:
    driver, state, request = _test_case_edit_state()
    card = next(card for card in request.cards if card.id == "TC-001")
    (choices,) = _cell(card, "Behaviours")
    assert [(str(option.id), option.selected) for option in choices.options] == [
        ("cover:TC-001:EB-1", True),
        ("cover:TC-001:EB-3", False),
    ]
    driver.handle(state, request, ChoiceResponse(selected=["cover:TC-001:EB-3"]))
    assert state.specification.tasks[0].behaviour_refs == ["EB-1", "EB-3"]

    driver.handle(
        state, driver.compose(state), ChoiceResponse(selected=["cover:TC-001:EB-1"])
    )
    assert state.specification.tasks[0].behaviour_refs == ["EB-3"]
    behaviour = state.specification.behaviour("EB-1")
    assert behaviour is not None and len(behaviour.criteria) == 2


def test_a_trial_edit_recomposes_the_scenario_total() -> None:
    driver, state, request = _test_case_edit_state()

    driver.handle(state, request, ChoiceResponse(values={"trials:TC-003": 7}))

    assert state.specification.task("TC-003").num_trials == 7  # type: ignore[union-attr]
    refreshed = driver.compose(state)
    assert refreshed.footer == "3 of 3 Test Cases selected, 13 trials"  # 2×3 + 1×7
    scenario_card = next(card for card in refreshed.cards if card.id == "TC-003")
    assert scenario_card.columns[3].components[0].value == 7  # type: ignore[union-attr]
    assert scenario_card.columns[3].summary == "7"
    assert scenario_card.trials == 7


def test_fixture_edits_normalize_and_compile() -> None:
    driver, state, request = _test_case_edit_state()

    driver.handle(
        state,
        request,
        ChoiceResponse(
            values={"files:TC-003": [" policy.pdf ", "faq.md", "policy.pdf"]}
        ),
    )

    scenario = state.specification.task("TC-003")
    assert scenario is not None and scenario.fixtures == ["policy.pdf", "faq.md"]

    from metis.wizard.application.compile import compile_experiment

    compiled = compile_experiment(state.specification, "edited")
    assert next(t for t in compiled["tasks"] if t["id"] == "TC-003")["fixtures"] == [
        "policy.pdf",
        "faq.md",
    ]

    refreshed = driver.compose(state)
    (files,) = _cell(
        next(card for card in refreshed.cards if card.id == "TC-003"), "Files"
    )
    assert files.value == ["policy.pdf", "faq.md"]

    driver.handle(state, refreshed, ChoiceResponse(values={"files:TC-003": ["faq.md"]}))
    assert state.specification.task("TC-003").fixtures == ["faq.md"]  # type: ignore[union-attr]

    refreshed = driver.compose(state)
    driver.handle(state, refreshed, ChoiceResponse(values={"files:TC-003": []}))
    assert state.specification.task("TC-003").fixtures == []  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "response",
    [
        ChoiceResponse(values={"trials:TC-003": 0}),
        ChoiceResponse(values={"trials:TC-003": 21}),
        ChoiceResponse.model_construct(
            selected=[], values={"trials:TC-003": ["not a number"]}
        ),
        ChoiceResponse(values={"files:TC-003": ["../secret.txt"]}),
        ChoiceResponse(values={"files:TC-003": ["/absolute.txt"]}),
        ChoiceResponse(values={"files:TC-003": ["folder\\secret.txt"]}),
        ChoiceResponse(values={"files:TC-003": [" "]}),
        # A comma separates names in a form value, so no file name may hold one.
        ChoiceResponse(values={"files:TC-003": ["report, final.pdf"]}),
        ChoiceResponse(values={"trials:S-404": 4}),
        ChoiceResponse(values={"not-offered:S-2": 4}),
        ChoiceResponse(selected=["continue"], values={"trials:TC-003": 4}),
        ChoiceResponse(values={"trials:TC-003": 4, "files:TC-003": []}),
    ],
)
def test_invalid_or_mixed_field_edits_do_not_mutate(response) -> None:
    driver, state, request = _test_case_edit_state()
    before = state.specification.model_copy(deep=True)

    driver.handle(state, request, response)

    assert state.specification == before
    refreshed = driver.compose(state)
    assert any(w.source is WarningSource.RUNTIME for w in refreshed.warnings)


def test_the_behaviour_screen_gates_continue_on_at_least_one_measured() -> None:
    """The review explains why Continue needs a selected Behaviour."""
    specification = research_assistant()
    for behaviour in specification.behaviours():
        behaviour.measured = False
    driver = StepDriver(interviewer=ScriptedInterviewer())
    state = driver_state(specification=specification, step=InterviewStep.BEHAVIOURS)

    request = driver.compose(state)

    assert any(warning.blocking for warning in request.warnings)
    assert not next(o for o in request.options if o.id.action == "continue").enabled

    specification.behaviour("EB-1").measured = True  # type: ignore[union-attr]
    request = driver.compose(state)

    assert not request.warnings
    assert next(o for o in request.options if o.id.action == "continue").enabled

    # More than five is allowed, with a warning that does not block.
    feature = specification.features[0]
    for number in range(4, 9):
        feature.behaviours.append(
            Behaviour(
                id=f"EB-{number}", name=f"B{number}", description="d", measured=True
            )
        )
    request = driver.compose(state)
    assert [(w.text, w.blocking) for w in request.warnings] == [
        ("You selected 6 behaviours. We suggest 5 or fewer.", False)
    ]
    assert next(o for o in request.options if o.id.action == "continue").enabled


def test_each_review_gates_its_continue_action_on_complete_content() -> None:
    from metis.wizard.application.screens import personas_screen

    specification = research_assistant()
    driver = StepDriver(interviewer=ScriptedInterviewer())

    specification.behaviour("EB-1").criteria = []  # type: ignore[union-attr]
    criteria = driver.compose(
        driver_state(specification=specification, step=InterviewStep.CRITERIA)
    )
    assert not next(
        option for option in criteria.options if option.id.action == "continue"
    ).enabled

    specification = research_assistant()
    specification.personas = []
    personas = personas_screen(specification, "Current personas")
    assert not next(
        option for option in personas.options if option.id.action == "continue"
    ).enabled


def test_the_final_continue_uses_full_specification_readiness() -> None:
    specification = research_assistant()
    specification.target.name = ""

    request = _test_cases_screen(specification)

    assert not scenario_readiness(specification)
    assert any("name and description" in warning.text for warning in request.warnings)
    assert not next(
        option for option in request.options if option.id.action == "continue"
    ).enabled


# ── going back ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("source", "destination", "expected_prompt"),
    [
        (
            InterviewStep.CRITERIA,
            InterviewStep.BEHAVIOURS,
            "Review the behaviour draft.",
        ),
        (
            InterviewStep.PERSONAS,
            InterviewStep.CRITERIA,
            "Review the acceptance criteria.",
        ),
        (
            InterviewStep.SCENARIOS,
            InterviewStep.PERSONAS,
            "Review the personas.",
        ),
        (
            InterviewStep.TEST_CASES,
            InterviewStep.SCENARIOS,
            "Review the scenarios.",
        ),
    ],
)
def test_every_visible_back_transition_restores_its_destination(
    source: InterviewStep, destination: InterviewStep, expected_prompt: str
) -> None:
    specification = research_assistant()
    interviewer = ScriptedInterviewer()
    driver = StepDriver(interviewer=interviewer)
    # The drafting messages travel in the state, so Back shows them after a round trip.
    state = driver_state(
        specification=specification,
        step=source,
        history=[
            InterviewMessage(role="user", text="Keep everything I already decided.")
        ],
        step_messages={
            InterviewStep.BEHAVIOURS: "Review the behaviour draft.",
            InterviewStep.CRITERIA: "Review the acceptance criteria.",
            InterviewStep.PERSONAS: "Review the personas.",
            InterviewStep.SCENARIOS: "Review the scenarios.",
        },
    )
    before_specification = specification.model_copy(deep=True)
    before_history = list(state.history)
    request = driver.compose(state)
    assert any(option.id.action == "back" for option in request.options)

    driver.handle(state, request, ChoiceResponse(selected=["back"]))
    destination_request = driver.compose(state)

    assert state.step is destination
    assert destination_request.prompt == expected_prompt
    assert state.specification == before_specification
    assert state.history == before_history
    assert interviewer.calls == []


def test_back_from_behaviours_shows_the_target_review_form_with_no_model_call() -> None:
    specification = research_assistant()
    interviewer = ScriptedInterviewer()
    driver = StepDriver(interviewer=interviewer)
    state = driver_state(
        specification=specification,
        step=InterviewStep.BEHAVIOURS,
        behaviours_confirmed=True,
    )
    request = driver.compose(state)

    driver.handle(state, request, ChoiceResponse(selected=["back"]))

    form = state.pending
    assert isinstance(form, FormRequest)
    assert state.step is InterviewStep.CLARIFY
    assert form.title == "Understanding your target"
    assert {field.id: field.value for field in form.fields} == {
        "target.name": specification.target.name,
        "target.users": specification.target.users,
        "target.description": specification.target.description,
        "target.detail": specification.target.detail,
    }
    assert not state.behaviours_confirmed
    assert interviewer.calls == []


def test_back_to_criteria_keeps_the_behaviour_confirmation() -> None:
    driver = StepDriver(interviewer=ScriptedInterviewer())
    state = driver_state(
        specification=research_assistant(),
        step=InterviewStep.PERSONAS,
        behaviours_confirmed=True,
    )
    request = driver.compose(state)

    driver.handle(state, request, ChoiceResponse(selected=["back"]))

    assert state.step is InterviewStep.CRITERIA
    assert state.behaviours_confirmed


def test_a_recomposed_screen_uses_a_neutral_message() -> None:
    specification = research_assistant()
    driver = StepDriver(interviewer=ScriptedInterviewer())
    state = driver_state(specification=specification, step=InterviewStep.BEHAVIOURS)

    request = driver.compose(state)

    assert request.prompt == "Choose what to evaluate."


def test_going_back_regenerates_nothing_that_already_exists() -> None:
    """Continue generates only what is missing; existing criteria are left alone."""
    specification = research_assistant()
    interviewer = ScriptedInterviewer()
    driver = StepDriver(interviewer=interviewer)
    state = driver_state(specification=specification, step=InterviewStep.BEHAVIOURS)
    before = specification.behaviour("EB-1").criteria[0].description  # type: ignore[union-attr]

    driver._advance(state)  # the Continue that generates

    assert "draft_criteria" not in interviewer.calls  # nothing was missing
    assert specification.behaviour("EB-1").criteria[0].description == before  # type: ignore[union-attr]


def test_missing_criteria_are_drafted_only_for_measured_gaps() -> None:
    """Continue at Behaviours, or a later change that adds a measured Behaviour with no
    Criteria, drafts Criteria for that gap only. The full Specification is model context, but
    only measured gaps are writable output."""

    class ScopeBreakingInterviewer(ScriptedInterviewer):
        def draft_criteria(self, specification, context=None):
            result = super().draft_criteria(specification, context=context)
            result.patches.append(
                Patch(
                    op=PatchOp.ADD,
                    path="features[F-1].behaviours[EB-2].criteria",
                    value={
                        "name": "Unselected addition",
                        "description": "Given an answer, when it returns, then it stays short.",
                    },
                )
            )
            return result

    specification = research_assistant()
    specification.behaviour("EB-1").criteria = []  # type: ignore[union-attr]
    dormant_count = len(specification.behaviour("EB-2").criteria)  # type: ignore[union-attr]
    interviewer = ScopeBreakingInterviewer()
    driver = StepDriver(interviewer=interviewer)
    state = driver_state(specification=specification, step=InterviewStep.BEHAVIOURS)
    screen = driver.compose(state)

    driver.handle(state, screen, ChoiceResponse(selected=["continue"]))

    assert interviewer.calls == ["draft_criteria"]
    assert specification.behaviour("EB-1").criteria  # type: ignore[union-attr]
    assert len(specification.behaviour("EB-3").criteria) == 1  # type: ignore[union-attr]
    assert len(specification.behaviour("EB-2").criteria) == dormant_count  # type: ignore[union-attr]
    assert driver.pending_warnings

    # At Personas, a Behaviour added from the chat gets its Criteria in the same turn.
    class AddsBehaviour(ScriptedInterviewer):
        def chat(self, specification, step, text, target, context=None):
            return StepResult(
                message="Added.",
                patches=[
                    Patch(
                        op=PatchOp.ADD,
                        path="features[F-1].behaviours",
                        value={"name": "Polite", "description": "Answers politely."},
                    )
                ],
            )

    interviewer = AddsBehaviour()
    driver = StepDriver(interviewer=interviewer)
    state = driver_state(
        specification=research_assistant(),
        step=InterviewStep.PERSONAS,
        issued_ids=collect_specification_ids(research_assistant()),
    )
    driver.handle(
        state, driver.compose(state), ChoiceResponse(feedback="Add politeness")
    )
    added = state.specification.features[0].behaviours[-1]
    assert added.name == "Polite" and added.measured and added.criteria


# ── total model failure ────────────────────────────────────────────────────


@dataclass
class BrokenInterviewer(ScriptedInterviewer):
    """Every attempt already failed inside the client."""

    def draft_personas(self, specification, context=None):
        raise ModelOutputError("three attempts, all malformed")

    def chat(self, specification, step, text, target, context=None):
        raise ModelOutputError("three attempts, all malformed")


def test_a_total_failure_warns_and_loses_nothing() -> None:
    specification = research_assistant()
    specification.personas = []
    driver = StepDriver(interviewer=BrokenInterviewer())
    state = driver_state(specification=specification, step=InterviewStep.PERSONAS)

    request = driver.compose(state)

    runtime = [w for w in request.warnings if w.source is WarningSource.RUNTIME]
    assert runtime and "nothing you've decided has been lost" in runtime[0].text.lower()
    assert not runtime[0].blocking
    assert state.specification.features  # the specification is intact
    assert state.step is InterviewStep.PERSONAS  # and we did not advance past it


def test_a_chat_failure_warns_and_loses_nothing() -> None:
    """A chat is a model call like any other: when all its retries fail, it degrades to a
    warning and touches nothing, rather than crashing the turn."""
    specification = research_assistant()
    before = specification.model_copy(deep=True)
    driver = StepDriver(interviewer=BrokenInterviewer())
    state = driver_state(
        specification=specification,
        step=InterviewStep.CRITERIA,
        issued_ids=collect_specification_ids(specification),
    )

    driver.handle(
        state,
        ChatRequest(prompt="q", multiline=True),
        ChatResponse(text="change something"),
    )

    runtime = [w for w in driver.pending_warnings if w.source is WarningSource.RUNTIME]
    assert (
        runtime
        and "left your specification exactly as it is" in runtime[0].text.lower()
    )
    assert not runtime[0].blocking
    assert state.specification == before  # nothing applied


# ── responses that cost no model call ──────────────────────────────────────


def test_ticking_costs_no_model_call() -> None:
    specification = research_assistant()
    interviewer = ScriptedInterviewer()
    driver = StepDriver(interviewer=interviewer)
    state = driver_state(specification=specification, step=InterviewStep.BEHAVIOURS)
    request = driver.compose(state)
    interviewer.calls.clear()

    driver.handle(state, request, ChoiceResponse(selected=["tick:EB-2"]))

    assert interviewer.calls == []
    assert specification.behaviour("EB-2").measured is True  # type: ignore[union-attr]


def test_only_the_users_own_chat_can_select_behaviours_and_set_trials() -> None:
    """Measured state and Trials are the user's decisions. Chat feedback is the user deciding,
    so its patches apply, with a type check. A drafting call with the same patches is refused."""
    decisions = [
        Patch(
            op=PatchOp.SET, path="features[F-1].behaviours[EB-2].measured", value=True
        ),
        Patch(op=PatchOp.SET, path="tasks[TC-001].num_trials", value=5),
        Patch(
            op=PatchOp.SET, path="tasks[TC-002].num_trials", value=50
        ),  # out of range
    ]

    class Decides(ScriptedInterviewer):
        def chat(self, specification, step, text, target, context=None):
            return StepResult(message="Done.", patches=list(decisions))

        def draft_personas(self, specification, context=None):
            return StepResult(message="Drafted.", patches=list(decisions))

    specification = research_assistant()
    driver = StepDriver(interviewer=Decides())
    state = driver_state(
        specification=specification,
        step=InterviewStep.SCENARIOS,
        behaviours_confirmed=True,
    )
    driver.handle(state, driver.compose(state), ChoiceResponse(feedback="Measure EB-2"))
    assert specification.behaviour("EB-2").measured  # type: ignore[union-attr]
    assert specification.task("TC-001").num_trials == 5  # type: ignore[union-attr]
    assert specification.task("TC-002").num_trials == 3  # type: ignore[union-attr]
    # No Test Case covers the newly measured Behaviour yet. The review names the gap, so
    # the user chooses where it runs. It is not added to every Test Case.
    assert [b.id for b in specification.uncovered()] == ["EB-2"]

    specification = research_assistant()
    specification.personas = []
    state = driver_state(specification=specification, step=InterviewStep.PERSONAS)
    driver.compose(state)
    assert not specification.behaviour("EB-2").measured  # type: ignore[union-attr]
    assert specification.task("TC-001").num_trials == 3  # type: ignore[union-attr]


def test_model_output_is_scoped_and_a_removal_takes_its_test_cases() -> None:
    """A drafting call writes only its own collection, so it cannot add a measured Behaviour.
    A chat REMOVE of a Persona also removes the Test Cases that used it, and says so."""

    class Overreaches(ScriptedInterviewer):
        def draft_scenarios(self, specification, context=None):
            result = super().draft_scenarios(specification, context=context)
            result.patches.append(
                Patch(
                    op=PatchOp.ADD,
                    path="features[F-1].behaviours",
                    value={"name": "Extra", "description": "Model added."},
                )
            )
            return result

        def chat(self, specification, step, text, target, context=None):
            return StepResult(
                message="Removed.",
                patches=[
                    Patch(op=PatchOp.REMOVE, path="personas[impatient-executive]")
                ],
            )

    specification = research_assistant()
    specification.scenarios, specification.tasks = [], []
    driver = StepDriver(interviewer=Overreaches())
    state = driver_state(specification=specification, step=InterviewStep.SCENARIOS)
    measured = {b.id for b in specification.measured_behaviours()}
    driver.compose(state)
    assert {b.id for b in specification.measured_behaviours()} == measured
    assert specification.scenarios

    specification = research_assistant()
    state = driver_state(
        specification=specification,
        step=InterviewStep.PERSONAS,
        behaviours_confirmed=True,
    )
    driver = StepDriver(interviewer=Overreaches())
    driver.handle(state, driver.compose(state), ChoiceResponse(feedback="Drop him"))
    assert [t.id for t in specification.tasks] == ["TC-001", "TC-003"]
    assert any("TC-002" in w.text for w in driver.pending_warnings)


# ── a reworded criterion re-maps its grader, silently ───────────────────────

_AC1 = "features[F-1].behaviours[EB-1].criteria[AC-1-1].description"


@dataclass
class RewordingInterviewer(ScriptedInterviewer):
    """A chat that rewords one criterion, the way the model is told to when the user asks
    for a different grader — it never touches grader_fqn itself."""

    def chat(self, specification, step, text, target, context=None):
        self.calls.append("chat")
        from metis.wizard.contracts import Patch, PatchOp

        return StepResult(
            message="Reworded it.",
            patches=[
                Patch(op=PatchOp.SET, path=_AC1, value="it names the routing decision")
            ],
        )


class RecordingMatcher:
    """Records which criteria it was asked to (re)match, and stamps a marker so the effect
    is observable. Stands in for the grader matcher, whose internals are tested elsewhere."""

    def __init__(self) -> None:
        self.matched: list[str] = []
        self.degraded = False

    def match(self, criterion, _behaviour=None) -> str:
        self.matched.append(criterion.id)
        return "metis.library.graders.demo.DemoTraceBudgetGrader"

    def match_many(self, pairs) -> dict[str, str]:
        return {criterion.id: self.match(criterion) for criterion, _ in pairs}


def test_rewording_a_criterion_in_chat_rematches_only_it() -> None:
    """The other half of the grader rule: the model rewords, the matcher re-picks. Only the
    criterion whose text changed is rematched — untouched ones keep their grader and cost
    no call."""
    specification = research_assistant()
    matcher = RecordingMatcher()
    driver = StepDriver(interviewer=RewordingInterviewer(), matcher=matcher)
    state = driver_state(
        specification=specification,
        step=InterviewStep.CRITERIA,
        issued_ids=collect_specification_ids(specification),
    )

    driver.handle(
        state, ChatRequest(prompt="q", multiline=True), ChatResponse(text="use routing")
    )

    assert matcher.matched == ["AC-1-1"]  # only the reworded criterion
    assert (
        specification.behaviour("EB-1").criteria[0].grader_fqn  # type: ignore[union-attr]
        == "metis.library.graders.demo.DemoTraceBudgetGrader"
    )


# ── direct edits from a criteria card ────────────────────────────────────────


def _criterion_action(driver, state, action, label):
    """Return one EB-1 control while checking the user-facing workflow contract."""
    screen = driver.compose(state)
    state.pending = screen
    card = next(c for c in screen.cards if c.id == "EB-1")
    option = next(o for o in card.options if o.id.action == action)
    assert option.id.target == "EB-1"
    assert option.label == label
    return screen, option


def test_direct_behaviour_edit_preserves_identity_selection_and_task_references() -> (
    None
):
    from metis.wizard.contracts import FormRequest, FormResponse

    specification = research_assistant()
    driver = StepDriver(interviewer=ScriptedInterviewer())
    state = driver_state(
        specification=specification,
        step=InterviewStep.CRITERIA,
        issued_ids=collect_specification_ids(specification),
    )
    screen, edit = _criterion_action(driver, state, "edit", "Edit Cite factual claims")
    before_tasks = [task.model_dump() for task in specification.tasks]
    driver.handle(state, screen, ChoiceResponse(selected=[str(edit.id)]))
    form = state.pending
    assert isinstance(form, FormRequest)
    assert form.purpose == "edit" and form.cancellable
    assert form.fields[0].value == "Cite factual claims"
    driver.handle(
        state,
        form,
        FormResponse(
            values={
                "name": "Cite evidence",
                "description": "Use the supplied evidence.",
            }
        ),
    )
    behaviour = specification.behaviour("EB-1")
    assert behaviour is not None
    assert behaviour.name == "Cite evidence" and behaviour.measured
    assert behaviour.description == "Use the supplied evidence."
    assert [task.model_dump() for task in specification.tasks] == before_tasks
    assert "EB-1" in state.user_typed


# ── a typed Criterion from a Behaviour's "+": exact text, then matched ──────


def _type_one(driver, state, values):
    """Click "+" on EB-1's card, then submit `values` into the form it raises.

    Goes through compose/handle both times so the behaviour id rides on the form as its
    target exactly as it would from the door, rather than being constructed by hand."""
    from metis.wizard.contracts import ChoiceResponse, FormRequest, FormResponse

    screen, add = _criterion_action(
        driver, state, "add", "Add a Criterion to Cite factual claims"
    )
    assert add.icon == "plus"
    driver.handle(state, screen, ChoiceResponse(selected=[str(add.id)]))

    form = state.pending
    assert isinstance(form, FormRequest)
    assert form.target == "EB-1"
    assert [f.id for f in form.fields] == ["name", "description"]
    driver.handle(state, form, FormResponse(values=values))


def test_writing_two_criteria_by_hand_produces_two_distinct_ones() -> None:
    """Manual entry appends a FORM criterion under the card's behaviour, verbatim, with no
    drafting call. A second submission gets its own scoped id rather than overwriting the
    first, and each new one is matched to a Grader."""
    specification = research_assistant()
    matcher = RecordingMatcher()
    interviewer = ScriptedInterviewer()
    driver = StepDriver(interviewer=interviewer, matcher=matcher)
    state = driver_state(
        specification=specification,
        step=InterviewStep.CRITERIA,
        issued_ids=collect_specification_ids(specification),
    )

    _type_one(
        driver,
        state,
        {
            "name": "Long report outcome",
            "description": "Given a long report, when it is asked to summarise, then it keeps every citation.",
        },
    )
    _type_one(
        driver,
        state,
        {
            "name": "Consistent follow-up",
            "description": "Given a follow-up, when it answers again, then it stays consistent.",
        },
    )

    eb1 = specification.behaviour("EB-1")
    assert [c.id for c in eb1.criteria] == ["AC-1-1", "AC-1-2", "AC-1-3", "AC-1-4"]  # type: ignore[union-attr]
    fresh = eb1.criteria[-2:]  # type: ignore[union-attr]
    assert [c.description for c in fresh] == [
        "Given a long report, when it is asked to summarise, then it keeps every citation.",
        "Given a follow-up, when it answers again, then it stays consistent.",
    ]  # verbatim, in order
    assert {c.id for c in fresh} <= state.user_typed
    assert matcher.matched == ["AC-1-3", "AC-1-4"]  # each new one matched, once
    assert interviewer.calls == []


# ── delete: the item and its dependants together ────────────────────────────


@pytest.mark.parametrize(
    ("step", "target", "confirm", "gone"),
    [
        (
            InterviewStep.BEHAVIOURS,
            "F-1",
            "Delete Answer quality? This also deletes 2 Behaviours and 3 Criteria. "
            "Its Behaviours are removed from 2 Test Cases.",
            {"F-1", "EB-1", "EB-2", "AC-1-1"},
        ),
        (
            InterviewStep.BEHAVIOURS,
            "EB-1",
            "Delete Cite factual claims? This also deletes 2 Criteria. "
            "It is removed from 2 Test Cases.",
            {"EB-1", "AC-1-1", "AC-1-2"},
        ),
        (
            InterviewStep.PERSONAS,
            "impatient-executive",
            "Delete Impatient executive? This also deletes 1 Test Case.",
            {"impatient-executive", "TC-002"},
        ),
        (
            InterviewStep.SCENARIOS,
            "S-2",
            "Delete Repeated search timeout? This also deletes 1 Test Case.",
            {"S-2", "TC-003"},
        ),
        (InterviewStep.TEST_CASES, "TC-001", None, {"TC-001"}),
    ],
)
def test_delete_names_and_removes_the_items_that_depend_on_it(
    step, target, confirm, gone
) -> None:
    from metis.wizard.domain.nodes import locate

    specification = research_assistant()
    driver = StepDriver(interviewer=ScriptedInterviewer())
    state = driver_state(
        specification=specification, step=step, behaviours_confirmed=True
    )
    screen = driver.compose(state)
    option = offered(screen, "remove", target)
    assert option.icon == "trash"
    assert option.confirm == confirm

    driver.handle(state, screen, ChoiceResponse(selected=[str(option.id)]))

    assert all(locate(specification, node_id) is None for node_id in gone)
    behaviours = {b.id for b in specification.behaviours()}
    assert all(set(t.behaviour_refs) <= behaviours for t in specification.tasks)


@pytest.mark.parametrize(
    ("step", "selected"),
    [
        (InterviewStep.PERSONAS, ["remove:cooperative-delegator"]),
        (InterviewStep.SCENARIOS, ["remove:S-1", "remove:S-2"]),
        (InterviewStep.BEHAVIOURS, ["remove:F-1", "remove:F-2"]),
        (InterviewStep.BEHAVIOURS, ["remove:EB-3", "tick:EB-1"]),
    ],
)
def test_deletes_that_would_empty_a_review_or_mix_with_other_actions_change_nothing(
    step, selected
) -> None:
    """The last Feature, Persona or Scenario stays, even when several deletes travel in one
    response. A delete is its own operation, so it is not combined with another action."""
    specification = research_assistant()
    specification.personas = specification.personas[:1]
    specification.tasks = [
        t for t in specification.tasks if t.persona_ref == specification.personas[0].id
    ]
    interviewer = ScriptedInterviewer()
    driver = StepDriver(interviewer=interviewer)
    state = driver_state(
        specification=specification, step=step, behaviours_confirmed=True
    )
    screen = driver.compose(state)
    if step is InterviewStep.PERSONAS:
        assert not offered(screen, "remove", selected[0].split(":")[1]).enabled
    before = specification.model_copy(deep=True)

    driver.handle(state, screen, ChoiceResponse(selected=selected))
    refreshed = driver.compose(state)

    assert specification == before
    assert interviewer.calls == []
    assert any(w.source is WarningSource.RUNTIME for w in refreshed.warnings)


# ── Test Cases: one per Persona and Scenario pair ───────────────────────────


def test_a_test_case_is_created_and_edited_in_its_row_and_pairs_stay_unique() -> None:
    from metis.wizard.contracts import FormRequest, FormResponse

    specification = research_assistant()
    driver = StepDriver(interviewer=ScriptedInterviewer())
    state = driver_state(
        specification=specification,
        step=InterviewStep.TEST_CASES,
        issued_ids=collect_specification_ids(specification),
    )
    state.context.documents = [InterviewDocument(name="policy.pdf")]
    screen = driver.compose(state)
    driver.handle(state, screen, ChoiceResponse(selected=["add:tasks"]))
    form = state.pending
    assert isinstance(form, FormRequest)
    # Each field names its table column. The form opens on the one free pair, covers all
    # measured Behaviours, and lists the used pairs.
    fields = {f.id: f for f in form.fields}
    assert {f.id: (f.column, f.value) for f in form.fields} == {
        "persona": ("Persona", "impatient-executive"),
        "scenario": ("Scenario", "S-2"),
        "behaviours": ("Behaviours", "EB-1,EB-3"),
        "trials": ("Trials", "3"),
        "files": ("Files", ""),
    }
    assert fields["behaviours"].multiple and fields["files"].multiple
    assert fields["behaviours"].choices[0].hint
    assert [c.value for c in fields["files"].choices] == ["policy.pdf"]
    assert {"persona": "cooperative-delegator", "scenario": "S-1"} in (
        form.used_combinations
    )
    values = {f.id: f.value for f in form.fields}

    # A used pair, an unknown id, an unmeasured Behaviour, bad Trials and a file name with a
    # folder are each refused. A new uploaded file name is accepted, as in the row's file field. The form stays open with the typed values.
    for change, reason in (
        ({"persona": "cooperative-delegator", "scenario": "S-1"}, "already uses"),
        ({"persona": "/oops"}, "from the lists"),
        ({"behaviours": "EB-2"}, "measured Behaviour"),
        ({"trials": "50"}, "Trials must be"),
        ({"files": "../secret.txt"}, "portable file names"),
    ):
        driver.handle(state, state.pending, FormResponse(values={**values, **change}))
        assert len(specification.tasks) == 3
        assert isinstance(state.pending, FormRequest) and reason in state.pending.prompt
        first = next(iter(change))
        assert {f.id: f.value for f in state.pending.fields}[first] == change[first]

    driver.handle(
        state,
        state.pending,
        FormResponse(
            values={
                **values,
                "behaviours": "EB-3",
                "trials": "5",
                "files": "policy.pdf",
            }
        ),
    )
    created = specification.tasks[-1]
    assert (created.persona_ref, created.scenario_ref) == ("impatient-executive", "S-2")
    assert (created.behaviour_refs, created.num_trials, created.fixtures) == (
        ["EB-3"],
        5,
        ["policy.pdf"],
    )
    # Every pair is now used, so "+" is shown but unavailable.
    assert not offered(driver.compose(state), "add", "tasks").enabled

    # Edit changes every cell of a row and keeps its id.
    driver.handle(
        state, driver.compose(state), ChoiceResponse(selected=["remove:TC-002"])
    )
    driver.handle(
        state, driver.compose(state), ChoiceResponse(selected=["edit:TC-001"])
    )
    driver.handle(
        state,
        state.pending,
        FormResponse(
            values={
                "persona": "impatient-executive",
                "scenario": "S-1",
                "behaviours": "EB-1,EB-3",
                "trials": "7",
                "files": "",
            }
        ),
    )
    edited = specification.task("TC-001")
    assert edited is not None and edited.persona_ref == "impatient-executive"
    assert (edited.behaviour_refs, edited.num_trials) == (["EB-1", "EB-3"], 7)


def test_only_selected_test_cases_run_count_and_export() -> None:
    """A Test Case tick includes or excludes it. Readiness, the footer and the export use
    the selected Test Cases only. With none selected, Continue is blocked."""
    from metis.wizard.application.readiness import selected_specification

    specification = research_assistant()
    driver = StepDriver(interviewer=ScriptedInterviewer())
    state = driver_state(specification=specification, step=InterviewStep.TEST_CASES)
    screen = driver.compose(state)
    tick = offered(screen, "tick", "TC-003")
    assert tick.selected and tick.patch is None
    assert next(c for c in screen.cards if c.id == "TC-003").selected

    driver.handle(state, screen, ChoiceResponse(selected=["tick:TC-003"]))
    screen = driver.compose(state)
    assert state.excluded_tasks == {"TC-003"}
    assert screen.footer == "2 of 3 Test Cases selected, 6 trials"
    # TC-003 was the only Test Case that covered EB-3.
    assert any(
        "EB-3 is covered by no selected Test Case" in w.text for w in screen.warnings
    )
    exported = selected_specification(specification, state.excluded_tasks)
    assert [t.id for t in exported.tasks] == ["TC-001", "TC-002"]
    # S-2 has no selected Test Case, so the export leaves it out.
    assert [scenario.id for scenario in exported.scenarios] == ["S-1"]

    # A tick is its own operation: Continue in the same response does not advance.
    driver.handle(state, screen, ChoiceResponse(selected=["tick:TC-003"]))
    screen = driver.compose(state)
    assert offered(screen, "continue").enabled
    driver.handle(
        state,
        screen,
        ChoiceResponse(
            selected=["tick:TC-001", "tick:TC-002", "tick:TC-003", "continue"]
        ),
    )
    assert state.step is InterviewStep.TEST_CASES
    screen = driver.compose(state)
    assert any(w.text == "Select at least one Test Case." for w in screen.warnings)
    assert not offered(screen, "continue").enabled

    # Duplicate pairs are checked among the selected Test Cases.
    state.excluded_tasks = {"TC-001"}
    for task in specification.tasks[1:]:
        task.persona_ref, task.scenario_ref = "cooperative-delegator", "S-1"
    screen = driver.compose(state)
    assert any("TC-003 uses the same Persona" in w.text for w in screen.warnings), [
        w.text for w in screen.warnings
    ]

    # A Test Case that a model removal deletes leaves the selection as well.
    class RemovesScenario(ScriptedInterviewer):
        def chat(self, specification, step, text, target, context=None):
            return StepResult(
                message="Removed.",
                patches=[Patch(op=PatchOp.REMOVE, path="scenarios[S-2]")],
            )

    state.excluded_tasks = {"TC-003"}
    specification.tasks[2].scenario_ref = "S-2"
    driver = StepDriver(interviewer=RemovesScenario())
    driver.handle(state, driver.compose(state), ChoiceResponse(feedback="Drop S-2"))
    assert specification.task("TC-003") is None and state.excluded_tasks == set()


def test_scenario_continue_matches_each_new_scenario_with_the_personas_the_model_picked() -> (
    None
):
    """The Scenario review shows Scenarios only. Its Continue asks the model to match each
    Scenario that has no Test Case yet, and the Test Case review shows the result.

    Each Test Case is selected, uses the default Trial count, and covers the measured
    Behaviours that the model picked. An unmeasured pick is left out with a warning, and a
    Test Case left with none covers all measured Behaviours. The model cannot add a second
    Test Case for a pair or a Test Case for a Scenario that already has one."""

    class Picks(ScriptedInterviewer):
        def draft_test_cases(self, specification, context=None):
            self.calls.append("draft_test_cases")

            def task(scenario, persona, behaviours):
                return Patch(
                    op=PatchOp.ADD,
                    path="tasks",
                    value={
                        "scenario_ref": scenario,
                        "persona_ref": persona,
                        "behaviour_refs": behaviours,
                    },
                )

            return StepResult(
                message="Two test cases.",
                patches=[
                    # EB-2 is not measured, so it is left out with a warning.
                    task("S-2", "impatient-executive", ["EB-1", "EB-2"]),
                    task("S-2", "impatient-executive", ["EB-3"]),
                    task("S-3", "cooperative-delegator", ["EB-2"]),
                    # S-1 already has a Test Case.
                    task("S-1", "impatient-executive", ["EB-1"]),
                ],
            )

    specification = research_assistant()
    specification.tasks = [t for t in specification.tasks if t.scenario_ref == "S-1"]
    specification.scenarios.append(
        specification.scenarios[1].model_copy(update={"id": "S-3", "name": "Third"})
    )
    before = [t.id for t in specification.tasks]
    interviewer = Picks()
    driver = StepDriver(interviewer=interviewer)
    state = driver_state(
        specification=specification,
        step=InterviewStep.SCENARIOS,
        behaviours_confirmed=True,
        issued_ids=collect_specification_ids(specification),
    )
    screen = driver.compose(state)
    assert {card.profile_section_id for card in screen.cards} == {"scenarios"}
    assert interviewer.calls == []

    driver.handle(state, screen, ChoiceResponse(selected=["continue"]))
    screen = driver.compose(state)

    assert state.step is InterviewStep.TEST_CASES
    assert interviewer.calls == ["draft_test_cases"]
    measured = [b.id for b in specification.measured_behaviours()]
    assert [
        (t.persona_ref, t.scenario_ref, t.behaviour_refs, t.num_trials)
        for t in specification.tasks
        if t.id not in before
    ] == [
        ("impatient-executive", "S-2", ["EB-1"], 3),
        # No measured pick: all measured Behaviours.
        ("cooperative-delegator", "S-3", measured, 3),
    ]
    assert [t.id for t in specification.tasks if t.scenario_ref == "S-1"] == before
    assert all(card.selected for card in screen.cards if isinstance(card, ScenarioCard))
    assert any("EB-2" in w.text for w in screen.warnings)

    # Back and Continue again does not match a Scenario that already has a Test Case.
    driver.handle(state, screen, ChoiceResponse(selected=["back"]))
    driver.handle(state, driver.compose(state), ChoiceResponse(selected=["continue"]))
    assert interviewer.calls == ["draft_test_cases"]


def test_duplicate_pairs_block_continue_and_model_patches() -> None:
    from metis.wizard.domain.applier import PatchValueError, validate_model_patches

    specification = research_assistant()
    specification.tasks[1].persona_ref = specification.tasks[0].persona_ref
    request = _test_cases_screen(specification)
    assert not next(o for o in request.options if o.id.action == "continue").enabled
    assert any("same Persona and Scenario" in w.text for w in request.warnings)

    with pytest.raises(PatchValueError):
        validate_model_patches(
            research_assistant(),
            [
                Patch(
                    op=PatchOp.SET,
                    path="tasks[TC-002].persona_ref",
                    value="cooperative-delegator",
                )
            ],
        )


def test_criterion_edit_form_changes_the_selected_requirement() -> None:
    from metis.wizard.contracts import FormResponse

    specification = research_assistant()
    criterion = specification.behaviour("EB-2").criteria[0]  # type: ignore[union-attr]
    specification.behaviour("EB-2").measured = True  # type: ignore[union-attr]
    state = driver_state(specification=specification, step=InterviewStep.CRITERIA)
    driver = StepDriver(interviewer=ScriptedInterviewer())
    screen = driver.compose(state)
    driver.handle(state, screen, ChoiceResponse(selected=[f"edit:{criterion.id}"]))
    assert state.pending is not None
    driver.handle(
        state,
        state.pending,
        FormResponse(
            values={
                "description": "The agent stays within the trace budget.",
                "name": criterion.name,
                "args.max_traces": "4",
            }
        ),
    )
    assert criterion.grader_args["max_traces"] == 4
    assert criterion.description == "The agent stays within the trace budget."


def test_fallback_parameter_edits_validate_before_replacing_settings() -> None:
    from metis.wizard.application.matching import CRITERION_JUDGE_FQN
    from metis.wizard.contracts import FormResponse

    specification = research_assistant()
    criterion = specification.features[0].behaviours[0].criteria[0]
    criterion.grader_fqn = CRITERION_JUDGE_FQN
    criterion.grader_args = {"threshold": 0.8, "model": "chosen-judge"}
    state = driver_state(specification=specification, step=InterviewStep.CRITERIA)
    driver = StepDriver(interviewer=ScriptedInterviewer())
    screen = driver.compose(state)
    driver.handle(state, screen, ChoiceResponse(selected=[f"edit:{criterion.id}"]))
    assert state.pending is not None
    driver.handle(
        state,
        state.pending,
        FormResponse(values={"args.threshold": "2"}),
    )
    assert criterion.grader_args == {"threshold": 0.8, "model": "chosen-judge"}
    assert state.pending is not None
    driver.handle(
        state,
        state.pending,
        FormResponse(values={"args.threshold": "0.6", "args.model": "chosen-judge"}),
    )
    assert criterion.grader_args == {"threshold": 0.6, "model": "chosen-judge"}
