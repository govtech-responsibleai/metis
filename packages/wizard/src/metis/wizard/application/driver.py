"""The interview, as a state machine.

`compose(state)` builds the screen for wherever the interview is. `handle(state, req, resp)`
applies what came back and decides where to go next.

Most responses cost no model call: every tick, chip and stepper arrives carrying a patch the
package composed before the screen was ever drawn, so applying it is a dictionary lookup. The
model is called at five points only — clarify, and the four drafting steps.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from metis.wizard.application import config, screens
from metis.wizard.application.interviewer import Interviewer, InterviewerOutputError
from metis.wizard.application.readiness import missing_criteria_paths
from metis.wizard.contracts.conversation import (
    AnyRequest,
    AnyResponse,
    CardFieldValue,
    CardNumberField,
    CardUploadField,
    ChatRequest,
    ChatResponse,
    ChoiceRequest,
    ChoiceResponse,
    FormField,
    FormRequest,
    Option,
    OptionId,
    Warning,
    WarningSource,
    editable_fields_of,
    options_of,
)
from metis.wizard.contracts.interview_state import InterviewState
from metis.wizard.contracts.output import (
    BehaviourDraft,
    CriterionDraft,
    FeatureDraft,
    PersonaDraft,
    ScenarioDraft,
    StepResult,
)
from metis.wizard.domain import materializer, nodes
from metis.wizard.domain.applier import apply, sanitise
from metis.wizard.domain.cascade import Impact, impacts_for
from metis.wizard.domain.documents import normalize_fixture_name
from metis.wizard.domain.patch import Patch, PatchOp, PatchOrigin
from metis.wizard.domain.permissions import InterviewStep

if TYPE_CHECKING:
    from collections.abc import Callable

    from metis.wizard.contracts.interview_state import InterviewMessage
    from metis.wizard.domain.specification import (
        Behaviour,
        Criterion,
        Feature,
        Persona,
        Scenario,
        Specification,
    )


class DriverState(InterviewState):
    """The client-held state, plus the one field the driver alone needs: where the interview is.

    `InterviewState` carries no stage — the stage is derived, so the client never stores it. But
    the state machine below reads and writes a stage on every turn, so a turn lifts the client
    value into this subclass, runs the driver on it, and projects the result back down without
    the stage. The driver therefore needs no knowledge of derivation, and the client contract
    keeps its single source of truth. See `application.turn`.
    """

    step: InterviewStep


_NEXT_STEP = {
    InterviewStep.CLARIFY: InterviewStep.BEHAVIOURS,
    InterviewStep.BEHAVIOURS: InterviewStep.CRITERIA,
    InterviewStep.CRITERIA: InterviewStep.PERSONAS,
    InterviewStep.PERSONAS: InterviewStep.SCENARIOS,
    InterviewStep.SCENARIOS: InterviewStep.TEST_CASES,
    InterviewStep.TEST_CASES: InterviewStep.DONE,
}

# Each review screen after Clarify shows Back, and this map tells where it goes. The map is
# explicit so that the door's navigation contract is easy to inspect. Clarify and DONE are not
# keys: Clarify is the first step, and DONE shows no screen.
PREVIOUS_STEP = {
    InterviewStep.BEHAVIOURS: InterviewStep.CLARIFY,
    InterviewStep.CRITERIA: InterviewStep.BEHAVIOURS,
    InterviewStep.PERSONAS: InterviewStep.CRITERIA,
    InterviewStep.SCENARIOS: InterviewStep.PERSONAS,
    InterviewStep.TEST_CASES: InterviewStep.SCENARIOS,
}

AFTER_BEHAVIOURS = frozenset(
    {
        InterviewStep.CRITERIA,
        InterviewStep.PERSONAS,
        InterviewStep.SCENARIOS,
        InterviewStep.TEST_CASES,
    }
)

# A drafting call writes only its own collection. It cannot add a Feature, a Behaviour or a
# Criterion, so nothing becomes measured without the user.
_PERSONA_DRAFT_PATHS = frozenset({"personas"})
_SCENARIO_DRAFT_PATHS = frozenset({"scenarios"})
# Test Case drafting adds Test Cases only. It cannot change a Persona or a Scenario.
_TEST_CASE_DRAFT_PATHS = frozenset({"tasks"})

_DEFAULT_MESSAGES = {
    InterviewStep.BEHAVIOURS: "Choose what to evaluate.",
    InterviewStep.CRITERIA: "Here are the current acceptance criteria.",
    InterviewStep.PERSONAS: "Here are the current personas.",
    InterviewStep.SCENARIOS: "Here are the current scenarios.",
    InterviewStep.TEST_CASES: "Here are the current test cases.",
}

_CLARIFY_TARGET_PATHS = frozenset(
    {
        "target.name",
        "target.users",
        "target.description",
        "target.detail",
    }
)


def _clarify_questions_asked(history: list[InterviewMessage]) -> int:
    """Count only questions composed by the model, not the package opening line."""
    count = sum(1 for message in history if message.role == "assistant")
    if history and history[0].role == "assistant":
        try:
            opening = config.opening_question()
        except RuntimeError:
            opening = ""
        if opening and history[0].text == opening:
            count -= 1
    return max(0, count)


@dataclass
class StepDriver:
    """Composes screens and advances the interview.

    `pending_warnings` is where a RUNTIME warning waits between being raised and being drawn.
    It is the one piece of state that crosses a turn, and it is deliberately shown once: every
    runtime warning so far describes something that already happened rather than something
    still true.
    """

    interviewer: Interviewer
    matcher: object | None = None  # a GraderMatcher; None leaves criteria unmatched
    pending_warnings: list[Warning] = field(default_factory=list)
    model_error: InterviewerOutputError | None = field(default=None, repr=False)

    # ── composing ──────────────────────────────────────────────────────────

    def compose(self, state: DriverState) -> AnyRequest:
        """Compose the next screen and stamp its step header.

        Stamping here rather than in each screen builder is deliberate: every request the
        interview produces — the clarify chat, the five review screens and any cascade
        question raised mid-step — leaves through this one method, so the header cannot go
        missing on one path or disagree with another. A cascade question raised while
        standing at criteria inherits the criteria header, which is what keeps it anchored.
        """
        request = self._compose(state)
        # The missing Target fields finish Clarify, so their form keeps the Clarify header. The
        # Behaviours header comes with the review, after the fields are filled in.
        step = (
            InterviewStep.CLARIFY
            if state.step is InterviewStep.BEHAVIOURS
            and isinstance(request, FormRequest)
            and request == screens.target_completion_form(state.specification)
            else state.step
        )
        screens.stamp_step(request, step)
        return request

    def _compose(self, state: DriverState) -> AnyRequest:
        specification = state.specification
        step = state.step

        if step is InterviewStep.CLARIFY:
            # The package-owned opening line is an assistant message for context, but it is not a
            # question composed by the model and must not consume the clarify budget.
            if not any(t.role == "user" for t in state.history):
                return ChatRequest(prompt=config.opening_question())

            asked = _clarify_questions_asked(state.history)
            cap = config.clarify_turn_cap()
            if asked <= cap:
                result = self.interviewer.clarify(
                    specification,
                    state.history,
                    context=state.context,
                )
                self._run(
                    state,
                    result,
                    allowed_paths=_CLARIFY_TARGET_PATHS,
                )
                # The call at the bound is record-only. Its patches are required, but its
                # message must never become a sixth question or enter the transcript.
                if asked < cap and not result.done and result.message:
                    return ChatRequest(prompt=result.message)
            # Either the model is finished or the cap is reached. Draft regardless.
            state.step = InterviewStep.BEHAVIOURS
            step = InterviewStep.BEHAVIOURS

        if step is InterviewStep.BEHAVIOURS:
            # A model can finish clarification without filling required Target fields.
            # Collect them directly so the review cannot strand the user at Continue.
            completion = screens.target_completion_form(specification)
            if completion is not None:
                return completion
            if not specification.features:
                self._try(
                    lambda: self.interviewer.draft_behaviours(
                        specification,
                        state.history,
                        context=state.context,
                    ),
                    state,
                )
            return self._attach(
                screens.behaviours_screen(
                    specification, self._message(state, InterviewStep.BEHAVIOURS)
                )
            )

        if step is InterviewStep.CRITERIA:
            return self._attach(
                screens.criteria_screen(
                    specification, self._message(state, InterviewStep.CRITERIA)
                )
            )

        if step is InterviewStep.PERSONAS:
            if not specification.personas:
                self._try(
                    lambda: self.interviewer.draft_personas(
                        specification, context=state.context
                    ),
                    state,
                    allowed_paths=_PERSONA_DRAFT_PATHS,
                    allowed_ops=frozenset({PatchOp.ADD}),
                )
            return self._attach(
                screens.personas_screen(
                    specification, self._message(state, InterviewStep.PERSONAS)
                )
            )

        if step is InterviewStep.SCENARIOS:
            if not specification.scenarios:
                self._try(
                    lambda: self.interviewer.draft_scenarios(
                        specification, context=state.context
                    ),
                    state,
                    allowed_paths=_SCENARIO_DRAFT_PATHS,
                    allowed_ops=frozenset({PatchOp.ADD}),
                )
            return self._attach(
                screens.scenarios_screen(
                    specification, self._message(state, InterviewStep.SCENARIOS)
                )
            )

        if step is InterviewStep.TEST_CASES:
            if not specification.tasks:
                self.draft_test_cases(state)
            return self._attach(
                screens.task_review_screen(
                    specification,
                    self._message(state, InterviewStep.TEST_CASES),
                    state.context.document_names,
                    state.excluded_tasks,
                )
            )

        raise RuntimeError(f"Nothing to compose at step {step}.")

    def complete_target(self, state: DriverState) -> None:
        """Fill required Target fields from evidence during best-effort completion."""
        missing = frozenset(
            f"target.{name}"
            for name in ("name", "description")
            if not getattr(state.specification.target, name)
        )
        if not missing:
            return
        self._try(
            lambda: self.interviewer.chat(
                state.specification,
                "clarify",
                "Complete these required Target fields from the opening description and "
                "supporting documents: "
                + ", ".join(sorted(missing))
                + ". Use a short descriptive name if the evidence gives no product name. "
                "Return SET patches for these fields only. Do not ask another question.",
                None,
                context=state.context,
            ),
            state,
            allowed_paths=missing,
            allowed_ops=frozenset({PatchOp.SET}),
        )

    @staticmethod
    def _message(state: DriverState, step: InterviewStep) -> str:
        return state.step_messages.get(step, _DEFAULT_MESSAGES[step])

    def _attach(self, request: ChoiceRequest) -> ChoiceRequest:
        """Drain the runtime warnings onto the next screen drawn.

        Shown once: they are events, not conditions, so nothing recomputes them and nothing
        should carry them forward.
        """
        if self.pending_warnings:
            request.warnings = [*self.pending_warnings, *request.warnings]
            self.pending_warnings = []
        return request

    # ── handling ───────────────────────────────────────────────────────────

    def handle(
        self, state: DriverState, request: AnyRequest, response: AnyResponse
    ) -> None:
        previous = state.pending
        if isinstance(request, ChatRequest):
            self._handle_chat(state, request, response)
        elif isinstance(request, FormRequest):
            self._handle_form(state, request, response)
        else:
            self._handle_choice(state, request, response)
        # A form that this turn opened is still in progress, so nothing is drafted yet.
        if state.pending is None or state.pending is previous:
            self.draft_missing_criteria(state)
        # Every removal path ends here, so an exclusion never names a deleted Test Case.
        state.excluded_tasks &= {task.id for task in state.specification.tasks}

    def _handle_chat(
        self, state: DriverState, request: ChatRequest, response: AnyResponse
    ) -> None:
        text = getattr(response, "text", "")
        if state.step is InterviewStep.CLARIFY:
            return  # the answer is in history; the next compose() asks the next question

        # A chat raised from a criteria card carries that behaviour's id; a screen-level chat
        # carries None. The id both tells the model what the user is looking at and confines
        # the edit to that behaviour's own criteria — so "Chat about these criteria" cannot
        # reach across and rewrite a different card's.
        target = request.target
        try:
            result = self.interviewer.chat(
                state.specification,
                str(state.step),
                text,
                target,
                context=state.context,
            )
        except InterviewerOutputError as exc:
            self.model_error = exc
            # Keep the direct driver API's warning behavior. The turn transaction checks
            # `model_error` and converts this into a typed retryable failure.
            return self._refuse_chat()
        if target is not None:
            if state.step is InterviewStep.CRITERIA:
                result = self._confine_to_behaviour(result, target)
            else:
                feature = state.specification.feature_of(target)
                prefix = (
                    f"features[{feature.id}].behaviours[{target}]"
                    if feature
                    else f"features[{target}]"
                )
                kept = [
                    patch
                    for patch in result.patches
                    if patch.path == prefix or patch.path.startswith(prefix + ".")
                ]
                if len(kept) != len(result.patches):
                    self.pending_warnings.append(
                        Warning(
                            text="I left out a change outside the selected item. Changes inside this item were applied.",
                            source=WarningSource.RUNTIME,
                        )
                    )
                result = result.model_copy(update={"patches": kept})
        self._run(state, result, request=text, user_message=True)

    def _refuse_chat(self) -> None:
        """Change nothing and say so, when a chat could not be answered by the model."""
        self.pending_warnings.append(
            Warning(
                text=(
                    "I couldn't work out a change from that just then, so I've left your "
                    "specification exactly as it is. Try saying it again."
                ),
                source=WarningSource.RUNTIME,
                blocking=False,
            )
        )

    def _confine_to_behaviour(
        self, result: StepResult, behaviour_id: str
    ) -> StepResult:
        """Drop any patch a scoped criteria chat produced that reaches outside this behaviour.

        The applier already enforces which *fields* the criteria step may write; this enforces
        which *behaviour*. A patch under `behaviours[<id>].criteria` stays; anything else — a
        sibling behaviour, the tree, a persona — is dropped and reported, because a chat the
        user opened on one card must not silently edit another.
        """
        prefix = f"behaviours[{behaviour_id}].criteria"
        kept = [p for p in result.patches if prefix in p.path]
        for dropped in result.patches:
            if prefix not in dropped.path:
                self.pending_warnings.append(
                    Warning(
                        text=(
                            "That change reached outside the criteria you were editing, so "
                            "I've left it out. Everything for this behaviour still applied."
                        ),
                        source=WarningSource.RUNTIME,
                        blocking=False,
                    )
                )
        return result.model_copy(update={"patches": kept})

    def _configure_changes(
        self, state: DriverState, before: Specification, request: str = ""
    ) -> None:
        from metis.wizard.application.matching.matcher import (
            default_grader_args,
            rematch,
            validate_grader_args,
        )

        if self.matcher is None:
            return
        for behaviour in state.specification.behaviours():
            for criterion in behaviour.criteria:
                previous = before.criterion(criterion.id)
                if previous and (previous.description, previous.name) == (
                    criterion.description,
                    criterion.name,
                ):
                    continue
                rematch(criterion, self.matcher)  # type: ignore[arg-type]
                criterion.grader_args = default_grader_args(criterion)
                configured = self.interviewer.configure_criterion(
                    criterion,
                    previous,
                    state.specification,
                    request,
                    context=state.context,
                )
                try:
                    validate_grader_args(
                        criterion.grader_fqn,
                        configured.grader_args,
                        description=configured.description,
                    )
                except ValueError as exc:
                    raise InterviewerOutputError(
                        f"Invalid assessment settings: {exc}"
                    ) from exc
                criterion.description = configured.description
                criterion.grader_args = configured.grader_args

    def _handle_form(
        self, state: DriverState, request: FormRequest, response: AnyResponse
    ) -> None:
        """Text typed into a form is used as-is — the model never sees it, so it cannot
        rewrite it. Everything created here is stamped FORM."""
        if isinstance(response, ChoiceResponse):
            # Back while a form is open: the turn validated that this is a bare Back. One
            # turn closes the form with no change, then goes back.
            return self._go_back(state)
        if getattr(response, "cancelled", False):
            if screens.is_target_review_form(request):
                # Cancel on the Target review returns to the Behaviour review with no change.
                state.step = InterviewStep.BEHAVIOURS
            return
        values = getattr(response, "values", {}) or {}
        specification = state.specification

        if state.step is InterviewStep.CLARIFY and screens.is_target_review_form(
            request
        ):
            return self._review_target(state, request, values)

        if state.step is InterviewStep.BEHAVIOURS and request.target is None:
            completion = screens.target_completion_form(specification)
            if completion is not None and request.fields == completion.fields:
                apply(
                    specification,
                    [
                        Patch(
                            op=PatchOp.SET,
                            path=field.id,
                            value=values[field.id],
                            origin=PatchOrigin.WIZARD,
                        )
                        for field in completion.fields
                        if isinstance(values.get(field.id), str)
                        and values[field.id].strip()
                    ],
                    issued_ids=state.issued_ids,
                    user_typed=state.user_typed,
                )
                return

        # Every other form names the node it writes. An add names the parent or a collection
        # key, and an edit names the node itself.
        if request.target is None:
            return self._refuse_form_target()
        if request.purpose == "edit":
            return self._edit_typed(state, request, values)
        return self._add_typed(state, request, values)

    def _review_target(
        self, state: DriverState, request: FormRequest, values: dict[str, Any]
    ) -> None:
        """Apply the changed Target fields, then return to the Behaviour review.

        Only a changed field becomes a patch. Values are compared without surrounding whitespace,
        so a stored value with a trailing newline is unchanged.
        An edit that affects derived content adjusts that content in this turn, the same as a
        correction. With no change, nothing is drafted again.
        """
        target = state.specification.target
        patches = []
        for form_field in request.fields:
            value = values.get(form_field.id)
            if not isinstance(value, str):
                continue
            value = value.strip()
            current = getattr(target, form_field.id.split(".", 1)[1]) or ""
            if value == current.strip() or (form_field.required and not value):
                continue
            patches.append(
                Patch(
                    op=PatchOp.SET,
                    path=form_field.id,
                    value=value,
                    origin=PatchOrigin.WIZARD,
                )
            )
        before = state.specification.model_copy(deep=True)
        outcome = apply(
            state.specification,
            patches,
            issued_ids=state.issued_ids,
            user_typed=state.user_typed,
        )
        impacts = impacts_for(before, outcome.applied)
        if impacts:
            self._adjust_derived(state, impacts)
        self._configure_changes(state, before)
        state.step = InterviewStep.BEHAVIOURS

    # ── the review actions: add, edit, remove ───────────────────────────────

    def _open(self, state: DriverState, form: FormRequest) -> None:
        screens.stamp_step(form, state.step)
        state.pending = form

    def _open_add_form(self, state: DriverState, target: str | None) -> None:
        """Open the form for a new child of `target`, or a new item of a collection."""
        specification = state.specification
        kind = nodes.COLLECTIONS.get(target or "")
        found = nodes.locate(specification, target) if target and not kind else None
        if kind == "task":
            if not screens.free_test_case_pairs(specification):
                return self._refuse_field_edit(
                    "Every Persona and Scenario pair already has a Test Case. "
                    "Add a Persona or a Scenario first."
                )
            return self._open(
                state,
                screens.task_form(specification, None, state.context.document_names),
            )
        if kind in ("persona", "scenario"):
            noun = "Persona" if kind == "persona" else "Scenario"
            return self._open(
                state,
                FormRequest(
                    prompt=f"Describe the new {noun}. I will use exactly what you write.",
                    target=target,
                    cancellable=True,
                    fields=_profile_fields(None),
                ),
            )
        if kind == "feature" or (found and found.kind in ("feature", "behaviour")):
            noun = {
                "feature": "Behaviour",
                "behaviour": "Criterion",
            }.get(found.kind if found else "", "Feature")
            fields = (
                [
                    FormField(id="name", label="Name", multiline=False, required=True),
                    FormField(id="description", label="Assessment", required=True),
                ]
                if noun == "Criterion"
                else _named_fields(None)
            )
            parent = f" to {found.node.name}" if found else ""  # type: ignore[union-attr]
            return self._open(
                state,
                FormRequest(
                    prompt=f"Add a {noun}{parent}. I will use exactly what you write.",
                    target=target,
                    cancellable=True,
                    fields=fields,
                ),
            )
        return self._refuse_form_target()

    def _open_edit_form(self, state: DriverState, target: str | None) -> None:
        """Open the form that edits the node `target` names, with its current values."""
        specification = state.specification
        found = nodes.locate(specification, target or "")
        if found is None:
            return self._refuse_form_target()
        if found.kind == "task":
            return self._open(
                state,
                screens.task_form(
                    specification, found.node.id, state.context.document_names
                ),
            )
        if found.kind == "criterion":
            return self._open_criterion_edit(state, found.node)  # type: ignore[arg-type]
        node = found.node
        fields = (
            _profile_fields(node)  # type: ignore[arg-type]
            if found.kind in ("persona", "scenario")
            else _named_fields(node)  # type: ignore[arg-type]
        )
        self._open(
            state,
            FormRequest(
                prompt=f"Edit {node.name}.",  # type: ignore[union-attr]
                target=node.id,
                purpose="edit",
                cancellable=True,
                fields=fields,
            ),
        )

    def _open_criterion_edit(self, state: DriverState, criterion: Criterion) -> None:
        from metis.wizard.application.criterion_forms import settings_fields

        try:
            fields = settings_fields(criterion)
        except ValueError as exc:
            return self._refuse_field_edit(str(exc))
        self._open(
            state,
            FormRequest(
                prompt="Edit the assessment and its settings. Keep their meanings consistent.",
                purpose="edit",
                cancellable=True,
                # The name comes first and is not in a group, so a door that edits in place puts
                # it where the Criterion title is. Grader settings stay in their closed group.
                fields=[
                    FormField(
                        id="name",
                        label="Name",
                        value=criterion.name,
                        multiline=False,
                        required=True,
                    ),
                    FormField(
                        id="description",
                        label="Assessment",
                        value=criterion.description,
                        required=True,
                    ),
                    *fields,
                ],
                target=criterion.id,
            ),
        )

    def _reopen(
        self,
        state: DriverState,
        request: FormRequest,
        values: dict[str, Any],
        text: str,
    ) -> None:
        """Keep a refused form open with what the user typed, and say why it was refused."""
        form = request.model_copy(deep=True)
        if not request.prompt.startswith(text):
            form.prompt = f"{text} {request.prompt}"
        for form_field in form.fields:
            if isinstance(values.get(form_field.id), str):
                form_field.value = values[form_field.id]
        self._open(state, form)

    def _edit_typed(
        self, state: DriverState, request: FormRequest, values: dict[str, Any]
    ) -> None:
        specification = state.specification
        found = nodes.locate(specification, request.target or "")
        if found is None:
            return self._refuse_form_target()
        if found.kind == "criterion":
            return self._edit_criterion(state, request, values, found.node)  # type: ignore[arg-type]
        if found.kind == "task":
            return self._save_task(state, request, values, found.node.id)

        fields: dict[str, object] = {
            "name": values.get("name", "").strip(),
            "description": values.get("description", "").strip(),
        }
        if found.kind in ("persona", "scenario"):
            metadata = _parse_metadata(values.get("metadata", ""))
            if metadata is None:
                return self._reopen(state, request, values, _METADATA_HELP)
            fields["metadata"] = metadata
        before = specification.model_copy(deep=True)
        state.user_typed.add(found.node.id)
        outcome = apply(
            specification,
            [
                Patch(
                    op=PatchOp.SET,
                    path=f"{found.path}.{name}",
                    value=value,
                    origin=PatchOrigin.WIZARD,
                )
                for name, value in fields.items()
            ],
            issued_ids=state.issued_ids,
            user_typed=state.user_typed,
        )
        impacts = impacts_for(before, outcome.applied)
        if impacts:
            self._adjust_derived(state, impacts)
        self._configure_changes(state, before)

    def _edit_criterion(
        self,
        state: DriverState,
        request: FormRequest,
        values: dict[str, Any],
        criterion: Criterion,
    ) -> None:
        from metis.wizard.application.criterion_forms import settings_values
        from metis.wizard.application.matching.matcher import validate_grader_args
        from metis.wizard.domain.specification import Criterion

        try:
            args = settings_values(request.fields, values, criterion.grader_args)
            candidate = Criterion.model_validate(
                {
                    **criterion.model_dump(),
                    "name": values.get("name", criterion.name),
                    "description": values.get("description", criterion.description),
                    "grader_args": args,
                }
            )
            validate_grader_args(
                candidate.grader_fqn, args, description=candidate.description
            )
        except (ValueError, TypeError) as exc:
            return self._refuse_field_edit(f"Invalid assessment settings: {exc}")
        state.user_typed.add(criterion.id)
        criterion.name = candidate.name
        criterion.description = candidate.description
        criterion.grader_args = candidate.grader_args

    def _add_typed(
        self, state: DriverState, request: FormRequest, values: dict[str, Any]
    ) -> None:
        """Create one node from a form, under the parent or in the collection it names."""
        specification = state.specification
        target = request.target or ""
        kind = nodes.COLLECTIONS.get(target)
        name = values.get("name", "").strip()
        description = values.get("description", "").strip()

        if kind == "task":
            return self._save_task(state, request, values, None)
        if kind in ("persona", "scenario"):
            metadata = _parse_metadata(values.get("metadata", ""))
            if metadata is None:
                return self._reopen(state, request, values, _METADATA_HELP)
            draft = (PersonaDraft if kind == "persona" else ScenarioDraft)(
                name=name, description=description, metadata=metadata
            )
            add = (
                materializer.add_persona
                if kind == "persona"
                else materializer.add_scenario
            )
            add(
                specification,
                draft,
                PatchOrigin.WIZARD,
                issued_ids=state.issued_ids,
                user_typed=state.user_typed,
            )
            return
        if kind == "feature":
            # A typed Feature starts with no Behaviours. Its heading offers the "+" for them.
            materializer.add_feature(
                specification,
                FeatureDraft.model_construct(
                    name=name, description=description, behaviours=[]
                ),
                PatchOrigin.WIZARD,
                issued_ids=state.issued_ids,
                user_typed=state.user_typed,
            )
            return

        found = nodes.locate(specification, target)
        if found is not None and found.kind == "feature":
            found.node.behaviours.append(  # type: ignore[union-attr]
                materializer.add_behaviour(
                    specification,
                    BehaviourDraft(name=name, description=description),
                    PatchOrigin.WIZARD,
                    issued_ids=state.issued_ids,
                    user_typed=state.user_typed,
                )
            )
            return
        if found is not None and found.kind == "behaviour":
            return self._add_typed_criterion(state, found.node, values)  # type: ignore[arg-type]
        return self._refuse_form_target()

    def _add_typed_criterion(
        self, state: DriverState, behaviour: Behaviour, values: dict[str, Any]
    ) -> None:
        """Add one directly authored assessment under its Behaviour, and give it a Grader.

        The text stays exactly as typed. The matcher picks the Grader and its default
        settings, the same as for a drafted Criterion, so Continue does not wait on it.
        """
        try:
            draft = CriterionDraft(
                name=values.get("name", "Criterion"),
                description=values.get("description", ""),
            )
        except ValueError as exc:
            return self._refuse_field_edit(str(exc))
        materializer.add_criterion(
            state.specification,
            behaviour,
            draft,
            PatchOrigin.WIZARD,
            issued_ids=state.issued_ids,
            user_typed=state.user_typed,
        )
        self._match_new(behaviour, {c.id for c in behaviour.criteria[:-1]})

    def _save_task(
        self,
        state: DriverState,
        request: FormRequest,
        values: dict[str, Any],
        task_id: str | None,
    ) -> None:
        """Create or re-pair one Test Case. A Persona and Scenario pair is used only once."""
        from metis.wizard.contracts.output import TaskDraft

        specification = state.specification
        persona_ref = values.get("persona", "")
        scenario_ref = values.get("scenario", "")
        if (
            specification.persona(persona_ref) is None
            or specification.scenario(scenario_ref) is None
        ):
            return self._reopen(
                state,
                request,
                values,
                "Choose a Persona and a Scenario from the lists.",
            )
        if any(
            (task.persona_ref, task.scenario_ref) == (persona_ref, scenario_ref)
            for task in specification.tasks
            if task.id != task_id
        ):
            return self._reopen(
                state,
                request,
                values,
                "Another Test Case already uses this Persona and Scenario. Choose another pair.",
            )
        settings = _task_settings(request, values)
        if isinstance(settings, str):
            return self._reopen(state, request, values, settings)
        behaviour_refs, num_trials, fixtures = settings
        if task_id is not None:
            task = specification.task(task_id)
            if task is None:
                return self._refuse_form_target()
            task.persona_ref, task.scenario_ref = persona_ref, scenario_ref
            task.behaviour_refs = behaviour_refs
            task.num_trials = num_trials
            task.fixtures = fixtures
            return
        try:
            created = materializer.add_task(
                specification,
                TaskDraft(
                    scenario_ref=scenario_ref,
                    persona_ref=persona_ref,
                    behaviour_refs=behaviour_refs,
                ),
                PatchOrigin.WIZARD,
                issued_ids=state.issued_ids,
                user_typed=state.user_typed,
            )
        except ValueError as exc:
            return self._reopen(state, request, values, str(exc))
        # The file names passed the portable-name check above. As in an edit, a file that
        # the user uploads in the same form is allowed; the door keeps its bytes.
        created.num_trials = num_trials
        created.fixtures = fixtures

    def draft_test_cases(self, state: DriverState) -> None:
        """Ask the model to match each Scenario that has no Test Case yet.

        The model picks the Personas that each Scenario runs with and the Behaviours that it
        really tests. Code then keeps the result runnable: a pair that a Test Case already uses
        is not added again, an unmeasured Behaviour is left out, and a Test Case left with no
        Behaviour covers all measured Behaviours. A Scenario that already has a Test Case is not
        matched again, so a Test Case that the user deleted does not come back.
        """
        specification = state.specification
        used = {task.scenario_ref for task in specification.tasks}
        if not specification.personas or all(
            scenario.id in used for scenario in specification.scenarios
        ):
            return
        before = {task.id for task in specification.tasks}
        self._try(
            lambda: self.interviewer.draft_test_cases(
                specification, context=state.context
            ),
            state,
            allowed_paths=_TEST_CASE_DRAFT_PATHS,
            allowed_ops=frozenset({PatchOp.ADD}),
        )
        measured = [b.id for b in specification.measured_behaviours()]
        pairs = {
            (task.persona_ref, task.scenario_ref)
            for task in specification.tasks
            if task.id in before
        }
        dropped: list[str] = []
        kept = []
        for task in specification.tasks:
            if task.id in before:
                kept.append(task)
                continue
            pair = (task.persona_ref, task.scenario_ref)
            if task.scenario_ref in used or pair in pairs:
                continue
            pairs.add(pair)
            dropped += [ref for ref in task.behaviour_refs if ref not in measured]
            task.behaviour_refs = [
                ref for ref in task.behaviour_refs if ref in measured
            ] or list(measured)
            kept.append(task)
        specification.tasks = kept
        if dropped:
            self.pending_warnings.append(
                Warning(
                    text=(
                        "I left out Behaviours that are not selected: "
                        + ", ".join(dict.fromkeys(dropped))
                        + "."
                    ),
                    source=WarningSource.RUNTIME,
                )
            )

    def _remove(self, state: DriverState, targets: list[str]) -> None:
        """Remove each named node with its dependants. The door confirmed this first.

        The guard reads the result, not each option: several deletes sent together must not
        empty a collection that one disabled Delete protects.
        """

        def remove_all(specification: Specification) -> None:
            for target in targets:
                found = nodes.locate(specification, target)
                if found is not None:
                    nodes.remove(specification, found)

        candidate = state.specification.model_copy(deep=True)
        remove_all(candidate)
        lost = nodes.emptied(state.specification, candidate)
        if lost:
            return self._refuse_field_edit(
                f"I can't delete {', '.join(lost)}. Add another one first. "
                "Nothing was changed."
            )
        remove_all(state.specification)

    def _go_back(self, state: DriverState) -> None:
        destination = PREVIOUS_STEP.get(state.step, state.step)
        # Back to Clarify or Behaviours reopens the measurement-scope decision, so its
        # earlier confirmation no longer holds and must be earned again with Continue.
        if destination in (InterviewStep.CLARIFY, InterviewStep.BEHAVIOURS):
            state.behaviours_confirmed = False
        state.step = destination
        if destination is InterviewStep.CLARIFY:
            # The Clarify chat is a model call. Back shows the Target fields as a form
            # instead, so going back costs nothing and asks no new question.
            self._open(state, screens.target_review_form(state.specification))

    def _handle_choice(
        self, state: DriverState, request: AnyRequest, response: AnyResponse
    ) -> None:
        feedback = getattr(response, "feedback", "")
        if feedback:
            return self._handle_chat(
                state, ChatRequest(prompt=""), ChatResponse(text=feedback)
            )
        values = getattr(response, "values", {}) or {}
        selected = set(getattr(response, "selected", []) or [])

        if values:
            if selected or len(values) != 1:
                return self._refuse_field_edit(
                    "Edit one scenario field at a time; I left the specification unchanged."
                )
            key, value = next(iter(values.items()))
            return self._handle_field_value(state, request, key, value)

        if not selected:
            return

        options = _all_options(request)
        # A disabled option is shown but cannot act — the last Persona cannot be deleted.
        chosen = [
            options[key] for key in selected if key in options and options[key].enabled
        ]
        if len(chosen) != len([key for key in selected if key in options]):
            return self._refuse_field_edit(
                "That action is not available now. Nothing was changed."
            )
        actions = {option.id.action for option in chosen}

        if "edit" in actions:
            return self._open_edit_form(state, _target_of(chosen, "edit"))

        if "add" in actions:
            return self._open_add_form(state, _target_of(chosen, "add"))

        if "remove" in actions:
            removes = [o for o in chosen if o.id.action == "remove"]
            # A delete is its own operation. Several deletes travel together only when none
            # takes other items with it (bulk removal of Test Cases), and never with a tick or
            # a navigation reply. The door confirmed each delete on its own.
            if len(removes) != len(chosen) or (
                len(removes) > 1 and any(option.confirm for option in removes)
            ):
                return self._refuse_field_edit(
                    "Delete one item at a time. Nothing was changed."
                )
            return self._remove(state, [o.id.target for o in removes if o.id.target])

        # A Test Case tick includes or excludes it. The selection is Interview state, so the
        # option carries no patch. Like a Behaviour tick, it is its own operation: the review
        # is drawn again with the new totals, and Continue in the same response is ignored.
        ticked = [
            option.id.target
            for option in chosen
            if option.id.action == "tick"
            and option.id.target
            and state.specification.task(option.id.target)
        ]
        if ticked:
            state.excluded_tasks ^= set(ticked)
            return

        # Toggles and ticks: apply the patches the package already composed.
        patches = [option.patch for option in chosen if option.patch]
        if patches:
            apply(
                state.specification,
                patches,
                issued_ids=state.issued_ids,
                user_typed=state.user_typed,
            )  # WIZARD origin — trusted by construction
            # Measurement changes are their own operation. Even if a multi-select caller also
            # sends Continue, return the recomposed Behaviour review first so the changed scope is
            # visible and must then be confirmed deliberately.
            if state.step is InterviewStep.BEHAVIOURS:
                return

        if "back" in actions:
            return self._go_back(state)

        # A per-card chat carries its item id in OptionId.target, and a screen-level chat
        # carries None and stays unscoped.
        if "chat" in actions:
            return self._open_chat(state, _target_of(chosen, "chat"))

        if "continue" in actions:
            self._advance(state)

    def _handle_field_value(
        self,
        state: DriverState,
        request: AnyRequest,
        key: str,
        value: CardFieldValue,
    ) -> None:
        """Validate one request-bound scenario field before composing its trusted patch."""
        field = editable_fields_of(request).get(key)
        if field is None:
            return self._refuse_field_edit(
                "That field is no longer available on this screen; I left the specification unchanged."
            )

        scenario_id = field.id.target
        scenario = state.specification.task(scenario_id) if scenario_id else None
        if scenario is None:
            return self._refuse_field_edit(
                "That scenario is no longer available; I left the specification unchanged."
            )

        if isinstance(field, CardNumberField):
            if field.id.action != "trials":
                return self._refuse_field_edit(
                    "That scenario field is not a supported trial editor; "
                    "I left the specification unchanged."
                )
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not field.min <= value <= field.max
            ):
                return self._refuse_field_edit(
                    f"Trials must be an integer from {field.min} to {field.max}; "
                    "I left the specification unchanged."
                )
            path = f"tasks[{scenario.id}].num_trials"
            patch_value: int | list[str] = value
        elif isinstance(field, CardUploadField):
            if field.id.action != "files":
                return self._refuse_field_edit(
                    "That scenario field is not a supported filename editor; "
                    "I left the specification unchanged."
                )
            normalized = _normalise_fixture_references(value)
            if normalized is None:
                return self._refuse_field_edit(
                    "Fixture references must be non-blank portable filenames; "
                    "I left the specification unchanged."
                )
            path = f"tasks[{scenario.id}].fixtures"
            patch_value = normalized
        else:  # pragma: no cover - editable_fields_of only returns the two field shapes
            return self._refuse_field_edit(
                "That scenario field is not editable; I left the specification unchanged."
            )

        outcome = apply(
            state.specification,
            [
                Patch(
                    op=PatchOp.SET,
                    path=path,
                    value=patch_value,
                    origin=PatchOrigin.WIZARD,
                )
            ],
            issued_ids=state.issued_ids,
            user_typed=state.user_typed,
        )
        if outcome.any_rejected:
            return self._refuse_field_edit(
                "That scenario field could not be updated; I left the specification unchanged."
            )

    def _refuse_field_edit(self, text: str) -> None:
        self.pending_warnings.append(
            Warning(text=text, source=WarningSource.RUNTIME, blocking=False)
        )

    # ── chat and refusals ──────────────────────────────────────────────────

    def _open_chat(self, state: DriverState, target: str | None) -> None:
        """Raise a chat request, scoped to a behaviour when one was named.

        `target` is the OptionId.target the clicked option carried — a behaviour id from a
        criteria card, or None from a screen-level "Chat about it". It rides on the request so
        the scope survives a save/resume or HTTP round trip, and `_handle_chat` reads it back.
        A mid-step chat inherits the header of the step it was raised on, so it does not read
        as the interview having jumped somewhere new.
        """
        behaviour = state.specification.behaviour(target) if target else None
        feature = state.specification.feature(target) if target else None
        label = behaviour.name if behaviour else feature.name if feature else None
        chat = ChatRequest(
            prompt="What would you like to change?",
            multiline=True,
            target=target,
            target_label=label,
        )
        screens.stamp_step(chat, state.step)
        state.pending = chat

    def _refuse_form_target(self) -> None:
        """Refuse a form whose parent no longer exists, without widening its scope."""
        self.pending_warnings.append(
            Warning(
                text=(
                    "I couldn't find where that item belongs, so I've left the specification "
                    "unchanged. Open the form again from its Feature."
                ),
                source=WarningSource.RUNTIME,
                blocking=False,
            )
        )

    def _match_new(self, behaviour: Behaviour, before_ids: set[str]) -> None:
        """Resolve a grader for any criterion the suggestion just added under this behaviour."""
        if self.matcher is None:
            return
        from metis.wizard.application.matching import rematch

        for criterion in behaviour.criteria:
            if criterion.id not in before_ids:
                rematch(criterion, self.matcher)  # type: ignore[arg-type]

    def _advance(self, state: DriverState) -> None:
        """Move on, generating whatever the next screen needs and does not have."""
        current = state.step

        # Behaviour Continue is the measurement-scope lock. It needs at least one measured
        # behaviour — with none there is nothing to write criteria for — and it records that
        # the user has chosen the set to measure. A screen with the gate held stays put.
        if current is InterviewStep.BEHAVIOURS:
            if not state.specification.measured_behaviours():
                return
            state.behaviours_confirmed = True
            _follow_measured_scope(state.specification)

        state.step = _NEXT_STEP.get(current, InterviewStep.DONE)
        # Scenario Continue is where the user approves the Scenarios, so the model matches
        # each Scenario that has no Test Case yet. The Test Case review then shows the result.
        if current is InterviewStep.SCENARIOS:
            self.draft_test_cases(state)

    def draft_missing_criteria(self, state: DriverState) -> None:
        """Draft Criteria for each measured Behaviour that has none, then match them.

        Continue at Behaviours is what normally generates Criteria. A Behaviour can also
        become measured later — added from a form or the chat at a later step — so every turn
        at Criteria or after closes the same gap. Nothing is drafted for an unmeasured one.
        """
        if state.step not in AFTER_BEHAVIOURS:
            return
        allowed_paths = missing_criteria_paths(state.specification)
        if not allowed_paths:
            return
        self._try(
            lambda: self.interviewer.draft_criteria(
                state.specification, context=state.context
            ),
            state,
            allowed_paths=allowed_paths,
            allowed_ops=frozenset({PatchOp.ADD}),
        )
        # A separate pass, after generation — never folded into it.
        self.match(state)

    # ── applying model output ──────────────────────────────────────────────

    def _try(
        self,
        call: Callable[[], StepResult],
        state: DriverState,
        *,
        allowed_paths: frozenset[str] | None = None,
        allowed_ops: frozenset[PatchOp] | None = None,
    ) -> bool:
        """Run a model call, turning a total failure into a warning rather than a crash.

        Three attempts have already happened inside the client. Reaching here means all of
        them failed, so the user is told and the previous screen is redrawn — everything
        already decided is still in the specification, because nothing was applied.
        """
        try:
            self._run(
                state,
                call(),
                allowed_paths=allowed_paths,
                allowed_ops=allowed_ops,
            )
            return True
        except InterviewerOutputError as exc:
            self.model_error = exc
            self.pending_warnings.append(
                Warning(
                    text=(
                        "I couldn't get a usable answer from the model just then. "
                        "Nothing you've decided has been lost — try that again."
                    ),
                    source=WarningSource.RUNTIME,
                    blocking=False,
                )
            )
            return False

    def _run(
        self,
        state: DriverState,
        result: StepResult,
        *,
        request: str = "",
        allowed_paths: frozenset[str] | None = None,
        allowed_ops: frozenset[PatchOp] | None = None,
        user_message: bool = False,
    ) -> None:
        """Apply a model result, reporting anything the applier refused.

        `sanitise` forces MODEL origin first: origin is stamped by the code that builds a
        patch, so a model claiming `wizard` is either confused or trying it on.
        `user_message` is True only when the result answers the user's own chat message.
        """
        before = state.specification.model_copy(deep=True)
        # Clarify questions are kept in the history, so only a review step keeps its message.
        if result.message and state.step in _DEFAULT_MESSAGES:
            state.step_messages[state.step] = result.message
        patches = sanitise(result.patches)
        if user_message:
            patches = [_user_requested(patch) for patch in patches]
        refused = [
            patch
            for patch in patches
            if (allowed_paths is not None and patch.path not in allowed_paths)
            or (allowed_ops is not None and patch.op not in allowed_ops)
        ]
        patches = [patch for patch in patches if patch not in refused]
        if refused:
            self.pending_warnings.append(
                Warning(
                    text=(
                        "I left out a model change that was outside this operation's "
                        "allowed scope. Your specification keeps the scope you selected."
                    ),
                    source=WarningSource.RUNTIME,
                    blocking=False,
                )
            )
        outcome = apply(
            state.specification,
            patches,
            issued_ids=state.issued_ids,
            user_typed=state.user_typed,
            allowed_fixture_names=set(state.context.document_names),
        )

        for rejection in outcome.rejected:
            self.pending_warnings.append(
                Warning(
                    text=rejection.message,
                    source=WarningSource.RUNTIME,
                    blocking=False,
                )
            )

        removed = nodes.follow_removals(before, state.specification)
        if removed:
            self.pending_warnings.append(
                Warning(
                    text=(
                        "That change removed an item that Test Cases used, so I removed "
                        f"{', '.join(removed)} too."
                    ),
                    source=WarningSource.RUNTIME,
                )
            )
        impacts = impacts_for(before, outcome.applied)
        if impacts:
            self._adjust_derived(state, impacts)
        self._configure_changes(state, before, request)
        # The user changed the measured set from the chat after Behaviours were confirmed.
        # Follow it in the Test Cases now, as Behaviours Continue does.
        if (
            user_message
            and state.step in AFTER_BEHAVIOURS
            and _measured_ids(before) != _measured_ids(state.specification)
        ):
            _follow_measured_scope(state.specification)

    def _adjust_derived(self, state: DriverState, impacts: list[Impact]) -> None:
        prefixes: list[str] = []
        for impact in impacts:
            if impact.kind == "criteria":
                feature = state.specification.feature_of(impact.subject)
                if feature:
                    prefixes.append(
                        f"features[{feature.id}].behaviours[{impact.subject}].criteria"
                    )
            elif impact.kind == "feature":
                prefixes.append(f"features[{impact.subject}].behaviours")
                feature = state.specification.feature(impact.subject)
                if feature:
                    prefixes.extend(
                        f"scenarios[{scenario.id}]"
                        for behaviour in feature.behaviours
                        for scenario in state.specification.scenarios_covering(
                            behaviour.id
                        )
                    )
            elif impact.kind == "scenario":
                prefixes.append(f"scenarios[{impact.subject}]")
            else:
                prefixes.extend(
                    f"features[{feature.id}]"
                    for feature in state.specification.features
                )
                prefixes.extend(
                    f"scenarios[{scenario.id}]"
                    for scenario in state.specification.scenarios
                )
        result = self.interviewer.chat(
            state.specification,
            str(state.step),
            "Adjust the existing model-written content affected by the correction just applied. "
            "Update only these paths: " + ", ".join(prefixes) + ". "
            "Keep existing IDs, unrelated content, selected Behaviours, and all form-written entries. "
            "Use SET on text fields and ADD for missing Criteria only. Do not remove or replace items "
            "or lists. Do not ask keep-or-regenerate questions. Return a short result message.",
            None,
            context=state.context,
        )
        criteria_paths = missing_criteria_paths(state.specification)
        patches = [
            patch
            for patch in sanitise(result.patches)
            if any(
                patch.path == prefix
                or patch.path.startswith(prefix + ".")
                or patch.path.startswith(prefix + "[")
                for prefix in prefixes
            )
            and not any(
                f"[{item}].name" in patch.path or f"[{item}].description" in patch.path
                for item in state.user_typed
            )
            and (
                (
                    patch.op is PatchOp.SET
                    and patch.path.endswith((".name", ".description"))
                )
                or (patch.op is PatchOp.ADD and patch.path in criteria_paths)
            )
        ]
        outcome = apply(
            state.specification,
            patches,
            issued_ids=state.issued_ids,
            user_typed=state.user_typed,
            allowed_fixture_names=set(state.context.document_names),
        )
        for rejection in outcome.rejected:
            self.pending_warnings.append(
                Warning(text=rejection.message, source=WarningSource.RUNTIME)
            )
        if result.message and state.step in _DEFAULT_MESSAGES:
            state.step_messages[state.step] = result.message

    def match(self, state: DriverState) -> None:
        """Resolve graders for criteria that lack them.

        A separate model call after criteria generation. If the call fails, every criterion
        gets the criterion judge, which is still a working experiment. So this warns and
        continues.
        """
        if self.matcher is None:
            return

        from metis.wizard.application.matching import match_specification

        match_specification(state.specification, self.matcher)  # type: ignore[arg-type]
        if getattr(self.matcher, "degraded", False):
            self.pending_warnings.append(
                Warning(
                    text=(
                        "The model could not pick library graders, so each new criterion "
                        "uses a custom judge. The evaluation still runs. You can change "
                        "the grader of each criterion."
                    ),
                    source=WarningSource.RUNTIME,
                    blocking=False,
                )
            )
            self.matcher.degraded = False  # type: ignore[attr-defined]  # shown once


def _target_of(chosen: list[Option], action: str) -> str | None:
    """The behaviour id the option carrying `action` was scoped to, or None.

    Reads it straight off `OptionId.target`, which the criteria screen set to the behaviour a
    card belongs to. Screen-level chat carries None here, which is exactly what keeps it
    unscoped; the criteria actions carry a behaviour id, which is what scopes them to one card.
    """
    return next((o.id.target for o in chosen if o.id.action == action), None)


# The user's own decisions. No model call may write them, except a chat that answers the
# user's own message: "measure only the citation behaviour" or "run 5 trials" is the user
# deciding, through the chat. A drafting call never reaches this.
_USER_DECISIONS = (
    (re.compile(r"^features\[[^\]]+\]\.behaviours\[[^\]]+\]\.measured$"), bool),
    (re.compile(r"^tasks\[[^\]]+\]\.num_trials$"), int),
)


def _user_requested(patch: Patch) -> Patch:
    """Trust a SET of a user decision, with a value of the right type, from a user chat."""
    if patch.op is not PatchOp.SET:
        return patch
    for pattern, kind in _USER_DECISIONS:
        if (
            pattern.match(patch.path)
            and type(patch.value) is kind
            and (
                kind is bool or screens.TRIALS_MIN <= patch.value <= screens.TRIALS_MAX
            )
        ):
            return patch.model_copy(update={"origin": PatchOrigin.WIZARD})
    return patch


def _task_settings(
    request: FormRequest, values: dict[str, Any]
) -> tuple[list[str], int, list[str]] | str:
    """Read the Behaviours, Trials and Files of a Test Case form, or say what is wrong."""
    fields = {field.id: field for field in request.fields}

    def listed(field_id: str) -> list[str] | None:
        field = fields.get(field_id)
        if field is None:
            return []
        raw = values.get(field_id, field.value)
        chosen = list(
            dict.fromkeys(part.strip() for part in raw.split(",") if part.strip())
        )
        allowed = {choice.value for choice in field.choices}
        return chosen if set(chosen) <= allowed else None

    behaviours = listed("behaviours")
    if not behaviours:
        return "Choose at least one measured Behaviour from the list."
    # Files follow the same rule as the row's file field: a listed document or a file the user
    # uploads in the same edit. The browser keeps the file bytes; the package checks the name.
    raw_files = values.get("files", fields["files"].value if "files" in fields else "")
    fixtures = _normalise_fixture_references(
        [part for part in raw_files.split(",") if part.strip()]
    )
    if fixtures is None:
        return (
            "Use portable file names: no folders, no commas, and none of "
            'the characters < > : " | ? *.'
        )
    raw_trials = values.get(
        "trials", fields["trials"].value if "trials" in fields else ""
    )
    try:
        trials = int(raw_trials)
    except ValueError:
        trials = 0
    if not screens.TRIALS_MIN <= trials <= screens.TRIALS_MAX:
        return f"Trials must be a whole number from {screens.TRIALS_MIN} to {screens.TRIALS_MAX}."
    return behaviours, trials, fixtures


def _measured_ids(specification: Specification) -> set[str]:
    return {behaviour.id for behaviour in specification.measured_behaviours()}


def _follow_measured_scope(specification: Specification) -> None:
    """Keep Test Cases in line with the measured set confirmed at Behaviours Continue.

    A Test Case drops each Behaviour that is no longer measured. A Test Case left with none,
    like a new Test Case, covers all measured Behaviours, so it stays runnable. A newly
    measured Behaviour is not added to every Test Case, because not every Scenario exercises
    it. The Test Case review shows it as a coverage gap, and the user chooses where it runs.
    """
    measured = [behaviour.id for behaviour in specification.measured_behaviours()]
    for task in specification.tasks:
        task.behaviour_refs = [
            ref for ref in task.behaviour_refs if ref in measured
        ] or list(measured)


_METADATA_HELP = "Add a detail for each fact, such as Role and Policy analyst. Each detail needs a name."


def _named_fields(node: Feature | Behaviour | None) -> list[FormField]:
    return [
        FormField(
            id="name",
            label="Name",
            value=node.name if node else "",
            multiline=False,
            required=True,
        ),
        FormField(
            id="description",
            label="Description",
            value=node.description if node else "",
            required=True,
        ),
    ]


def _profile_fields(node: Persona | Scenario | None) -> list[FormField]:
    """Name, description, and metadata as labelled details. Metadata may be empty."""
    metadata = node.metadata if node else {}
    return [
        *_named_fields(node),  # type: ignore[arg-type]
        FormField(
            id="metadata",
            label="More information",
            input_type="pairs",
            value=json.dumps([[key, value] for key, value in metadata.items()]),
            placeholder="Role|Policy analyst",
            help=_METADATA_HELP,
        ),
    ]


def _parse_metadata(text: str) -> dict[str, str] | None:
    """Read the labelled details of a `pairs` field. None when a detail with a value has no name.

    A detail that is empty in both parts is a row the user did not fill, so it is skipped.
    """
    if not text.strip():
        return {}
    try:
        rows = json.loads(text)
    except ValueError:
        return None
    if not isinstance(rows, list):
        return None
    metadata: dict[str, str] = {}
    for row in rows:
        if (
            not isinstance(row, list)
            or len(row) != 2
            or not all(isinstance(part, str) for part in row)
        ):
            return None
        key, value = row[0].strip(), row[1].strip()
        if not key and not value:
            continue
        if not key:
            return None
        metadata[key] = value
    return metadata


def _normalise_fixture_references(value: object) -> list[str] | None:
    """Return safe, ordered file name references, or ``None`` when the value is invalid.

    Every door uses the one portable-name rule, so a name that the table cell accepts also
    survives the comma-separated form value.
    """
    if not isinstance(value, list):
        return None

    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return None
        try:
            name = normalize_fixture_name(item)
        except ValueError:
            return None
        if name not in normalized:
            normalized.append(name)
    return normalized


def _all_options(request: AnyRequest) -> dict[str, Option]:
    return options_of(request)


__all__ = ["DriverState", "OptionId", "StepDriver"]
