"""Composing the screen for each step.

This is the package's answer to *"draw this screen"*, not *"here is my document"*. Every
function here walks the specification, decides each card's state, composes its components and
notes, runs the completeness check, and emits a finished request.

Nothing here calls a model. Screens are composed from the specification as it stands, which is why
document warnings clear themselves: they are recomputed every time a screen is built, so
there is never a stale flag to track.

All user-facing wording lives here. That is the accepted cost of the door contract — a door
wanting different phrasing changes this file, rather than two doors quietly disagreeing.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from metis.wizard.application.readiness import specification_readiness
from metis.wizard.application.trials import format_trials
from metis.wizard.contracts.conversation import (
    AnyCard,
    AnyCardComponent,
    BehaviourCard,
    CardColumn,
    CardDetails,
    CardNumberField,
    CardOptionGroup,
    CardText,
    CardUploadField,
    ChoiceRequest,
    FormChoice,
    FormField,
    FormRequest,
    Option,
    OptionId,
    ReviewSection,
    ScenarioCard,
    Warning,
    WarningSource,
    WizardRequest,
)
from metis.wizard.domain.nodes import dependants, locate
from metis.wizard.domain.patch import Patch, PatchOp, PatchOrigin
from metis.wizard.domain.permissions import InterviewStep

if TYPE_CHECKING:
    from metis.wizard.domain.specification import (
        Behaviour,
        Feature,
        Specification,
        Task,
    )

TRIALS_MIN = 1
TRIALS_MAX = 20
DEFAULT_TRIALS = 3  # the shared Task default
# One short sentence for each review. Each tells the user what to do on that screen.
# The report scores a Behaviour from its Criteria, so the instruction says what they stand for.
CRITERIA_INSTRUCTION = (
    "The criteria under a behaviour show how well it performs. "
    "Check that each one is right for its behaviour."
)
PERSONAS_INSTRUCTION = "Check that these personas are the users you want to simulate."
SCENARIOS_INSTRUCTION = (
    "Check that these scenarios are the situations you want to test."
)
TEST_CASES_INSTRUCTION = "Select the test cases to run."
# Guidance, not a rule: more measured Behaviours are allowed, with a warning.
SUGGESTED_BEHAVIOURS = 5


# ── step headers ─────────────────────────────────────────────────────────────

# The interview's steps, in order, each with the header title it shows. Position and total
# are *derived* from this list, so no screen builder ever writes a number — the one drift the
# design names out loud. CLARIFY is step one even though the model, not a screen builder,
# composes its chat; DONE is terminal and carries no header.
_STEP_TITLES: dict[InterviewStep, str] = {
    InterviewStep.CLARIFY: "Understanding your target",
    InterviewStep.BEHAVIOURS: "Features / Expected Behaviours",
    InterviewStep.CRITERIA: "Acceptance criteria",
    InterviewStep.PERSONAS: "Personas",
    InterviewStep.SCENARIOS: "Scenarios",
    InterviewStep.TEST_CASES: "Test Cases",
}
_INTERVIEW_STEPS: list[InterviewStep] = list(_STEP_TITLES)


def _ready_through(specification: Specification, step: InterviewStep) -> bool:
    """True when the Specification has no missing content at or before this review."""
    position = _INTERVIEW_STEPS.index(step)
    return not any(
        _INTERVIEW_STEPS.index(gap.stage) <= position
        for gap in specification_readiness(specification)
    )


def stamp_step(request: WizardRequest, step: InterviewStep) -> None:
    """Write the step's header onto a request: title, one-based position and total.

    One place turns a step into a position, so the screens cannot drift into disagreeing about
    which step they are. A step off the list — only DONE — leaves the fields at their
    `None` defaults, so a door draws no header rather than a wrong one.

    A mid-step form or chat is stamped with whatever step the interview is on when it is
    raised, which is the parent step — so "I'll add one" keeps the header anchored rather than
    looking like the interview jumped.
    """
    if step not in _STEP_TITLES:
        return
    request.title = _STEP_TITLES[step]
    request.step = _INTERVIEW_STEPS.index(step) + 1
    request.steps = len(_INTERVIEW_STEPS)


def _wizard_patch(path: str, value: object, op: PatchOp = PatchOp.SET) -> Patch:
    """A patch the package composed, and knows it composed.

    Everything on a tick, a chip or a stepper goes through here — which is what lets the
    applier trust it without an address check.
    """
    return Patch(op=op, path=path, value=value, origin=PatchOrigin.WIZARD)


def _behaviour_path(specification: Specification, behaviour_id: str, field: str) -> str:
    feature = specification.feature_of(behaviour_id)
    feature_id = feature.id if feature else "?"
    return f"features[{feature_id}].behaviours[{behaviour_id}].{field}"


def _section(feature: Feature) -> str:
    # The name alone. "Feature 1 ·" would be ordinal noise — the grouping is already visible, and
    # the number matches nothing the user could refer to.
    return feature.name


# ── review actions ───────────────────────────────────────────────────────────
#
# Every item on a review offers the same three actions, and each names its item by id only.
# The driver finds what the id names, so `edit` and `remove` mean the same at every step. The
# labels are complete text because the CLI shows them in place of the icons.


def _back() -> Option:
    return Option(id=OptionId(action="back"), label="← Back")


def _continue(enabled: bool) -> Option:
    # A disabled Continue is still shown, marked unavailable.
    return Option(
        id=OptionId(action="continue"), label="Continue", primary=True, enabled=enabled
    )


def _add(target: str, label: str, *, enabled: bool = True) -> Option:
    return Option(
        id=OptionId(action="add", target=target),
        label=label,
        icon="plus",
        enabled=enabled,
    )


def _edit(node_id: str, name: str) -> Option:
    return Option(
        id=OptionId(action="edit", target=node_id), label=f"Edit {name}", icon="pencil"
    )


def _count(number: int, one: str, many: str) -> str:
    return f"{number} {one if number == 1 else many}"


def _join(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _remove(
    specification: Specification, node_id: str, name: str, *, enabled: bool = True
) -> Option:
    """Delete an item. When other items go with it, the door asks first and names them."""
    found = locate(specification, node_id)
    extra = dependants(specification, found) if found else None
    confirm = None
    if extra:
        confirm = f"Delete {name}?"
        deleted = [
            _count(number, one, many)
            for number, one, many in (
                (extra.behaviours, "Behaviour", "Behaviours"),
                (extra.criteria, "Criterion", "Criteria"),
                (extra.tasks, "Test Case", "Test Cases"),
            )
            if number
        ]
        if deleted:
            confirm += f" This also deletes {_join(deleted)}."
        if extra.covering_tasks:
            subject = "Its Behaviours are" if extra.behaviours else "It is"
            confirm += (
                f" {subject} removed from "
                f"{_count(extra.covering_tasks, 'Test Case', 'Test Cases')}."
            )
    return Option(
        id=OptionId(action="remove", target=node_id),
        label=f"Delete {name}",
        icon="trash",
        confirm=confirm,
        enabled=enabled,
    )


def _more_information(metadata: dict[str, str]) -> list[AnyCardComponent]:
    """Supporting detail, drawn quietly. An item with no metadata shows no disclosure."""
    if not metadata:
        return []
    return [
        CardDetails(
            title="More information",
            muted=True,
            components=[
                CardText(label=key, text=value) for key, value in metadata.items()
            ],
        )
    ]


# ── step 1 · behaviours ────────────────────────────────────────────────────

BEHAVIOUR_INSTRUCTION = f"Select max {SUGGESTED_BEHAVIOURS} key behaviours only."


def target_completion_form(specification: Specification) -> FormRequest | None:
    """Ask for required Target fields that the model did not supply.

    It is not cancellable: the Behaviour review needs these fields. Back still works.
    """
    fields: list[FormField] = []
    if not specification.target.name.strip():
        fields.append(
            FormField(
                id="target.name", label="Target name", multiline=False, required=True
            )
        )
    if not specification.target.description.strip():
        fields.append(
            FormField(
                id="target.description", label="Target description", required=True
            )
        )
    if not fields:
        return None
    return FormRequest(
        prompt="Enter the missing target details to continue to the behaviour review.",
        fields=fields,
        submit_label="Continue",
    )


TARGET_REVIEW_FIELDS = (
    ("target.name", "Target name", False, True),
    ("target.users", "Target users", True, False),
    ("target.description", "Target description", True, True),
    ("target.detail", "Target detail", True, False),
)


def target_review_form(specification: Specification) -> FormRequest:
    """Show the Target fields with their current values, for Back from Behaviours.

    This form replaces the Clarify chat when the user goes back. It costs no model call, and
    Continue with no change returns to the Behaviour review with all content kept. Cancel also
    returns to the Behaviour review, with no change.
    """
    target = specification.target
    return FormRequest(
        prompt=(
            "Review the target details. Change a field, or keep it as it is, "
            "then continue to the behaviour review."
        ),
        cancellable=True,
        submit_label="Continue",
        fields=[
            FormField(
                id=field_id,
                label=label,
                multiline=multiline,
                required=required,
                value=getattr(target, field_id.split(".", 1)[1]),
            )
            for field_id, label, multiline, required in TARGET_REVIEW_FIELDS
        ],
    )


def is_target_review_form(request: FormRequest) -> bool:
    """True when a form holds exactly the Target review fields."""
    return [field.id for field in request.fields] == [
        field_id for field_id, *_ in TARGET_REVIEW_FIELDS
    ]


def _behaviour_warnings(specification: Specification) -> list[Warning]:
    measured = len(specification.measured_behaviours())
    if not measured:
        return [
            Warning(text="Select at least one Behaviour to continue.", blocking=True)
        ]
    if measured > SUGGESTED_BEHAVIOURS:
        return [
            Warning(
                text=(
                    f"You selected {measured} behaviours. "
                    f"We suggest {SUGGESTED_BEHAVIOURS} or fewer."
                )
            )
        ]
    return []


def behaviours_screen(specification: Specification, message: str) -> ChoiceRequest:
    """Review and measurement selection in one screen.

    Each card shows a behaviour and carries its own measurement tick — the "which of these do
    we measure" decision, the only real decision in the interview. `multi=True`: every tick was
    composed by the package and writes one independent flag on a different behaviour, so nothing
    can invalidate anything else, and several ticks can travel together.

    `selected` reflects `measured`, so both doors draw a checkbox (drafted and form behaviours
    start measured). Continue is disabled while nothing is measured: with no measured behaviour
    there is nothing to write criteria for.
    """
    cards: list[AnyCard] = []
    sections = [
        ReviewSection(
            id="behaviours",
            title="Features / Expected Behaviours",
            options=[_add("features", "Add a Feature")],
        )
    ]
    # The last Feature cannot be deleted: with no Feature, this screen drafts a new set.
    only_feature = len(specification.features) == 1
    for feature in specification.features:
        sections.append(
            ReviewSection(
                id=feature.id,
                title=_section(feature),
                parent="behaviours",
                options=[
                    _add(feature.id, f"Add a Behaviour to {feature.name}"),
                    _edit(feature.id, feature.name),
                    _remove(
                        specification,
                        feature.id,
                        feature.name,
                        enabled=not only_feature,
                    ),
                ],
            )
        )
        for behaviour in feature.behaviours:
            cards.append(
                BehaviourCard(
                    id=behaviour.id,
                    profile_section_id="behaviours",
                    section=_section(feature),
                    section_id=feature.id,
                    title=behaviour.name,
                    selected=behaviour.measured,
                    components=[CardText(text=behaviour.description)],
                    options=[
                        Option(
                            id=OptionId(action="tick", target=behaviour.id),
                            label=f"Measure {behaviour.name}",
                            selected=behaviour.measured,
                            patch=_wizard_patch(
                                _behaviour_path(
                                    specification, behaviour.id, "measured"
                                ),
                                not behaviour.measured,
                            ),
                        ),
                        _edit(behaviour.id, behaviour.name),
                        _remove(
                            specification,
                            behaviour.id,
                            behaviour.name,
                            enabled=len(specification.behaviours()) > 1,
                        ),
                    ],
                )
            )

    return ChoiceRequest(
        profile_section_id="behaviours",
        feedback_placeholder="Add a new feature that describes…",
        prompt=message,
        cards=cards,
        sections=sections,
        multi=True,
        footer=f"{len(specification.measured_behaviours())} behaviours selected",
        warnings=_behaviour_warnings(specification),
        # Readiness through this review requires a complete Target and at least one
        # measured Behaviour.
        options=[
            _back(),
            _continue(_ready_through(specification, InterviewStep.BEHAVIOURS)),
        ],
        instruction=BEHAVIOUR_INSTRUCTION,
    )


# ── step 2 · criteria ──────────────────────────────────────────────────────


def _criterion_components(
    specification: Specification, behaviour: Behaviour, *, actions: bool
) -> list[AnyCardComponent]:
    from metis.wizard.application.matching.matcher import default_grader_args

    components: list[AnyCardComponent] = []
    for criterion in behaviour.criteria:
        settings = {**default_grader_args(criterion), **criterion.grader_args}
        grader = (
            criterion.grader_fqn.rsplit(".", 1)[-1] if criterion.grader_fqn else None
        )
        details: list[AnyCardComponent] = [
            CardText(text=criterion.description),
            # Grader details support the Criterion; they are not what the user reviews.
            CardDetails(
                title=f"Grader: {grader or 'Not selected'}",
                muted=True,
                components=[
                    CardText(
                        label="Grader", text=criterion.grader_fqn or "Not selected"
                    ),
                    *[
                        CardText(label=name, text=json.dumps(value, ensure_ascii=False))
                        for name, value in settings.items()
                    ],
                ],
            ),
        ]
        if actions:
            details.append(
                CardOptionGroup(
                    options=[
                        _edit(criterion.id, criterion.name),
                        # A measured Behaviour keeps at least one Criterion, so Continue
                        # stays available. Add a new one first to replace the last one.
                        _remove(
                            specification,
                            criterion.id,
                            criterion.name,
                            enabled=len(behaviour.criteria) > 1,
                        ),
                    ]
                )
            )
        components.append(
            CardDetails(title=criterion.name, expanded=True, components=details)
        )
    return components


def _criteria_placeholder(specification: Specification) -> str:
    measured = specification.measured_behaviours()
    if measured:
        return f"Add a new criterion to {measured[0].name}…"
    return "Add a new criterion that checks…"


def criteria_screen(specification: Specification, message: str) -> ChoiceRequest:
    """Keep Feature groups and Behaviour identity while reviewing Criteria."""
    cards: list[AnyCard] = []
    sections = [ReviewSection(id="behaviours", title="Features / Expected Behaviours")]

    for feature in specification.features:
        sections.append(
            ReviewSection(
                id=feature.id,
                title=_section(feature),
                parent="behaviours",
                options=[_edit(feature.id, feature.name)],
            )
        )
        for behaviour in feature.behaviours:
            card = BehaviourCard(
                id=behaviour.id,
                profile_section_id="behaviours",
                section=_section(feature),
                section_id=feature.id,
                title=behaviour.name,
                components=[
                    CardText(text=behaviour.description),
                    *_criterion_components(
                        specification, behaviour, actions=behaviour.measured
                    ),
                ],
            )
            if behaviour.measured:
                card.options = [
                    _edit(behaviour.id, behaviour.name),
                    _add(behaviour.id, f"Add a Criterion to {behaviour.name}"),
                ]
            else:
                # Drawn with no actions — visible so you can see what you left out,
                # dormant so it costs nothing.
                card.note = "Not selected. Tasks cannot use these Criteria."
            cards.append(card)

    return ChoiceRequest(
        profile_section_id="behaviours",
        feedback_placeholder=_criteria_placeholder(specification),
        prompt=message,
        cards=cards,
        sections=sections,
        multi=False,
        instruction=CRITERIA_INSTRUCTION,
        options=[
            _back(),
            _continue(_ready_through(specification, InterviewStep.CRITERIA)),
        ],
    )


# ── step 3 · personas ──────────────────────────────────────────────────────


def personas_screen(specification: Specification, message: str) -> ChoiceRequest:
    # The last Persona cannot be deleted: with no Persona, this screen drafts a new set.
    only_one = len(specification.personas) == 1
    cards: list[AnyCard] = [
        BehaviourCard(
            id=persona.id,
            profile_section_id="personas",
            title=persona.name,
            show_id=False,
            components=[
                CardText(text=persona.description),
                *_more_information(persona.metadata),
            ],
            options=[
                _edit(persona.id, persona.name),
                _remove(specification, persona.id, persona.name, enabled=not only_one),
            ],
        )
        for persona in specification.personas
    ]

    return ChoiceRequest(
        profile_section_id="personas",
        feedback_placeholder=(
            f"Make {specification.personas[0].name} more…"
            if specification.personas
            else "Add a persona who…"
        ),
        prompt=message,
        cards=cards,
        sections=[
            ReviewSection(
                id="personas",
                title="Personas",
                options=[_add("personas", "Add a Persona")],
            )
        ],
        multi=False,
        options=[
            _back(),
            _continue(_ready_through(specification, InterviewStep.PERSONAS)),
        ],
        instruction=PERSONAS_INSTRUCTION,
    )


# ── step 4 · scenarios ───────────────────────────────────────────────────────


def scenarios_screen(specification: Specification, message: str) -> ChoiceRequest:
    """The Scenarios as cards. Continue matches them with Personas on the next review."""
    # The last Scenario cannot be deleted: with no Scenario, this screen drafts a new set.
    only_one = len(specification.scenarios) == 1
    cards: list[AnyCard] = [
        BehaviourCard(
            id=scenario.id,
            profile_section_id="scenarios",
            title=scenario.name,
            show_id=False,
            components=[
                CardText(text=scenario.description),
                *_more_information(scenario.metadata),
            ],
            options=[
                _edit(scenario.id, scenario.name),
                _remove(
                    specification, scenario.id, scenario.name, enabled=not only_one
                ),
            ],
        )
        for scenario in specification.scenarios
    ]
    return ChoiceRequest(
        profile_section_id="scenarios",
        feedback_placeholder="Add a scenario where the user…",
        prompt=message,
        cards=cards,
        sections=[
            ReviewSection(
                id="scenarios",
                title="Scenarios",
                options=[_add("scenarios", "Add a Scenario")],
            ),
        ],
        multi=False,
        instruction=SCENARIOS_INSTRUCTION,
        options=[
            _back(),
            _continue(_ready_through(specification, InterviewStep.SCENARIOS)),
        ],
    )


# ── step 5 · test cases ──────────────────────────────────────────────────────


def free_test_case_pairs(
    specification: Specification, *, ignore: str | None = None
) -> list[tuple[str, str]]:
    """Persona and Scenario pairs that no Test Case uses yet, in screen order."""
    used = {
        (task.persona_ref, task.scenario_ref)
        for task in specification.tasks
        if task.id != ignore
    }
    return [
        (persona.id, scenario.id)
        for scenario in specification.scenarios
        for persona in specification.personas
        if (persona.id, scenario.id) not in used
    ]


def _behaviour_choices(specification: Specification) -> list[FormChoice]:
    """Measured Behaviours by id, with the description as the hint."""
    return [
        FormChoice(value=b.id, label=b.id, hint=f"{b.name}: {b.description}")
        for b in specification.measured_behaviours()
    ]


def task_form(
    specification: Specification,
    task_id: str | None,
    available_fixture_names: list[str] | None = None,
) -> FormRequest:
    """Edit one Test Case row in place. A pair that another Test Case uses is refused.

    Each field names the column of the cell it edits, so a door can draw the form inside the
    row. A new Test Case starts on the first free pair and covers all measured Behaviours.
    """
    task = specification.task(task_id) if task_id else None
    free = free_test_case_pairs(specification, ignore=task_id)
    persona_ref, scenario_ref = (
        (task.persona_ref, task.scenario_ref) if task else free[0] if free else ("", "")
    )
    behaviours = (
        task.behaviour_refs
        if task
        else [b.id for b in specification.measured_behaviours()]
    )
    return FormRequest(
        prompt=(
            f"Edit {task.id}." if task else "Choose the settings for the new Test Case."
        ),
        purpose="edit" if task else "add",
        target=task.id if task else "tasks",
        cancellable=True,
        fields=[
            FormField(
                id="persona",
                label="Persona",
                column="Persona",
                multiline=False,
                required=True,
                value=persona_ref,
                choices=[
                    FormChoice(value=persona.id, label=persona.name)
                    for persona in specification.personas
                ],
            ),
            FormField(
                id="scenario",
                label="Scenario",
                column="Scenario",
                multiline=False,
                required=True,
                value=scenario_ref,
                choices=[
                    FormChoice(value=scenario.id, label=scenario.name)
                    for scenario in specification.scenarios
                ],
            ),
            FormField(
                id="behaviours",
                label="Behaviours",
                column="Behaviours",
                multiline=False,
                multiple=True,
                required=True,
                value=",".join(behaviours),
                choices=_behaviour_choices(specification),
            ),
            FormField(
                id="trials",
                label="Trials",
                column="Trials",
                multiline=False,
                input_type="integer",
                required=True,
                value=str(task.num_trials if task else DEFAULT_TRIALS),
                help=f"A whole number from {TRIALS_MIN} to {TRIALS_MAX}.",
            ),
            FormField(
                id="files",
                label="Files",
                column="Files",
                multiline=False,
                multiple=True,
                value=",".join(task.fixtures if task else []),
                choices=[
                    FormChoice(value=name, label=name)
                    for name in (available_fixture_names or [])
                ],
            ),
        ],
        used_combinations=[
            {"persona": item.persona_ref, "scenario": item.scenario_ref}
            for item in specification.tasks
            if item.id != task_id
        ],
    )


def _test_case_card(
    specification: Specification,
    task: Task,
    available_fixture_names: list[str] | None,
    *,
    included: bool,
) -> ScenarioCard:
    """One Test Case as a table row. The checkbox includes it in the evaluation."""
    scenario = specification.scenario(task.scenario_ref)
    persona = specification.persona(task.persona_ref)
    return ScenarioCard(
        id=task.id,
        profile_section_id="test-cases",
        title=task.id,
        trials=task.num_trials,
        selected=included,
        columns=[
            CardColumn(
                title="Persona",
                summary=persona.name if persona else f"Unknown ({task.persona_ref})",
            ),
            CardColumn(
                title="Scenario",
                summary=scenario.name if scenario else f"Unknown ({task.scenario_ref})",
            ),
            CardColumn(
                title="Behaviours",
                summary=", ".join(task.behaviour_refs) or "None",
                components=[
                    CardOptionGroup(
                        options=[
                            Option(
                                id=OptionId(action="cover", target=task.id, via=b.id),
                                label=b.id,
                                hint=f"{b.name}: {b.description}"
                                if b.measured
                                else f"{b.name} (not measured)",
                                selected=b.id in task.behaviour_refs,
                                patch=_wizard_patch(
                                    f"tasks[{task.id}].behaviour_refs",
                                    sorted(set(task.behaviour_refs) ^ {b.id}),
                                ),
                            )
                            for b in specification.behaviours()
                            if b.measured or b.id in task.behaviour_refs
                        ]
                        + [
                            Option(
                                id=OptionId(action="cover", target=task.id, via=ref),
                                label=ref,
                                hint="Missing. Select to remove this reference.",
                                selected=True,
                                patch=_wizard_patch(
                                    f"tasks[{task.id}].behaviour_refs",
                                    [bid for bid in task.behaviour_refs if bid != ref],
                                ),
                            )
                            for ref in task.behaviour_refs
                            if specification.behaviour(ref) is None
                        ],
                    )
                ],
            ),
            CardColumn(
                title="Trials",
                summary=str(task.num_trials),
                components=[
                    CardNumberField(
                        label="Trials",
                        id=OptionId(action="trials", target=task.id),
                        value=task.num_trials,
                        min=TRIALS_MIN,
                        max=TRIALS_MAX,
                    )
                ],
            ),
            CardColumn(
                title="Files",
                summary=", ".join(task.fixtures) or "None",
                components=[
                    CardUploadField(
                        label="Files sent to your target",
                        id=OptionId(action="files", target=task.id),
                        value=list(task.fixtures),
                        available=list(available_fixture_names or []),
                    )
                ],
            ),
        ],
        options=[
            Option(
                id=OptionId(action="tick", target=task.id),
                label=f"Include {task.id}",
                selected=included,
            ),
            _edit(task.id, task.id),
            _remove(specification, task.id, task.id),
        ],
    )


def task_review_screen(
    specification: Specification,
    message: str,
    available_fixture_names: list[str] | None = None,
    excluded: set[str] | None = None,
) -> ChoiceRequest:
    """The Test Cases as a table. Each row pairs one Persona with one Scenario."""
    excluded = excluded or set()
    # The last review checks the whole Specification, so Continue completes a runnable one.
    gaps = specification_readiness(specification, excluded)
    cards: list[AnyCard] = [
        _test_case_card(
            specification,
            task,
            available_fixture_names,
            included=task.id not in excluded,
        )
        for task in specification.tasks
    ]
    included = [task for task in specification.tasks if task.id not in excluded]
    return ChoiceRequest(
        profile_section_id="test-cases",
        feedback_placeholder="Add a test case where…",
        prompt=message,
        cards=cards,
        sections=[
            ReviewSection(
                id="test-cases",
                title="Test Cases",
                options=[
                    _add(
                        "tasks",
                        "Add a Test Case",
                        enabled=bool(free_test_case_pairs(specification)),
                    )
                ],
            ),
        ],
        multi=True,
        warnings=[
            Warning(text=g.message, source=WarningSource.DOCUMENT, blocking=True)
            for g in gaps
        ],
        footer=(
            f"{len(included)} of {len(specification.tasks)} Test Cases selected, "
            f"{format_trials(sum(task.num_trials for task in included))}"
        ),
        instruction=TEST_CASES_INSTRUCTION,
        options=[_back(), _continue(not gaps)],
    )
