"""A scripted stand-in for the model.

Not a throwaway. This is how the whole corridor is exercised without paying per test run, and
it stays as the regression suite for the step prompts and the matcher once those are real: if
a prompt change breaks the shape the driver expects, this catches it offline.

It returns fixed, schema-conformant results. What it is *not* is a mock that asserts on calls
— the point is to drive real screens through real patch application, so everything downstream
of the model is genuinely under test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from metis.wizard.application import InterviewMessage
from metis.wizard.application.config import clarify_turn_cap
from metis.wizard.contracts import (
    ClarifyResult,
    Patch,
    PatchOp,
    Specification,
    StepResult,
)
from metis.wizard.domain.permissions import InterviewStep

if TYPE_CHECKING:
    from collections.abc import Iterable

    from metis.wizard.contracts import AnyRequest, InterviewContext, InterviewState
    from metis.wizard.domain.specification import Criterion


@dataclass
class ScriptedInterviewer:
    """Answers every step with a fixed, valid result."""

    clarify_questions: int = 2
    calls: list[str] = field(default_factory=list)

    def configure_criterion(
        self, criterion, previous, specification, request, context=None
    ):
        from metis.wizard.contracts.output import CriterionConfiguration

        return CriterionConfiguration(
            description=criterion.description, grader_args=criterion.grader_args
        )

    def clarify(
        self,
        specification: Specification,
        history: list[InterviewMessage],
        context: InterviewContext | None = None,
    ) -> ClarifyResult:
        self.calls.append("clarify")
        asked = sum(1 for t in history if t.role == "assistant")
        if history and history[0].text.startswith("Tell me about your target"):
            asked -= 1
        if asked >= self.clarify_questions:
            latest_answer = next(
                (
                    message.text
                    for message in reversed(history)
                    if message.role == "user"
                ),
                "",
            )
            patches = []
            if latest_answer and self.clarify_questions >= clarify_turn_cap():
                current_detail = specification.target.detail.strip()
                merged_detail = "\n".join(
                    part for part in (current_detail, latest_answer) if part
                )
                patches.append(
                    Patch(
                        op=PatchOp.SET,
                        path="target.detail",
                        value=merged_detail,
                    )
                )
            return ClarifyResult(message="", done=True, patches=patches)
        patches = []
        if not specification.target.description or not specification.target.users:
            patches = [
                Patch(
                    op=PatchOp.SET,
                    path="target.name",
                    value="Research assistant",
                ),
                Patch(
                    op=PatchOp.SET,
                    path="target.users",
                    value="Policy analysts",
                ),
                Patch(
                    op=PatchOp.SET,
                    path="target.description",
                    value="Answers research questions over an internal library.",
                ),
                Patch(
                    op=PatchOp.SET,
                    path="target.detail",
                    value="It uses search and can recover from a timeout.",
                ),
            ]
        return ClarifyResult(
            message=f"Question {asked + 1}: what does it do?",
            done=False,
            patches=patches,
        )

    def draft_behaviours(
        self,
        specification: Specification,
        history: list[InterviewMessage],
        context: InterviewContext | None = None,
    ) -> StepResult:
        self.calls.append("draft_behaviours")
        return StepResult(
            message="Here's what I think it should do. Have a look.",
            patches=[
                Patch(
                    op=PatchOp.ADD,
                    path="features",
                    value={
                        "name": "Answer quality",
                        "description": "Answer research questions accurately and with useful evidence.",
                        "behaviours": [
                            {
                                "name": "Source citations",
                                "description": "Cites a source for every claim",
                            },
                            {
                                "name": "Concise answers",
                                "description": "Keeps answers short",
                            },
                        ],
                    },
                ),
                Patch(
                    op=PatchOp.ADD,
                    path="features",
                    value={
                        "name": "Recovery",
                        "description": "Recover safely when document search cannot complete.",
                        "behaviours": [
                            {
                                "name": "Failure recovery",
                                "description": "Stops after repeated failures",
                            }
                        ],
                    },
                ),
            ],
        )

    def draft_criteria(
        self,
        specification: Specification,
        context: InterviewContext | None = None,
    ) -> StepResult:
        self.calls.append("draft_criteria")
        patches = []
        for behaviour in specification.measured_behaviours():
            if behaviour.criteria:
                continue
            feature = specification.feature_of(behaviour.id)
            patches.append(
                Patch(
                    op=PatchOp.ADD,
                    path=f"features[{feature.id}].behaviours[{behaviour.id}].criteria",
                    value={
                        "name": "Expected outcome",
                        "description": "Given "
                        + "a question it can answer"
                        + ", when "
                        + "the answer comes back"
                        + ", then "
                        + str(f"it satisfies: {behaviour.description.lower()}")
                        + ".",
                    },
                )
            )
        return StepResult(message="Here are the criteria.", patches=patches)

    def draft_personas(
        self,
        specification: Specification,
        context: InterviewContext | None = None,
    ) -> StepResult:
        self.calls.append("draft_personas")
        return StepResult(
            message="You're measuring citations and recovery, so these will stress both.",
            patches=[
                Patch(
                    op=PatchOp.ADD,
                    path="personas",
                    value={
                        "name": "Cooperative delegator",
                        "description": "Engages fully and answers questions willingly.",
                    },
                ),
                Patch(
                    op=PatchOp.ADD,
                    path="personas",
                    value={
                        "name": "Impatient executive",
                        "description": "Curt imperatives, no patience for clarification.",
                    },
                ),
            ],
        )

    def draft_scenarios(
        self,
        specification: Specification,
        context: InterviewContext | None = None,
    ) -> StepResult:
        self.calls.append("draft_scenarios")
        return StepResult(
            message="Two situations should cover everything you picked.",
            patches=[
                Patch(
                    op=PatchOp.ADD,
                    path="scenarios",
                    value={
                        "name": "Covered literature review",
                        "description": "Ask for a literature review on a covered topic.",
                    },
                ),
            ],
        )

    def draft_test_cases(
        self,
        specification: Specification,
        context: InterviewContext | None = None,
    ) -> StepResult:
        self.calls.append("draft_test_cases")
        used = {task.scenario_ref for task in specification.tasks}
        # Every Persona runs each new Scenario, and covers every measured Behaviour.
        return StepResult(
            message="Each persona runs the review.",
            patches=[
                Patch(
                    op=PatchOp.ADD,
                    path="tasks",
                    value={
                        "scenario_ref": scenario.id,
                        "persona_ref": persona.id,
                        "behaviour_refs": [
                            b.id for b in specification.measured_behaviours()
                        ],
                    },
                )
                for scenario in specification.scenarios
                if scenario.id not in used
                for persona in specification.personas
            ],
        )

    def chat(
        self,
        specification: Specification,
        step: str,
        text: str,
        target: str | None,
        context: InterviewContext | None = None,
    ) -> StepResult:
        self.calls.append("chat")
        return StepResult(message=f"Noted: {text}")


TRACE_BUDGET = "metis.library.graders.demo.DemoTraceBudgetGrader"


@dataclass
class ScriptedMatcher:
    """Give every generated Criterion one runnable offline grader.

    The interview flow tests need a criterion that compiles and that the engine's input gate
    accepts, not a meaningful match. DemoTraceBudgetGrader is the only grader written so far, a demo.
    """

    degraded: bool = False

    def match(self, _criterion: object, _behaviour: object = None) -> str:
        return TRACE_BUDGET

    def match_many(self, pairs: Iterable[tuple[Criterion, object]]) -> dict[str, str]:
        return {criterion.id: TRACE_BUDGET for criterion, _ in pairs}


@dataclass
class RejectingInterviewer(ScriptedInterviewer):
    """Tries to write two things it is never allowed to write.

    Used to prove the applier's refusals reach the user as runtime warnings rather than
    happening in silence.
    """

    def draft_criteria(
        self,
        specification: Specification,
        context: InterviewContext | None = None,
    ) -> StepResult:
        result = super().draft_criteria(specification, context=context)
        result.patches.append(
            Patch(
                op=PatchOp.SET,
                path="features[F-1].behaviours[EB-2].measured",
                value=True,
            )
        )
        return result


# ── the offline turn walk ──────────────────────────────────────────────────


@dataclass
class Walk:
    """The record of one scripted interview driven through `handle_interview`.

    `state` is the final client-held state; `seen` is every pending request rendered along the
    way, in order; `max_state_bytes` is the largest serialized state observed, so a test can
    assert the wire payload stays bounded.
    """

    state: InterviewState
    seen: list[AnyRequest]
    max_state_bytes: int
    used_end: bool


def walk(
    interviewer=None, matcher=None, *, send=None, description="A research assistant"
):
    """Drive a fresh interview to DONE through the Interview contract, round-tripping state as JSON.

    This is the offline corridor: one command in, one result out, exactly as a door drives it.
    After every accepted command the returned state is serialized and re-validated, so the walk
    proves the whole flow survives the wire and never touches a file or a network.

    By default the walk calls `handle_interview` in process with the given interviewer and matcher. A
    door test passes `send` — a callable that takes an `InterviewRequest` and returns the typed
    result — to drive the very same corridor over its own transport (HTTP, say), so the door and
    the in-process gate share one answer script rather than two copies of it.

    The script changes the Behaviour scope, goes Back from Criteria, opens and submits one typed
    Criterion form from a Behaviour's "+", and then uses explicit end from the Scenario review. This covers each request
    shape and both forward and backward lifecycle movement in one authoritative walk.
    """
    from metis.wizard import handle_interview
    from metis.wizard.contracts import (
        ChatRequest,
        ChatResponse,
        ChoiceRequest,
        ChoiceResponse,
        FormRequest,
        FormResponse,
        InterviewEndRequest,
        InterviewStartRequest,
        InterviewState,
        InterviewTurnRequest,
    )
    from metis.wizard.contracts.turn import InterviewSuccess

    def advance(request: ChoiceRequest) -> list[str]:
        return [
            str(o.id)
            for o in request.options
            if o.id.action == "continue" and o.enabled
        ]

    if matcher is None:
        matcher = ScriptedMatcher()

    def _in_process(request: object) -> object:
        return handle_interview(request, interviewer=interviewer, matcher=matcher)

    drive = send or _in_process

    state = None
    request: object = InterviewStartRequest(
        description=description,
        known_capability_ids=[],
        capability_confidence="low",
    )
    seen: list[object] = []
    max_bytes = 0
    scope_changed = False
    went_back = False
    opened_form = False
    used_end = False

    for _ in range(60):  # a bound, so a bug fails the test rather than hanging
        result = drive(request)
        assert isinstance(result, InterviewSuccess), (
            f"Interview failed: {getattr(result, 'code', None)} {getattr(result, 'message', '')}"
        )

        # The client owns persistence: prove the state survives a full JSON round trip every turn.
        serialized = result.state.model_dump_json()
        max_bytes = max(max_bytes, len(serialized.encode("utf-8")))
        state = InterviewState.model_validate_json(serialized)

        if result.outcome == "done":
            return Walk(
                state=state,
                seen=seen,
                max_state_bytes=max_bytes,
                used_end=used_end,
            )

        pending = state.pending
        assert pending is not None
        seen.append(pending)
        if isinstance(pending, ChatRequest):
            response: object = ChatResponse(text="It answers research questions.")
        elif isinstance(pending, FormRequest):
            response = FormResponse(
                values={field.id: "typed by hand" for field in pending.fields}
            )
        else:
            if pending.stage is InterviewStep.BEHAVIOURS and not scope_changed:
                selected = [
                    str(option.id)
                    for card in pending.cards
                    for option in card.options
                    if option.id.action == "tick" and option.selected
                ][:1]
                assert selected
                scope_changed = True
            elif pending.stage is InterviewStep.CRITERIA and not went_back:
                selected = [
                    str(option.id)
                    for option in pending.options
                    if option.id.action == "back"
                ]
                went_back = True
            elif pending.stage is InterviewStep.CRITERIA and not opened_form:
                selected = [
                    str(option.id)
                    for card in pending.cards
                    for option in card.options
                    if option.id.action == "add"
                ][:1]
                assert selected
                opened_form = True
            elif pending.stage is InterviewStep.SCENARIOS:
                request = InterviewEndRequest(state=state)
                used_end = True
                continue
            else:
                selected = advance(pending)
            response = ChoiceResponse(selected=selected)
        request = InterviewTurnRequest(
            state=state,
            request_id=pending.request_id or "",
            response=response,
        )

    raise AssertionError("the interview did not reach DONE within the walk bound")
