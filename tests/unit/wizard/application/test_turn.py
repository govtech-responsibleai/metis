"""The Interview operation as a stateless transaction."""

from __future__ import annotations

import pytest

from metis.wizard import (
    CompilationError,
    InterviewEndRequest,
    InterviewErrorCode,
    InterviewFailure,
    InterviewStartRequest,
    InterviewSuccess,
    InterviewTurnRequest,
    compile_specification,
    derive_stage,
    handle_interview,
)
from metis.wizard.application.driver import PREVIOUS_STEP, DriverState
from metis.wizard.application.interviewer import (
    InterviewContextBudgetError,
    InterviewerOutputError,
)
from metis.wizard.application.screens import behaviours_screen, task_review_screen
from metis.wizard.application.turn import _reconcile_locks
from metis.wizard.contracts import (
    ChatResponse,
    ChoiceRequest,
    ChoiceResponse,
    ClarifyResult,
    FormRequest,
    FormResponse,
    InterviewDocument,
    Option,
    OptionId,
    Patch,
    PatchOp,
    Perspective,
    Specification,
    StepResult,
    Target,
)
from metis.wizard.contracts.interview_state import (
    HISTORY_LIMIT,
    InterviewMessage,
    InterviewState,
)
from metis.wizard.domain.permissions import InterviewStep
from tests.fixtures.wizard.context import interview_context
from tests.fixtures.wizard.scripted import ScriptedInterviewer, ScriptedMatcher
from tests.fixtures.wizard.specifications import research_assistant


def _start(
    *,
    interviewer=None,
    perspective=Perspective.END_USER,
    known_capability_ids=None,
    capability_confidence="low",
    documents=None,
):
    return handle_interview(
        InterviewStartRequest(
            description="A research assistant",
            perspective=perspective,
            known_capability_ids=(
                [] if known_capability_ids is None else known_capability_ids
            ),
            capability_confidence=capability_confidence,
            documents=documents or [],
        ),
        interviewer=interviewer or ScriptedInterviewer(),
        matcher=None,
    )


def _turn(state, response, *, request_id=None, interviewer=None):
    return handle_interview(
        InterviewTurnRequest(
            state=state,
            request_id=request_id or state.pending.request_id,
            response=response,
        ),
        interviewer=interviewer or ScriptedInterviewer(),
        matcher=None,
    )


def _end(state, *, interviewer=None, matcher=None):
    return handle_interview(
        InterviewEndRequest(state=state),
        interviewer=interviewer or ScriptedInterviewer(),
        matcher=matcher,
    )


def _empty_specification() -> Specification:
    return Specification(target=Target(name="", description="", users=""))


def _pending_choice(request_id: str = "req-1") -> InterviewState:
    return InterviewState(
        specification=research_assistant(),
        context=interview_context(),
        pending=ChoiceRequest(
            prompt="Do these look right?",
            options=[Option(id=OptionId(action="continue"), label="Continue")],
            request_id=request_id,
            stage=InterviewStep.BEHAVIOURS,
        ),
    )


def test_start_records_the_raw_description_as_the_first_user_turn() -> None:
    result = _start()

    assert isinstance(result, InterviewSuccess)
    assert result.state.history[0].role == "user"
    assert result.state.history[0].text == "A research assistant"
    assert result.state.context.opening_description == "A research assistant"
    assert result.state.pending is not None


def test_start_records_a_perspective_and_reuses_it_on_the_next_turn() -> None:
    class RecordingInterviewer(ScriptedInterviewer):
        def __init__(self) -> None:
            super().__init__()
            self.seen: list[Perspective] = []

        def clarify(self, specification, history, context=None):
            assert context is not None
            self.seen.append(context.perspective)
            return super().clarify(specification, history, context)

    interviewer = RecordingInterviewer()
    started = _start(interviewer=interviewer, perspective=Perspective.SECURITY)
    assert isinstance(started, InterviewSuccess)
    assert started.state.context.perspective is Perspective.SECURITY

    continued = _turn(
        started.state,
        ChatResponse(text="It answers policy questions."),
        interviewer=interviewer,
    )

    assert isinstance(continued, InterviewSuccess)
    assert interviewer.seen
    assert all(perspective is Perspective.SECURITY for perspective in interviewer.seen)


def test_start_records_capability_evidence_and_keeps_it_on_a_later_turn() -> None:
    started = _start(
        known_capability_ids=["tool_use", "internet_search_access"],
        capability_confidence="medium",
    )
    assert isinstance(started, InterviewSuccess)
    evidence = started.state.context.capability_evidence
    assert [item.value for item in evidence.known_capability_ids] == [
        "tool_use",
        "internet_search_access",
    ]
    assert evidence.confidence.value == "medium"

    continued = _turn(
        started.state,
        ChatResponse(text="It searches the internal library."),
    )

    assert isinstance(continued, InterviewSuccess)
    assert continued.state.context.capability_evidence == evidence


def test_start_with_whitespace_is_rejected_before_processing() -> None:
    with pytest.raises(ValueError):
        InterviewStartRequest(
            description="  ", known_capability_ids=[], capability_confidence="low"
        )


def test_explicit_none_disables_the_configured_matcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from metis.wizard.application import turn as turn_module

    class ConfiguredMatcher:
        degraded = False
        calls = 0

        def match(self, _criterion):
            self.calls += 1
            return "configured.grader"

    matcher = ConfiguredMatcher()
    monkeypatch.setattr(turn_module, "_DEFAULT_MATCHER", matcher)
    specification = research_assistant()
    specification.behaviour("EB-1").criteria = []  # type: ignore[union-attr]
    state = InterviewState(
        specification=specification,
        context=interview_context(),
        pending=ChoiceRequest(
            prompt="Review Behaviours",
            options=[Option(id=OptionId(action="continue"), label="Continue")],
            request_id="req-behaviours",
            stage=InterviewStep.BEHAVIOURS,
        ),
    )

    result = handle_interview(
        InterviewTurnRequest(
            state=state,
            request_id="req-behaviours",
            response=ChoiceResponse(selected=["continue"]),
        ),
        interviewer=ScriptedInterviewer(),
        matcher=None,
    )

    assert isinstance(result, InterviewSuccess)
    assert matcher.calls == 0
    assert result.state.specification.behaviour("EB-1").criteria[0].grader_fqn is None  # type: ignore[union-attr]


def test_a_late_answer_is_caught_by_the_request_id() -> None:
    state = _pending_choice()

    result = _turn(
        state,
        ChoiceResponse(selected=["continue"]),
        request_id="req-0",
    )

    assert isinstance(result, InterviewFailure)
    assert result.code is InterviewErrorCode.REQUEST_ID_MISMATCH
    assert result.state == state


def test_an_answer_of_the_wrong_kind_is_refused() -> None:
    state = _pending_choice()

    result = _turn(state, ChatResponse(text="hi"))

    assert isinstance(result, InterviewFailure)
    assert result.code is InterviewErrorCode.RESPONSE_TYPE_MISMATCH
    assert result.state == state


def test_an_option_the_screen_never_offered_is_refused() -> None:
    state = _pending_choice()

    result = _turn(state, ChoiceResponse(selected=["never-shown"]))

    assert isinstance(result, InterviewFailure)
    assert result.code is InterviewErrorCode.RESPONSE_NOT_OFFERED
    assert result.state == state


def test_a_behaviour_measurement_change_stays_pending_before_continue() -> None:
    specification = research_assistant()
    pending = behaviours_screen(specification, "Review Behaviours")
    pending.request_id = "req-behaviours"
    pending.stage = InterviewStep.BEHAVIOURS
    state = InterviewState(
        specification=specification, context=interview_context(), pending=pending
    )

    result = _turn(
        state,
        ChoiceResponse(selected=["tick:EB-1", "continue"]),
    )

    assert isinstance(result, InterviewSuccess)
    assert result.stage is InterviewStep.BEHAVIOURS
    assert result.state.pending is not None
    assert result.state.pending.stage is InterviewStep.BEHAVIOURS
    assert not result.state.behaviours_confirmed
    assert not result.state.specification.behaviour("EB-1").measured  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "error, code, retryable",
    [
        (
            InterviewerOutputError("three attempts, all failed"),
            InterviewErrorCode.MODEL_UNAVAILABLE,
            True,
        ),
        (
            InterviewContextBudgetError("Request exceeds context budget"),
            InterviewErrorCode.CONTEXT_BUDGET_EXCEEDED,
            False,
        ),
    ],
)
def test_model_failure_preserves_state_and_diagnostics(error, code, retryable) -> None:
    """A failed model call returns a typed failure with the caller's state, also when the
    answer fills the history to its limit (a full Clarify, then review feedback)."""

    class FailingInterviewer(ScriptedInterviewer):
        def clarify(self, specification, history, context=None):
            raise error

        def chat(self, specification, step, text, target, context=None):
            raise error

    opening = _start()
    assert isinstance(opening, InterviewSuccess)
    full = _review_state(InterviewStep.PERSONAS)
    full.history = [
        InterviewMessage(role="user", text=f"Note {i}") for i in range(HISTORY_LIMIT)
    ]

    for state, response in (
        (opening.state, ChatResponse(text="a policy tool")),
        (full, ChoiceResponse(feedback="Make them shorter.")),
    ):
        result = _turn(state, response, interviewer=FailingInterviewer())

        assert isinstance(result, InterviewFailure)
        assert result.code is code
        assert result.retryable is retryable
        assert result.state == state

        assert result.diagnostic_state is not None
        assert str(error) in (result.diagnostic_message or result.message)


def test_end_finishes_a_completable_interview() -> None:
    specification = research_assistant()
    specification.behaviour("EB-1").criteria[0].grader_fqn = None  # type: ignore[union-attr]
    result = _end(
        InterviewState(
            specification=specification,
            context=interview_context(),
            behaviours_confirmed=True,
        ),
        matcher=ScriptedMatcher(),
    )

    assert isinstance(result, InterviewSuccess)
    assert result.outcome == "done"
    assert result.state.confirmed
    assert result.state.pending is None
    assert result.state.specification.behaviour("EB-1").criteria[0].grader_fqn  # type: ignore[union-attr]


def test_missing_target_details_can_be_completed_before_review() -> None:
    class IncompleteInterviewer(ScriptedInterviewer):
        def clarify(self, specification, history, context=None):
            return ClarifyResult(
                done=True,
                message="",
                patches=[
                    Patch(op=PatchOp.SET, path=f"target.{key}", value="")
                    for key in ("name", "description")
                ],
            )

    interviewer = IncompleteInterviewer()
    started = _start(interviewer=interviewer)
    assert isinstance(started, InterviewSuccess)
    assert isinstance(started.state.pending, FormRequest)
    completed = _turn(
        started.state,
        FormResponse(
            values={
                "target.name": "Policy assistant",
                "target.description": "Answers policy questions.",
            }
        ),
        interviewer=interviewer,
    )
    assert isinstance(completed, InterviewSuccess)
    assert isinstance(completed.state.pending, ChoiceRequest)
    continued = _turn(
        completed.state, ChoiceResponse(selected=["continue"]), interviewer=interviewer
    )
    assert isinstance(continued, InterviewSuccess)
    assert continued.stage is InterviewStep.CRITERIA


def test_documents_survive_turns_and_require_file_review() -> None:
    """Documents travel with the state. End stops at the Scenario review so the user chooses
    the files: the paired Test Cases start with none."""
    documents = [
        InterviewDocument(name="policy.pdf", text="POLICY_CONTEXT_SENTINEL"),
        InterviewDocument(name="terms.md"),
    ]

    class FixtureInterviewer(ScriptedInterviewer):
        def clarify(self, specification, history, context=None):
            assert context is not None and context.documents == documents
            return super().clarify(specification, history, context)

    interviewer = FixtureInterviewer()
    started = _start(interviewer=interviewer, documents=documents)
    assert isinstance(started, InterviewSuccess)
    state = InterviewState.model_validate_json(started.state.model_dump_json())
    state.history = [
        InterviewMessage(role="user", text=f"Note {i}") for i in range(HISTORY_LIMIT)
    ]
    continued = _turn(
        state,
        ChatResponse(text="It answers policy questions."),
        interviewer=interviewer,
    )
    assert isinstance(continued, InterviewSuccess)
    assert len(continued.state.history) == HISTORY_LIMIT
    assert continued.state.context.documents == documents

    review = _end(continued.state, interviewer=interviewer, matcher=ScriptedMatcher())
    assert isinstance(review, InterviewSuccess)
    assert review.outcome == "awaiting_response"
    assert review.stage is InterviewStep.TEST_CASES
    assert not review.state.confirmed
    assert review.state.specification.task("TC-001").fixtures == []
    from metis.wizard.contracts.conversation import editable_fields_of

    uploads = [
        component
        for component in editable_fields_of(review.state.pending).values()
        if component.type == "upload"
    ]
    assert uploads and uploads[0].available == ["policy.pdf", "terms.md"]

    selected = _turn(
        review.state,
        ChoiceResponse(values={"files:TC-001": ["terms.md"]}),
        interviewer=interviewer,
    )
    assert isinstance(selected, InterviewSuccess)
    assert selected.state.specification.task("TC-001").fixtures == ["terms.md"]
    done = _turn(
        selected.state, ChoiceResponse(selected=["continue"]), interviewer=interviewer
    )
    assert isinstance(done, InterviewSuccess)
    assert done.outcome == "done" and done.state.confirmed


def test_final_continue_completes_a_ready_specification() -> None:
    specification = research_assistant()
    pending = task_review_screen(specification, "Review test cases")
    pending.request_id = "req-final"
    pending.stage = InterviewStep.TEST_CASES
    state = InterviewState(
        specification=specification,
        context=interview_context(),
        behaviours_confirmed=True,
        pending=pending,
    )

    result = _turn(state, ChoiceResponse(selected=["continue"]))

    assert isinstance(result, InterviewSuccess)
    assert result.outcome == "done"
    assert result.state.confirmed
    assert result.state.pending is None


def test_end_on_a_held_gate_preserves_state() -> None:
    specification = research_assistant()
    specification.scenarios = [s for s in specification.scenarios if s.id != "S-2"]
    state = InterviewState(
        specification=specification,
        context=interview_context(),
        behaviours_confirmed=True,
    )

    result = _end(state)

    assert isinstance(result, InterviewFailure)
    assert result.code is InterviewErrorCode.COMPLETION_FAILED
    assert result.state == state
    assert any(gap.subject == "EB-3" for gap in result.missing)


def test_failed_end_preserves_pending_state_for_a_later_turn() -> None:
    class DraftUnavailable(ScriptedInterviewer):
        def draft_behaviours(self, specification, history, context=None):
            raise InterviewerOutputError("three attempts, all failed")

    state = InterviewState(
        specification=Specification(
            target=Target(name="Tool", description="A tool", users="Analysts")
        ),
        context=interview_context(),
        pending=ChoiceRequest(
            prompt="Review behaviours",
            options=[Option(id=OptionId(action="continue"), label="Continue")],
            request_id="req-behaviours",
            stage=InterviewStep.BEHAVIOURS,
        ),
    )
    failed = _end(state, interviewer=DraftUnavailable())

    assert isinstance(failed, InterviewFailure)
    assert failed.code is InterviewErrorCode.MODEL_UNAVAILABLE
    assert failed.state == state

    continued = _turn(
        state,
        ChoiceResponse(selected=["continue"]),
        interviewer=ScriptedInterviewer(),
    )
    assert isinstance(continued, InterviewSuccess)
    assert continued.state.pending is not None


def test_end_on_a_completed_state_does_not_call_the_model() -> None:
    interviewer = ScriptedInterviewer()
    state = InterviewState(
        specification=research_assistant(),
        context=interview_context(),
        behaviours_confirmed=True,
        confirmed=True,
    )

    result = _end(state, interviewer=interviewer)
    repeated = (
        _end(result.state, interviewer=interviewer)
        if isinstance(result, InterviewSuccess)
        else result
    )

    assert isinstance(result, InterviewSuccess)
    assert result.outcome == "done"
    assert isinstance(repeated, InterviewSuccess)
    assert repeated.state == result.state
    assert interviewer.calls == []


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (
            InterviewState(
                specification=_empty_specification(), context=interview_context()
            ),
            InterviewStep.CLARIFY,
        ),
        (
            InterviewState(
                specification=research_assistant(), context=interview_context()
            ),
            InterviewStep.BEHAVIOURS,
        ),
        (
            InterviewState(
                specification=research_assistant(),
                context=interview_context(),
                behaviours_confirmed=True,
                confirmed=True,
            ),
            InterviewStep.DONE,
        ),
    ],
)
def test_derive_stage_reads_the_specification_top_to_bottom(
    state: InterviewState, expected: InterviewStep
) -> None:
    assert derive_stage(state) is expected


def test_criteria_precede_personas_when_a_measured_behaviour_lacks_them() -> None:
    specification = research_assistant()
    specification.behaviour("EB-1").criteria = []  # type: ignore[union-attr]
    state = InterviewState(
        specification=specification,
        context=interview_context(),
        behaviours_confirmed=True,
    )

    assert derive_stage(state) is InterviewStep.CRITERIA


def test_behaviour_edit_clears_both_confirmation_locks() -> None:
    specification = research_assistant()
    before = specification.model_copy(deep=True)
    working = DriverState(
        step=InterviewStep.BEHAVIOURS,
        specification=specification,
        context=interview_context(),
        behaviours_confirmed=True,
        confirmed=True,
    )
    specification.behaviour("EB-1").description += " with audit logs"  # type: ignore[union-attr]

    _reconcile_locks(working, before)

    assert not working.behaviours_confirmed
    assert not working.confirmed


def test_compile_specification_returns_both_yaml_strings_and_writes_nothing() -> None:
    result = compile_specification(research_assistant())

    assert result.specification_yaml.strip()
    assert "scenarios" in result.specification_yaml


def test_compile_specification_raises_on_a_specification_that_will_not_build() -> None:
    with pytest.raises(CompilationError):
        compile_specification(_empty_specification())


def test_end_completes_missing_target_fields_from_evidence() -> None:
    class TargetCompletionInterviewer(ScriptedInterviewer):
        def chat(self, specification, step, text, target, context=None):
            assert specification.target.description
            return StepResult(
                message="",
                patches=[
                    Patch(op=PatchOp.SET, path="target.name", value="Billing support"),
                ],
            )

    specification = research_assistant()
    specification.target.name = ""
    result = _end(
        InterviewState(
            specification=specification,
            context=interview_context(),
            behaviours_confirmed=True,
        ),
        interviewer=TargetCompletionInterviewer(),
    )
    assert isinstance(result, InterviewSuccess)
    assert result.outcome == "done"
    assert result.state.specification.target.name == "Billing support"


def _review_state(step: InterviewStep) -> InterviewState:
    """A ready Specification whose pending request is the review screen at `step`."""
    from metis.wizard.application.driver import StepDriver

    working = DriverState(
        step=step,
        specification=research_assistant(),
        context=interview_context(),
        behaviours_confirmed=step is not InterviewStep.BEHAVIOURS,
    )
    pending = StepDriver(interviewer=ScriptedInterviewer()).compose(working)
    pending.request_id = "req-review"
    pending.stage = step
    return InterviewState(
        specification=working.specification,
        context=working.context,
        behaviours_confirmed=working.behaviours_confirmed,
        pending=pending,
    )


@pytest.mark.parametrize(
    "step",
    [
        InterviewStep.BEHAVIOURS,
        InterviewStep.CRITERIA,
        InterviewStep.PERSONAS,
        InterviewStep.SCENARIOS,
        InterviewStep.TEST_CASES,
    ],
)
def test_back_then_continue_with_no_edit_returns_to_the_later_step(
    step: InterviewStep,
) -> None:
    state = _review_state(step)
    interviewer = ScriptedInterviewer()

    back = _turn(state, ChoiceResponse(selected=["back"]), interviewer=interviewer)
    assert isinstance(back, InterviewSuccess)
    earlier = back.state.pending
    assert earlier is not None
    if isinstance(earlier, FormRequest):
        response = FormResponse(
            values={field.id: field.value for field in earlier.fields}
        )
    else:
        primary = next(option for option in earlier.options if option.primary)
        response = ChoiceResponse(selected=[str(primary.id)])
    later = _turn(back.state, response, interviewer=interviewer)

    assert isinstance(later, InterviewSuccess)
    assert later.state.pending is not None
    assert later.state.pending.stage is step
    assert later.state.specification == state.specification
    assert interviewer.calls == []


def _forward(state: InterviewState, interviewer) -> InterviewState:
    result = _turn(
        state, ChoiceResponse(selected=["continue"]), interviewer=interviewer
    )
    assert isinstance(result, InterviewSuccess)
    return result.state


def _back(state: InterviewState, interviewer, times: int = 1) -> InterviewState:
    for _ in range(times):
        result = _turn(
            state, ChoiceResponse(selected=["back"]), interviewer=interviewer
        )
        assert isinstance(result, InterviewSuccess)
        state = result.state
    return state


def _test_cases_continue(state: InterviewState) -> bool:
    return next(o for o in state.pending.options if o.id.action == "continue").enabled


@pytest.mark.parametrize("change", ["untick", "tick"])
def test_a_measured_set_changed_after_back_still_reaches_a_runnable_review(
    change: str,
) -> None:
    """Behaviours Continue keeps Test Cases in line with the measured set. An unmeasured
    Behaviour leaves every Test Case, and a Test Case left with none covers the measured set,
    so the Test Case review can Continue. A newly measured Behaviour gets Criteria, and the
    review shows that no Test Case covers it yet. One chip fixes it, then Continue works."""
    interviewer = ScriptedInterviewer()
    state = _review_state(InterviewStep.TEST_CASES)
    state = _back(state, interviewer, times=4)
    assert state.pending.stage is InterviewStep.BEHAVIOURS
    target = "EB-1" if change == "untick" else "EB-2"  # EB-2 starts unmeasured
    ticked = _turn(
        state, ChoiceResponse(selected=[f"tick:{target}"]), interviewer=interviewer
    )
    assert isinstance(ticked, InterviewSuccess)
    state = ticked.state
    while state.pending.stage is not InterviewStep.TEST_CASES:
        state = _forward(state, interviewer)

    measured = {b.id for b in state.specification.measured_behaviours()}
    assert (target in measured) is (change == "tick")
    assert all(set(t.behaviour_refs) <= measured for t in state.specification.tasks)
    if change == "tick":
        assert state.specification.behaviour(target).criteria  # type: ignore[union-attr]
        assert not _test_cases_continue(state)
        assert any(
            w.text == f"{target} is covered by no selected Test Case."
            for w in state.pending.warnings
        )
        chip = _turn(
            state,
            ChoiceResponse(selected=[f"cover:TC-001:{target}"]),
            interviewer=interviewer,
        )
        assert isinstance(chip, InterviewSuccess)
        state = chip.state
    assert _test_cases_continue(state), [w.text for w in state.pending.warnings]


@pytest.mark.parametrize(
    ("step", "response"),
    [
        (InterviewStep.CRITERIA, "pen"),
        (InterviewStep.TEST_CASES, "feedback"),
    ],
)
def test_a_scope_change_on_a_later_review_keeps_the_interview_moving(
    step: InterviewStep, response: str
) -> None:
    """A Behaviour edit made on a later review keeps the measured-scope lock. Continue goes
    forward, and the completed Interview derives DONE."""

    class Measures(ScriptedInterviewer):
        def chat(self, specification, step, text, target, context=None):
            return StepResult(
                message="Measured.",
                patches=[
                    Patch(
                        op=PatchOp.SET,
                        path="features[F-1].behaviours[EB-2].measured",
                        value=True,
                    )
                ],
            )

    interviewer = Measures()
    state = _review_state(step)
    if response == "pen":
        opened = _turn(
            state, ChoiceResponse(selected=["edit:EB-1"]), interviewer=interviewer
        )
        assert isinstance(opened, InterviewSuccess)
        edited = _turn(
            opened.state,
            FormResponse(
                values={"name": "Cites claims", "description": "Cites sources."}
            ),
            interviewer=interviewer,
        )
    else:
        edited = _turn(
            state, ChoiceResponse(feedback="Measure EB-2"), interviewer=interviewer
        )
    assert isinstance(edited, InterviewSuccess)
    assert edited.state.behaviours_confirmed
    state = edited.state
    # A newly measured Behaviour runs where the user puts it. Here it is TC-001.
    if response == "feedback":
        assert not _test_cases_continue(state)
        covered = _turn(
            state,
            ChoiceResponse(selected=["cover:TC-001:EB-2"]),
            interviewer=interviewer,
        )
        assert isinstance(covered, InterviewSuccess)
        state = covered.state
    for _ in range(7):
        result = _turn(
            state, ChoiceResponse(selected=["continue"]), interviewer=interviewer
        )
        assert isinstance(result, InterviewSuccess)
        if result.outcome == "done":
            break
        assert result.stage is not InterviewStep.BEHAVIOURS
        state = result.state
    else:
        raise AssertionError("Continue did not reach DONE")
    assert result.state.behaviours_confirmed and result.state.confirmed
    assert derive_stage(result.state) is InterviewStep.DONE


def test_back_from_a_completed_interview_reopens_the_last_review() -> None:
    """A completed Interview has no pending request. Back, sent with an empty request id,
    reopens the Test Case review with nothing changed, and Continue completes it again."""
    interviewer = ScriptedInterviewer()
    done = _turn(
        _review_state(InterviewStep.TEST_CASES),
        ChoiceResponse(selected=["continue"]),
        interviewer=interviewer,
    )
    assert isinstance(done, InterviewSuccess) and done.outcome == "done"

    reopened = _turn(
        done.state,
        ChoiceResponse(selected=["back"]),
        request_id="-",
        interviewer=interviewer,
    )
    assert isinstance(reopened, InterviewSuccess)
    assert reopened.stage is InterviewStep.TEST_CASES
    assert not reopened.state.confirmed
    assert reopened.state.specification == done.state.specification
    assert interviewer.calls == []

    again = _forward(reopened.state, interviewer)
    assert again.confirmed and again.pending is None

    # Any other answer to a completed Interview still has nothing to bind to.
    refused = _turn(done.state, ChoiceResponse(selected=["continue"]), request_id="-")
    assert isinstance(refused, InterviewFailure)
    assert refused.code == InterviewErrorCode.NO_PENDING_REQUEST


def test_the_target_review_after_back_cancels_to_behaviours_unchanged() -> None:
    interviewer = ScriptedInterviewer()
    state = _back(_review_state(InterviewStep.BEHAVIOURS), interviewer)
    form = state.pending
    assert isinstance(form, FormRequest) and form.cancellable
    assert form.submit_label == "Continue"

    cancelled = _turn(state, FormResponse(cancelled=True), interviewer=interviewer)
    assert isinstance(cancelled, InterviewSuccess)
    assert cancelled.state.pending.stage is InterviewStep.BEHAVIOURS
    assert cancelled.state.specification == state.specification
    assert interviewer.calls == []
    # The first step has no Back, so Back from this form is not offered.
    refused = _turn(state, ChoiceResponse(selected=["back"]), interviewer=interviewer)
    assert isinstance(refused, InterviewFailure)


def test_an_earlier_review_shows_its_drafting_message_after_back() -> None:
    interviewer = ScriptedInterviewer()
    started = _start(interviewer=interviewer)
    state = started.state
    while state.pending.stage is not InterviewStep.CRITERIA:
        if state.pending.type == "chat":
            result = _turn(
                state, ChatResponse(text="It answers."), interviewer=interviewer
            )
            assert isinstance(result, InterviewSuccess)
            state = result.state
        else:
            state = _forward(state, interviewer)
    state = InterviewState.model_validate_json(state.model_dump_json())

    back = _back(state, interviewer)

    assert back.pending.prompt == "Here's what I think it should do. Have a look."


@pytest.mark.parametrize("supplied", [False, True])
def test_start_preserves_optional_capability_context(supplied: bool) -> None:
    fields = (
        {"known_capability_ids": ["tool_use"], "capability_confidence": "high"}
        if supplied
        else {}
    )
    result = handle_interview(
        InterviewStartRequest(description="A research assistant", **fields),
        interviewer=ScriptedInterviewer(),
        matcher=None,
    )
    assert isinstance(result, InterviewSuccess)
    evidence = result.state.context.capability_evidence
    if supplied:
        assert evidence is not None and evidence.known_capability_ids == ["tool_use"]
        assert evidence.confidence == "high"
    else:
        assert evidence is None


@pytest.mark.parametrize(
    "fields",
    [
        {"known_capability_ids": []},
        {"capability_confidence": "low"},
        {
            "known_capability_ids": ["tool_use", "tool_use"],
            "capability_confidence": "high",
        },
    ],
)
def test_start_rejects_incomplete_or_duplicate_capability_evidence(fields) -> None:
    with pytest.raises(ValueError):
        InterviewStartRequest(description="A research assistant", **fields)


@pytest.mark.parametrize(
    "name,description", [("", "A detailed description"), ("New name", " ")]
)
def test_direct_edit_keeps_the_form_when_required_text_is_missing(
    name, description
) -> None:
    state = _pending_choice()
    state.pending = behaviours_screen(state.specification, "Review")
    state.pending.request_id = "req-edit"
    state.pending.stage = InterviewStep.BEHAVIOURS
    opened = _turn(state, ChoiceResponse(selected=["edit:EB-1"]))
    assert isinstance(opened, InterviewSuccess)
    result = _turn(
        opened.state, FormResponse(values={"name": name, "description": description})
    )
    assert isinstance(result, InterviewFailure)
    assert result.state == opened.state
    assert isinstance(result.state.pending, FormRequest)


@pytest.mark.parametrize(
    ("step", "opener"),
    [
        (InterviewStep.BEHAVIOURS, "edit:EB-1"),
        (InterviewStep.BEHAVIOURS, "add:F-1"),
        (InterviewStep.CRITERIA, "add:EB-1"),
        (InterviewStep.CRITERIA, "edit:AC-1-1"),
        (InterviewStep.PERSONAS, "add:personas"),
        (InterviewStep.SCENARIOS, "edit:S-1"),
        (InterviewStep.TEST_CASES, "edit:TC-001"),
    ],
)
def test_a_review_form_cancels_or_goes_back_without_mutation(step, opener) -> None:
    """Every "+" and pen form is cancellable. Cancel returns to the review; Back while the
    form is open closes it and goes back, in one turn. Neither changes the Specification."""
    state = _review_state(step)
    opened = _turn(state, ChoiceResponse(selected=[opener]))
    assert isinstance(opened, InterviewSuccess)
    assert isinstance(opened.state.pending, FormRequest)
    assert opened.state.pending.cancellable
    before = opened.state.model_copy(deep=True)

    cancelled = _turn(opened.state, FormResponse(cancelled=True))
    assert isinstance(cancelled, InterviewSuccess)
    assert cancelled.state.pending.stage is step
    assert cancelled.state.pending.type == "choice"
    assert cancelled.state.specification == before.specification
    assert cancelled.state.user_typed == before.user_typed
    assert cancelled.state.issued_ids == before.issued_ids

    back = _turn(opened.state, ChoiceResponse(selected=["back"]))
    assert isinstance(back, InterviewSuccess)
    assert back.state.pending.stage is PREVIOUS_STEP[step]
    assert back.state.specification == before.specification

    invalid = _turn(
        opened.state, FormResponse(cancelled=True, values={"name": "Unexpected"})
    )
    assert isinstance(invalid, InterviewFailure)
    assert invalid.state == before
    stale = _turn(opened.state, FormResponse(cancelled=True), request_id="req-stale")
    assert isinstance(stale, InterviewFailure)
    assert stale.code == InterviewErrorCode.REQUEST_ID_MISMATCH


@pytest.mark.parametrize(
    "selected,values", [([], {}), (["continue"], {}), ([], {"invalid": 1})]
)
def test_review_feedback_is_exclusive_and_applies_in_one_turn(selected, values) -> None:
    class FeedbackInterviewer(ScriptedInterviewer):
        def chat(self, specification, step, text, target, context=None):
            return StepResult(
                message="Updated.",
                patches=[Patch(op=PatchOp.SET, path="target.name", value=text)],
            )

    pending = behaviours_screen(research_assistant(), "Review.")
    pending.request_id = "review-feedback"
    pending.stage = InterviewStep.BEHAVIOURS
    state = InterviewState(
        specification=research_assistant(), context=interview_context(), pending=pending
    )
    result = _turn(
        state,
        ChoiceResponse(feedback="Research helper", selected=selected, values=values),
        interviewer=FeedbackInterviewer(),
    )
    if selected or values:
        assert isinstance(result, InterviewFailure)
        assert result.state == state
    else:
        assert isinstance(result, InterviewSuccess)
        assert result.state.specification.target.name == "Research helper"
        assert result.state.pending.type == "choice"
        assert any(turn.text == "Research helper" for turn in result.state.history)
        assert state.specification.target.name == "Research assistant"
