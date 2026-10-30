"""Corrections update related model content and preserve user decisions."""

import pytest

from metis.wizard import (
    InterviewFailure,
    InterviewSuccess,
    InterviewTurnRequest,
    handle_interview,
)
from metis.wizard.application.driver import DriverState, StepDriver
from metis.wizard.application.interviewer import InterviewerOutputError
from metis.wizard.contracts import ChatRequest, ChatResponse, Patch, PatchOp, StepResult
from metis.wizard.contracts.interview_state import InterviewState
from metis.wizard.domain.cascade import impacts_for
from metis.wizard.domain.permissions import InterviewStep
from tests.fixtures.wizard.context import interview_context
from tests.fixtures.wizard.scripted import ScriptedInterviewer
from tests.fixtures.wizard.specifications import research_assistant

DESCRIPTION = "features[F-1].behaviours[EB-1].description"
CRITERION = "features[F-1].behaviours[EB-1].criteria[AC-1-2].description"
TYPED = "features[F-1].behaviours[EB-1].criteria[AC-1-1].description"


def edit(path: str, value: str = "Updated wording") -> Patch:
    return Patch(op=PatchOp.SET, path=path, value=value)


class CorrectingInterviewer(ScriptedInterviewer):
    def chat(self, specification, step, text, target, context=None):
        self.calls.append("chat")
        if text == "Correct the behaviour":
            return StepResult(
                message="Updated the Behaviour.", patches=[edit(DESCRIPTION)]
            )
        return StepResult(
            message="Updated the related checks.",
            patches=[
                edit(CRITERION),
                edit(TYPED),
                edit("scenarios[S-1].description"),
                edit("features[F-1].behaviours[EB-2].description"),
                Patch(op=PatchOp.REMOVE, path="features[F-1].behaviours[EB-1]"),
            ],
        )


def correction_state() -> InterviewState:
    return InterviewState(
        specification=research_assistant(),
        context=interview_context(),
        user_typed={"AC-1-1"},
        pending=ChatRequest(
            prompt="What would you like to change?",
            request_id="req-correction",
            stage=InterviewStep.BEHAVIOURS,
            target="EB-1",
        ),
    )


def test_correction_updates_related_content_and_preserves_user_work() -> None:
    state = correction_state()
    before = state.specification.model_copy(deep=True)
    interviewer = CorrectingInterviewer()
    result = handle_interview(
        InterviewTurnRequest(
            state=state,
            request_id="req-correction",
            response=ChatResponse(text="Correct the behaviour"),
        ),
        interviewer=interviewer,
        matcher=None,
    )
    assert isinstance(result, InterviewSuccess)
    after = result.state.specification
    assert after.behaviour("EB-1").description == "Updated wording"
    assert after.criterion("AC-1-2").description == "Updated wording"
    assert after.scenario("S-1").description == "Updated wording"
    assert after.criterion("AC-1-1") == before.criterion("AC-1-1")
    assert after.behaviour("EB-2") == before.behaviour("EB-2")
    assert after.tasks == before.tasks
    assert [item.measured for item in after.behaviours()] == [
        item.measured for item in before.behaviours()
    ]
    assert result.state.pending.type == "choice"
    assert interviewer.calls == ["chat", "chat"]
    assert state.specification == before


def test_dependent_model_failure_preserves_the_complete_input_state() -> None:
    class Unavailable(CorrectingInterviewer):
        def chat(self, specification, step, text, target, context=None):
            if text != "Correct the behaviour":
                raise InterviewerOutputError("Service unavailable")
            return super().chat(specification, step, text, target, context)

    state = correction_state()
    result = handle_interview(
        InterviewTurnRequest(
            state=state,
            request_id="req-correction",
            response=ChatResponse(text="Correct the behaviour"),
        ),
        interviewer=Unavailable(),
        matcher=None,
    )
    assert isinstance(result, InterviewFailure)
    assert result.retryable
    assert result.state == state


@pytest.mark.parametrize("measured", [False, True])
def test_automatic_corrections_add_missing_criteria_for_selected_behaviours(
    measured: bool,
) -> None:
    class AddingCriteria(ScriptedInterviewer):
        def chat(self, specification, step, text, target, context=None):
            if text == "Change the Feature":
                return StepResult(
                    message="Updated the Feature.",
                    patches=[edit("features[F-1].description")],
                )
            return StepResult(
                message="Updated the checks.",
                patches=[
                    Patch(
                        op=PatchOp.ADD,
                        path="features[F-1].behaviours[EB-1].criteria",
                        value={
                            "name": "Supported answer",
                            "description": "Given a factual question, the answer cites a supporting source.",
                        },
                    )
                ],
            )

    specification = research_assistant()
    behaviour = specification.behaviour("EB-1")
    assert behaviour is not None
    behaviour.measured = measured
    behaviour.criteria = []
    state = DriverState(
        specification=specification,
        context=interview_context(),
        step=InterviewStep.BEHAVIOURS,
    )
    StepDriver(interviewer=AddingCriteria()).handle(
        state,
        ChatRequest(prompt="Change", target="F-1"),
        ChatResponse(text="Change the Feature"),
    )
    assert behaviour.measured is measured
    assert len(behaviour.criteria) == int(measured)


@pytest.mark.parametrize(
    ("stage", "target", "allowed"),
    [
        (InterviewStep.BEHAVIOURS, "EB-1", {DESCRIPTION, CRITERION}),
        (InterviewStep.BEHAVIOURS, "F-1", {DESCRIPTION, CRITERION}),
        (InterviewStep.CRITERIA, "EB-1", {CRITERION}),
    ],
)
def test_scoped_corrections_apply_only_inside_the_selected_item(
    stage, target, allowed
) -> None:
    class Scoped(ScriptedInterviewer):
        def chat(self, specification, step, text, target, context=None):
            if text != "Change":
                return StepResult(message="Updated.")
            return StepResult(
                message="Updated.",
                patches=[
                    edit(DESCRIPTION),
                    edit(CRITERION),
                    edit("personas[cooperative-delegator].description"),
                ],
            )

    state = DriverState(
        specification=research_assistant(), context=interview_context(), step=stage
    )
    before = state.specification.model_copy(deep=True)
    driver = StepDriver(interviewer=Scoped())
    driver.handle(
        state, ChatRequest(prompt="Change", target=target), ChatResponse(text="Change")
    )
    assert (
        state.specification.behaviour("EB-1").description
        != before.behaviour("EB-1").description
    ) == (DESCRIPTION in allowed)
    assert (
        state.specification.criterion("AC-1-2").description
        != before.criterion("AC-1-2").description
    ) == (CRITERION in allowed)
    assert state.specification.personas == before.personas
    assert driver.pending_warnings


def test_impact_groups_follow_target_feature_and_behaviour_context() -> None:
    spec = research_assistant()
    assert [
        item.kind for item in impacts_for(spec, [edit(DESCRIPTION), edit(DESCRIPTION)])
    ] == ["criteria", "scenario"]
    assert [
        item.kind
        for item in impacts_for(
            spec, [edit("target.description"), edit("target.detail")]
        )
    ] == ["tree"]
    assert [
        item.kind for item in impacts_for(spec, [edit("features[F-1].description")])
    ] == ["feature"]
    assert impacts_for(spec, [edit("target.name")]) == []


# ── the Target review form after Back ──────────────────────────────────────


def a_state(step: InterviewStep) -> DriverState:
    return DriverState(
        specification=research_assistant(), context=interview_context(), step=step
    )


def _submit_target_review(
    changes: dict[str, str], *, stored_description: str | None = None
) -> tuple[DriverState, CorrectingInterviewer]:
    from metis.wizard.application import screens
    from metis.wizard.contracts import FormResponse

    state = a_state(step=InterviewStep.CLARIFY)
    if stored_description is not None:
        state.specification.target.description = stored_description
    interviewer = CorrectingInterviewer()
    form = screens.target_review_form(state.specification)
    values = {field.id: field.value for field in form.fields}
    values.update(changes)
    StepDriver(interviewer=interviewer).handle(state, form, FormResponse(values=values))
    return state, interviewer


def test_a_target_description_edit_on_review_updates_derived_content() -> None:
    state, interviewer = _submit_target_review(
        {"target.description": "An agent that drafts policy briefs."}
    )

    assert state.specification.target.description == (
        "An agent that drafts policy briefs."
    )
    assert interviewer.calls == ["chat"]
    assert state.specification.criterion("AC-1-2").description == "Updated wording"
    assert state.step is InterviewStep.BEHAVIOURS


@pytest.mark.parametrize("stored_suffix", [None, "  \n"])
def test_a_target_review_with_no_derived_change_drafts_nothing(
    stored_suffix: str | None,
) -> None:
    stored = (
        research_assistant().target.description + stored_suffix
        if stored_suffix
        else None
    )
    renamed, renamed_calls = _submit_target_review({"target.name": "Librarian"})
    unchanged, unchanged_calls = _submit_target_review({}, stored_description=stored)

    assert renamed_calls.calls == unchanged_calls.calls == []
    assert renamed.specification.target.name == "Librarian"
    if stored is None:
        assert unchanged.specification == research_assistant()
    else:
        assert unchanged.specification.target.description == stored
    assert unchanged.step is InterviewStep.BEHAVIOURS
