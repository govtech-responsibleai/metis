"""One typed Interview operation in, one result out — the whole interview as a stateless transaction.

`handle_interview` is the single entry a door drives. It takes one concrete Interview request,
runs exactly one operation against a fresh driver, and returns a typed Interview result. Nothing
here reads or writes a file: the state travels on the wire, so a CLI and a stateless HTTP server
rehydrate mid-conversation the same way.

Three properties hold the design together:

- **Stage is derived.** `derive_stage` reads the Specification and the two explicit locks to find the
  first incomplete stage; the client never stores a stage. While a request is pending, that
  request's own `stage` is authoritative instead.
- **Every operation is a transaction.** The operation runs on a deep copy. On full success the
  copy is returned; on a retryable failure the caller's original state comes back untouched, so a
  failed operation is safe to resend.
- **One place stamps identity.** After the operation runs, the single pending request — whatever
  built it — is stamped with a fresh `request_id` and the working stage. That id is what a later
  `InterviewTurnRequest` must echo, which is how a stale or duplicated answer is caught.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from uuid import uuid4

from metis.core.logging import get_logger
from metis.wizard.application.compile import (
    CompilationError,
    SpecificationArchive,
    SpecificationFixture,
    build_specification_archive,
    compile_experiment,
    to_yaml,
)
from metis.wizard.application.connection import binding_yaml, connected_specification
from metis.wizard.application.driver import (
    AFTER_BEHAVIOURS,
    PREVIOUS_STEP,
    DriverState,
    StepDriver,
)
from metis.wizard.application.interviewer import (
    InterviewContextBudgetError,
    InterviewerOutputError,
    InterviewerUnavailable,
)
from metis.wizard.application.readiness import (
    selected_specification,
    specification_readiness,
)
from metis.wizard.contracts.conversation import (
    ChatRequest,
    ChatResponse,
    ChoiceRequest,
    ChoiceResponse,
    FormRequest,
    FormResponse,
    editable_fields_of,
    options_of,
)
from metis.wizard.contracts.interview_state import (
    HISTORY_LIMIT,
    CapabilityEvidence,
    InterviewContext,
    InterviewMessage,
    InterviewState,
)
from metis.wizard.contracts.turn import (
    CompileResult,
    InterviewEndRequest,
    InterviewErrorCode,
    InterviewFailure,
    InterviewRequest,
    InterviewResult,
    InterviewStartRequest,
    InterviewSuccess,
    InterviewTurnRequest,
    MissingData,
)
from metis.wizard.domain.permissions import InterviewStep
from metis.wizard.domain.specification import (
    Specification,
    Target,
    collect_specification_ids,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from metis.wizard.application.interviewer import Interviewer
    from metis.wizard.contracts.connection import TargetConnection
    from metis.wizard.contracts.conversation import AnyResponse

# The interview has five stages, so a best-effort finish that clicks Continue on each cannot need
# more passes than that with headroom. The guard only stops a pathological non-advancing loop.
_FINISH_GUARD = 12
_DEFAULT_INTERVIEWER: Interviewer | None = None
_DEFAULT_MATCHER: object | None = None
_USE_CONFIGURED_MATCHER = object()
logger = get_logger(__name__)


def configure_interview_dependencies(
    interviewer: Interviewer, matcher: object | None = None
) -> None:
    """Set process-wide collaborators used when a caller omits per-call dependencies."""
    global _DEFAULT_INTERVIEWER, _DEFAULT_MATCHER
    _DEFAULT_INTERVIEWER = interviewer
    _DEFAULT_MATCHER = matcher


# ── stage derivation ─────────────────────────────────────────────────────────


def derive_stage(state: InterviewState) -> InterviewStep:
    """The first stage the Specification has not yet satisfied — the interview's position, computed.

    Read top to bottom: a missing target needs clarification; a Behaviour list that is empty,
    measures nothing, or has not been confirmed needs the Behaviour review; a measured Behaviour
    with no criteria needs the Criteria review; no personas needs the Persona review; no
    Scenarios needs the Scenario review; a Test Case set that is not runnable, or a review not
    yet confirmed, needs the Test Case review. Everything satisfied is DONE.
    """
    gaps = specification_readiness(state.specification, state.excluded_tasks)

    if any(gap.stage is InterviewStep.CLARIFY for gap in gaps):
        return InterviewStep.CLARIFY

    if (
        any(gap.stage is InterviewStep.BEHAVIOURS for gap in gaps)
        or not state.behaviours_confirmed
    ):
        return InterviewStep.BEHAVIOURS

    if any(gap.stage is InterviewStep.CRITERIA for gap in gaps):
        return InterviewStep.CRITERIA

    if any(gap.stage is InterviewStep.PERSONAS for gap in gaps):
        return InterviewStep.PERSONAS

    if any(gap.stage is InterviewStep.SCENARIOS for gap in gaps):
        return InterviewStep.SCENARIOS

    if (
        any(gap.stage is InterviewStep.TEST_CASES for gap in gaps)
        or not state.confirmed
    ):
        return InterviewStep.TEST_CASES

    return InterviewStep.DONE


def _effective_stage(state: InterviewState) -> InterviewStep:
    """Where the interview is *now*: a pending request's own stage, else the derived stage.

    A pending request is authoritative while it is live — a mid-step chat raised at Criteria is
    still Criteria even though the derived stage might read further ahead once its edit lands.
    """
    if state.pending is not None and state.pending.stage is not None:
        return state.pending.stage
    return derive_stage(state)


# ── the turn ───────────────────────────────────────────────────────────────


def handle_interview(
    request: InterviewRequest,
    *,
    interviewer: Interviewer | None = None,
    matcher: object | None = _USE_CONFIGURED_MATCHER,
) -> InterviewResult:
    """Run one Interview operation and return the next state or a typed failure."""
    if isinstance(request, InterviewStartRequest):
        interviewer = interviewer or _DEFAULT_INTERVIEWER
        if interviewer is None:
            raise InterviewerUnavailable(
                "No wizard interviewer is configured for this process."
            )
        resolved_matcher = (
            _DEFAULT_MATCHER if matcher is _USE_CONFIGURED_MATCHER else matcher
        )
        return _start(request, interviewer, resolved_matcher)

    state = request.state
    reopen = isinstance(request, InterviewTurnRequest) and _is_back_from_done(
        request, state
    )
    if isinstance(request, InterviewTurnRequest) and not reopen:
        rejection = _validate_respond(request, state)
        if rejection is not None:
            return rejection

    if (
        isinstance(request, InterviewEndRequest)
        and state.pending is None
        and state.confirmed
        and derive_stage(state) is InterviewStep.DONE
    ):
        return InterviewSuccess(
            state=state,
            stage=InterviewStep.DONE,
            missing=[],
            outcome="done",
        )

    interviewer = interviewer or _DEFAULT_INTERVIEWER
    if interviewer is None:
        raise InterviewerUnavailable(
            "No wizard interviewer is configured for this process."
        )
    resolved_matcher = (
        _DEFAULT_MATCHER if matcher is _USE_CONFIGURED_MATCHER else matcher
    )

    # From here every path is a transaction: the operation runs on a deep copy, and the caller's
    # own state is returned untouched on any retryable failure.
    working = _lift(state, _effective_stage(state))
    driver = StepDriver(interviewer=interviewer, matcher=resolved_matcher)
    before = working.specification.model_copy(deep=True)

    if isinstance(request, InterviewEndRequest):
        return _finish(working, state, interviewer, resolved_matcher)

    if reopen:
        # Back from a completed Interview reopens its last review. Nothing in the
        # Specification changes, and the final lock must be earned again with Continue.
        working.step = InterviewStep.TEST_CASES
        working.confirmed = False
        try:
            working.pending = driver.compose(working)
            if driver.model_error is not None:
                raise driver.model_error
        except InterviewerOutputError as exc:
            return _model_unavailable(state, exc, working)
        except Exception as exc:
            return _internal_error(state, exc)
        return _awaiting(working)

    try:
        if isinstance(request.response, ChatResponse):
            working.history.append(
                InterviewMessage(role="user", text=request.response.text)
            )
        if isinstance(request.response, ChoiceResponse) and request.response.feedback:
            working.history.append(
                InterviewMessage(role="user", text=request.response.feedback)
            )
        # Bound the history now. A failure below projects this working state as its
        # diagnostic, and the state model refuses a history longer than the limit.
        working.history = working.history[-HISTORY_LIMIT:]
        _apply_response(working, driver, request.response)
        if driver.model_error is not None:
            raise driver.model_error
    except InterviewerOutputError as exc:
        return _model_unavailable(state, exc, working)
    except Exception as exc:
        return _internal_error(state, exc)

    _reconcile_locks(working, before, answered_at=_effective_stage(state))

    # Continue on a ready Test Case review advanced the driver to DONE; finalize it.
    if working.step is InterviewStep.DONE:
        return _finalize(working, state)

    try:
        if working.pending is None:
            working.pending = driver.compose(working)
        if driver.model_error is not None:
            raise driver.model_error
    except InterviewerOutputError as exc:
        return _model_unavailable(state, exc, working)
    except Exception as exc:
        return _internal_error(state, exc)

    _record_assistant(working)
    return _awaiting(working)


def _start(
    request: InterviewStartRequest,
    interviewer: Interviewer,
    matcher: object | None,
) -> InterviewResult:
    """Begin a fresh interview with the user's description as its first input."""
    specification = Specification.model_validate(
        {"target": Target(name="", description=request.description, users="")}
    )
    working = _lift(
        InterviewState(
            specification=specification,
            context=InterviewContext(
                perspective=request.perspective,
                capability_evidence=CapabilityEvidence(
                    known_capability_ids=request.known_capability_ids,
                    confidence=request.capability_confidence,
                )
                if request.known_capability_ids is not None
                and request.capability_confidence is not None
                else None,
                opening_description=request.description,
                documents=request.documents,
                connection=request.connection,
            ),
            history=[InterviewMessage(role="user", text=request.description)],
            issued_ids=collect_specification_ids(specification),
        ),
        InterviewStep.CLARIFY,
    )
    driver = StepDriver(interviewer=interviewer, matcher=matcher)
    try:
        working.pending = driver.compose(working)
        if driver.model_error is not None:
            raise driver.model_error
    except InterviewerOutputError as exc:
        return _model_unavailable(None, exc, working)
    except Exception as exc:
        return _internal_error(None, exc)
    _record_assistant(working)
    return _awaiting(working)


def _apply_response(
    working: DriverState, driver: StepDriver, response: AnyResponse
) -> None:
    """Consume the pending request with the user's answer, cascade question or plain screen."""
    pending = working.pending
    working.pending = None
    if (
        pending is None
    ):  # _validate_respond guarantees a pending request; narrow for the type
        return

    driver.handle(working, pending, response)


def _finish(
    working: DriverState,
    original: InterviewState,
    interviewer: Interviewer,
    matcher: object | None,
) -> InterviewResult:
    """Drive the remaining stages to DONE without asking, then check the Specification is runnable.

    Best-effort: each stage is composed (which drafts any missing content) and its Continue is
    clicked. Clarification is abandoned rather than continued. A held Test Case gate — a
    set the readiness check still rejects — stops the drive and returns `completion_failed` with
    the gaps, leaving the caller's original state untouched.
    """
    if (
        working.step is InterviewStep.DONE
        and working.pending is None
        and working.confirmed
    ):
        return _done(working)

    driver = StepDriver(interviewer=interviewer, matcher=matcher)
    # Client-held state can validly arrive at any stage with existing Criteria that have not yet
    # been matched. End owns the complete best-effort path, so resolve them before it advances.
    try:
        driver.complete_target(working)
        if driver.model_error is not None:
            return _model_unavailable(original, driver.model_error, working)
        driver.match(working)
    except InterviewerOutputError as exc:
        return _model_unavailable(original, exc, working)
    except Exception as exc:
        return _internal_error(original, exc)

    for _ in range(_FINISH_GUARD):
        if working.step is InterviewStep.DONE:
            break
        if working.step is InterviewStep.CLARIFY:
            working.step = InterviewStep.BEHAVIOURS
            continue
        try:
            screen = driver.compose(working)
        except InterviewerOutputError as exc:
            return _model_unavailable(original, exc, working)
        except Exception as exc:
            return _internal_error(original, exc)
        if driver.model_error is not None:
            return _model_unavailable(original, driver.model_error, working)
        offered = options_of(screen)
        advance = [
            key
            for key, option in offered.items()
            if option.id.action == "continue" and option.enabled
        ]
        if not advance:
            break  # a gate is holding this stage; a best-effort pass cannot force it
        working.pending = None
        try:
            driver.handle(working, screen, ChoiceResponse(selected=advance[:1]))
        except InterviewerOutputError as exc:
            return _model_unavailable(original, exc, working)
        except Exception as exc:
            return _internal_error(original, exc)
        if driver.model_error is not None:
            return _model_unavailable(original, driver.model_error, working)

    working.pending = None
    gaps = _completion_gaps(working)
    if working.step is InterviewStep.DONE and not gaps:
        if not original.confirmed and working.context.documents:
            # Early fixture names and model suggestions are proposals. Even a complete
            # Specification must pass through the Test Case review before it is confirmed.
            working.step = InterviewStep.TEST_CASES
            try:
                working.pending = driver.compose(working)
            except InterviewerOutputError as exc:
                return _model_unavailable(original, exc, working)
            except Exception as exc:
                return _internal_error(original, exc)
            if driver.model_error is not None:
                return _model_unavailable(original, driver.model_error, working)
            _record_assistant(working)
            return _awaiting(working)
        working.confirmed = True
        return _done(working)
    return InterviewFailure(
        code=InterviewErrorCode.COMPLETION_FAILED,
        message="I couldn't finish this into a runnable evaluation on my own.",
        retryable=False,
        state=original,
        missing=gaps,
        diagnostic_state=_to_client(working),
    )


def _finalize(working: DriverState, original: InterviewState) -> InterviewResult:
    """Seal an interview that Continue drove to DONE, verifying the Specification is runnable."""
    gaps = _completion_gaps(working)
    if gaps:  # the Test Case gate should have blocked Continue; refuse rather than emit a bad set
        return InterviewFailure(
            code=InterviewErrorCode.COMPLETION_FAILED,
            message="This evaluation is not runnable yet.",
            retryable=False,
            state=original,
            missing=gaps,
        )
    # A completed Interview holds both locks, so it always derives DONE.
    working.confirmed = True
    working.behaviours_confirmed = True
    working.pending = None
    return _done(working)


# ── validation ───────────────────────────────────────────────────────────────


def _validate_respond(
    request: InterviewTurnRequest, state: InterviewState
) -> InterviewFailure | None:
    """The binding checks: something to answer, the right id, the right kind, offered inputs.

    Each returns the caller's state unchanged, because none of them mutated anything — a rejected
    answer is always safe to correct and resend.
    """
    pending = state.pending
    if pending is None:
        return _reject(
            InterviewErrorCode.NO_PENDING_REQUEST,
            "There is no request to answer.",
            state,
        )
    if request.request_id != pending.request_id:
        return _reject(
            InterviewErrorCode.REQUEST_ID_MISMATCH,
            "This answer is for a different or older request.",
            state,
        )
    response = request.response
    if isinstance(pending, FormRequest) and _is_bare_back(response):
        # Back while a form is open closes the form and goes back in one turn. The form's
        # own stage must have an earlier step; the first step offers no Back.
        if pending.stage not in PREVIOUS_STEP:
            return _not_offered(state)
        return None
    if response.type != pending.type:
        return _reject(
            InterviewErrorCode.RESPONSE_TYPE_MISMATCH,
            "This answer does not match the kind of request that is pending.",
            state,
        )

    if isinstance(response, ChoiceResponse):
        if response.feedback and (
            not isinstance(pending, ChoiceRequest)
            or not pending.feedback_placeholder
            or not response.feedback.strip()
            or response.selected
            or response.values
        ):
            return _not_offered(state)
        offered = options_of(pending)
        editable = editable_fields_of(pending)
        for key in response.selected:
            if key not in offered:
                return _not_offered(state)

        for key in response.values:
            if key not in editable:
                return _not_offered(state)
    elif isinstance(response, FormResponse):
        if (
            isinstance(pending, FormRequest)
            and not response.cancelled
            and any(
                field.required and not response.values.get(field.id, "").strip()
                for field in pending.fields
            )
        ):
            # Only a required field must be non-blank. An optional field, such as
            # metadata, may be sent empty.
            return _reject(
                InterviewErrorCode.RESPONSE_NOT_OFFERED,
                "Fill in every required field. Your content was not changed.",
                state,
            )
        if response.cancelled and (
            not isinstance(pending, FormRequest)
            or not pending.cancellable
            or response.values
        ):
            return _not_offered(state)
        fields = (
            {field.id for field in pending.fields}
            if isinstance(pending, FormRequest)
            else set()
        )
        for key in response.values:
            if key not in fields:
                return _not_offered(state)

    return None


def _is_bare_back(response: AnyResponse) -> bool:
    return (
        isinstance(response, ChoiceResponse)
        and response.selected == ["back"]
        and not response.values
        and not response.feedback
    )


def _is_back_from_done(request: InterviewTurnRequest, state: InterviewState) -> bool:
    """True for Back sent to a completed Interview, which has no pending request.

    There is no request to bind, so `request_id` is not checked. Send an empty string.
    """
    return state.pending is None and state.confirmed and _is_bare_back(request.response)


def _reconcile_locks(
    working: DriverState,
    before: Specification,
    *,
    answered_at: InterviewStep = InterviewStep.BEHAVIOURS,
) -> None:
    """Clear the confirmation locks that an accepted mutation invalidates.

    Any change to the Specification clears the final `confirmed` lock, so an earlier sign-off can never
    cover new content. A change to the measurement scope itself — the Feature or Behaviour set, or a
    measured flag — also clears `behaviours_confirmed`, so re-scoping demands a fresh Continue.

    The exception is a scope change that the user made on a later review (a pen at Criteria, or
    chat feedback at Scenarios). The user made that change in view, and the turn already drafts
    any missing Criteria and updates Test Case coverage. Clearing the lock there would send a
    later Continue back to Behaviours, or leave a completed Interview that derives Behaviours.
    """
    if working.specification == before:
        return
    working.confirmed = False
    if answered_at in AFTER_BEHAVIOURS:
        return
    if _scope_signature(working.specification) != _scope_signature(before):
        working.behaviours_confirmed = False


def _scope_signature(specification: Specification) -> object:
    """The measurement scope, reduced to what a change to it would move."""
    return (
        tuple(
            (behaviour.id, behaviour.name, behaviour.description, behaviour.measured)
            for behaviour in specification.behaviours()
        ),
        tuple(
            (feature.id, feature.name, feature.description)
            for feature in specification.features
        ),
    )


# ── compilation ──────────────────────────────────────────────────────────────


def compile_specification(specification: Specification) -> CompileResult:
    """Compile a confirmed Specification to the `specification.yaml` string, writing nothing to disk.

    Reuses the same pure compile the CLI and golden-file test use; a caller that wants a file
    writes the returned string itself. Raises `CompilationError` when the Specification will not build
    a valid specification.
    """
    gaps = specification_readiness(specification)
    if gaps:
        raise CompilationError(
            "Specification is not runnable: " + "; ".join(gap.message for gap in gaps)
        )
    document = compile_experiment(specification, experiment_id(specification))
    return CompileResult.model_validate(
        {
            "specification.yaml": to_yaml(document),
            "specification": document,
        }
    )


def package_specification(
    source: Specification | InterviewState,
    fixtures: Iterable[SpecificationFixture],
    *,
    connection: TargetConnection | None = None,
) -> SpecificationArchive:
    """Compile a manual Specification or final Interview state into a portable export.

    A target connection exports `target-binding.yaml` next to `specification.yaml`, which then
    names the generic runner and the binding file. An Interview takes its connection from its
    state. A manual Specification takes it from `connection`, so both give the same export for
    the same binding.

    :raises ValueError: `connection` is given with an Interview state.
    """
    if isinstance(source, InterviewState):
        if connection is not None:
            raise ValueError(
                "An Interview state carries its own connection; do not pass one."
            )
        connection = source.context.connection
    # An Interview exports only the Test Cases that the user kept selected.
    specification = connected_specification(
        selected_specification(source.specification, source.excluded_tasks)
        if isinstance(source, InterviewState)
        else source,
        connection,
    )
    gaps = specification_readiness(specification)
    if gaps:
        raise CompilationError(
            "Specification is not runnable: " + "; ".join(gap.message for gap in gaps)
        )
    document = compile_experiment(specification, experiment_id(specification))
    return build_specification_archive(
        document,
        fixtures,
        interview_state_json=source.model_dump_json()
        if isinstance(source, InterviewState)
        else None,
        target_binding_yaml=binding_yaml(connection) if connection else None,
    )


def experiment_id(specification: Specification) -> str:
    """A filename-safe id from the target name, falling back when it is empty."""
    if specification.id:
        return specification.id
    slug = re.sub(r"[^a-z0-9]+", "-", specification.target.name.lower()).strip("-")
    return slug or "experiment"


# ── result and state plumbing ──────────────────────────────────────────────


def _lift(state: InterviewState, step: InterviewStep) -> DriverState:
    """Lift a client value into the driver's working type, carrying the stage the driver needs."""
    copy = state.model_copy(deep=True)
    return DriverState(
        step=step,
        **{name: getattr(copy, name) for name in InterviewState.model_fields},
    )


def _to_client(working: DriverState) -> InterviewState:
    """Project the working state back to the client value, dropping the derived stage."""
    return InterviewState(
        **{name: getattr(working, name) for name in InterviewState.model_fields}
    )


def _stamp(working: DriverState) -> None:
    """Stamp the single pending request with a fresh id and the working stage.

    The one choke point for request identity: whatever built the pending request — the driver, a
    cascade edit, a compose — it is stamped here, so no screen builder sets these and a fresh id
    is guaranteed for every composition.
    """
    if working.pending is not None:
        working.pending.request_id = f"req-{uuid4().hex}"
        working.pending.stage = working.step


def _record_assistant(working: DriverState) -> None:
    """Record a composed clarification question as an assistant message, and bound the history.

    Only chat messages are kept: the history exists for clarification context, and the review screens
    are not conversation. Bounding here keeps the wire payload small.
    """
    if isinstance(working.pending, ChatRequest):
        working.history.append(
            InterviewMessage(role="assistant", text=working.pending.prompt)
        )
    working.history = working.history[-HISTORY_LIMIT:]


def _awaiting(working: DriverState) -> InterviewSuccess:
    _stamp(working)
    client = _to_client(working)
    return InterviewSuccess(
        state=client,
        stage=_effective_stage(client),
        missing=_completion_gaps(client),
        outcome="awaiting_response",
    )


def _done(working: DriverState) -> InterviewSuccess:
    working.history = working.history[-HISTORY_LIMIT:]
    client = _to_client(working)
    return InterviewSuccess(
        state=client,
        stage=InterviewStep.DONE,
        missing=[],
        outcome="done",
    )


def _reject(
    code: InterviewErrorCode, message: str, state: InterviewState
) -> InterviewFailure:
    return InterviewFailure(code=code, message=message, retryable=False, state=state)


def _not_offered(state: InterviewState) -> InterviewFailure:
    return _reject(
        InterviewErrorCode.RESPONSE_NOT_OFFERED,
        "That option or field was not offered on this screen.",
        state,
    )


def _model_unavailable(
    state: InterviewState | None, error: InterviewerOutputError, working: DriverState
) -> InterviewFailure:
    if isinstance(error, InterviewContextBudgetError):
        return InterviewFailure(
            code=InterviewErrorCode.CONTEXT_BUDGET_EXCEEDED,
            diagnostic_state=_to_client(working),
            message=str(error),
            retryable=False,
            state=state,
        )
    return InterviewFailure(
        code=InterviewErrorCode.MODEL_UNAVAILABLE,
        message="The model could not return a usable result; nothing was changed.",
        diagnostic_message=str(error),
        diagnostic_state=_to_client(working),
        retryable=True,
        state=state,
    )


def _internal_error(state: InterviewState | None, exc: Exception) -> InterviewFailure:
    """Return a stable non-retryable failure without exposing an implementation traceback."""
    logger.exception(
        "wizard_interview_internal_error",
        error_type=type(exc).__name__,
    )
    return InterviewFailure(
        code=InterviewErrorCode.INTERNAL_ERROR,
        message="The wizard could not complete this turn.",
        retryable=False,
        state=state,
    )


def _completion_gaps(state: InterviewState) -> list[MissingData]:
    """Return all missing prerequisites before a result may claim `done`."""
    return specification_readiness(state.specification, state.excluded_tasks)


__all__ = [
    "MissingData",
    "compile_specification",
    "package_specification",
    "derive_stage",
    "experiment_id",
    "configure_interview_dependencies",
    "handle_interview",
]
