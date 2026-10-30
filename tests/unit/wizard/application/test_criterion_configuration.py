"""Complete assessment edits and direct field ownership."""

import json

import pytest
from pydantic import ValidationError

from metis.core.profile import Criterion
from metis.wizard import (
    InterviewFailure,
    InterviewSuccess,
    InterviewTurnRequest,
    handle_interview,
)
from metis.wizard.contracts.conversation import ChatRequest, ChatResponse
from metis.wizard.contracts.interview_state import InterviewState
from metis.wizard.contracts.output import CriterionConfiguration, StepResult
from metis.wizard.domain.patch import Patch, PatchOp
from metis.wizard.domain.permissions import InterviewStep
from tests.fixtures.wizard.context import interview_context
from tests.fixtures.wizard.scripted import (
    TRACE_BUDGET,
    ScriptedInterviewer,
    ScriptedMatcher,
)
from tests.fixtures.wizard.specifications import research_assistant
from tests.unit.wizard.adapters.llm.test_gateway import interviewer


@pytest.mark.parametrize("text", ["", "   ", 12])
def test_assessment_requires_nonempty_text(text) -> None:
    with pytest.raises(ValidationError):
        Criterion(id="AC-1-1", name="Budget", description=text)


def test_legacy_assessment_has_a_recovery_action() -> None:
    with pytest.raises(ValidationError, match="Replace its description"):
        Criterion.model_validate(
            dict(
                id="AC-1-1",
                name="Budget",
                description=dict(given="g", when="w", then="t"),
            )
        )


def test_configuration_uses_the_actual_settings_schema_and_full_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.example")
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test")
    proposed = Criterion(
        id="AC-1-1",
        name="Trace budget",
        description="The session stays within its trace budget.",
        grader_fqn=TRACE_BUDGET,
    )
    previous = proposed.model_copy(update={"grader_args": {"max_traces": 10}})
    gateway, calls = interviewer(
        [
            json.dumps(
                {
                    "description": "The session uses at most 3 traces.",
                    "grader_args": {"max_traces": 0},
                }
            ),
            json.dumps(
                {
                    "description": "The session uses at most 3 traces.",
                    "grader_args": {"max_traces": 3},
                }
            ),
        ]
    )
    result = gateway.configure_criterion(
        proposed,
        previous,
        research_assistant(),
        "Change the limit to 3.",
        interview_context(),
    )
    assert result.grader_args["max_traces"] == 3
    assert result.description == "The session uses at most 3 traces."
    assert len(calls.calls) == 2
    payload = json.loads(calls.calls[0]["messages"][1]["content"])
    assert payload["request"] == "Change the limit to 3."
    assert payload["previous_criterion"]["grader_args"] == {"max_traces": 10}
    assert payload["settings_schema"]["properties"]["max_traces"]["minimum"] == 1


def test_judge_input_limit_is_left_to_the_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from metis.wizard.application.criterion_forms import settings_fields
    from metis.wizard.application.matching import CRITERION_JUDGE_FQN

    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.example")
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test")
    proposed = Criterion(
        id="AC-1-1",
        name="Deck length",
        description="The deck contains exactly 10 slides.",
        grader_fqn=CRITERION_JUDGE_FQN,
    )
    previous = proposed.model_copy(update={"grader_args": {"max_input_tokens": 5000}})
    assert "args.max_input_tokens" not in {f.id for f in settings_fields(proposed)}

    gateway, calls = interviewer(
        [
            json.dumps(
                {
                    "description": "The deck contains exactly 10 slides.",
                    "grader_args": {},
                }
            )
        ]
    )
    result = gateway.configure_criterion(
        proposed, previous, research_assistant(), "", interview_context()
    )
    payload = json.loads(calls.calls[0]["messages"][1]["content"])
    assert "max_input_tokens" not in payload["settings_schema"]["properties"]
    assert result.grader_args["max_input_tokens"] == 5000


@pytest.mark.parametrize("valid", [True, False])
def test_guided_edit_commits_one_complete_criterion_or_keeps_the_previous_state(
    valid,
) -> None:
    spec = research_assistant()
    old = spec.criterion("AC-1-1")
    old.grader_fqn = TRACE_BUDGET
    old.grader_args = {"max_traces": 10}
    state = InterviewState(
        specification=spec,
        context=interview_context(),
        behaviours_confirmed=True,
        pending=ChatRequest(
            prompt="What changes?",
            request_id="edit-1",
            stage=InterviewStep.CRITERIA,
            target="EB-1",
        ),
    )
    snapshot = state.model_dump(mode="json")

    class Editor(ScriptedInterviewer):
        def chat(self, specification, step, text, target, context=None):
            return StepResult(
                message="",
                patches=[
                    Patch(
                        op=PatchOp.SET,
                        path="features[F-1].behaviours[EB-1].criteria[AC-1-1].description",
                        value="The session stays within its trace budget.",
                    )
                ],
            )

        def configure_criterion(
            self, criterion, previous, specification, request, context=None
        ):
            assert request == "Change the limit to 3."
            assert previous.grader_args["max_traces"] == 10
            return CriterionConfiguration(
                description="The session uses at most 3 traces.",
                grader_args={"max_traces": 3 if valid else 0},
            )

    result = handle_interview(
        InterviewTurnRequest(
            state=state,
            request_id="edit-1",
            response=ChatResponse(text="Change the limit to 3."),
        ),
        interviewer=Editor(),
        matcher=ScriptedMatcher(),
    )
    assert state.model_dump(mode="json") == snapshot
    if valid:
        assert isinstance(result, InterviewSuccess)
        updated = result.state.specification.criterion(old.id)
        assert updated.id == old.id
        assert updated.grader_fqn == TRACE_BUDGET
        assert updated.grader_args == {"max_traces": 3}
        assert updated.description == "The session uses at most 3 traces."
    else:
        assert isinstance(result, InterviewFailure)
        assert result.state.model_dump(mode="json") == snapshot
