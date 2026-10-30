"""The stable headless import surface."""

from metis.wizard import (
    AnyRequest,
    AnyResponse,
    ChatRequest,
    ChatResponse,
    ChoiceRequest,
    ChoiceResponse,
    CompilationError,
    CompileResult,
    FormRequest,
    FormResponse,
    InterviewEndRequest,
    InterviewFailure,
    InterviewRequest,
    InterviewResult,
    InterviewStartRequest,
    InterviewState,
    InterviewStep,
    InterviewSuccess,
    InterviewTurnRequest,
    Specification,
    UserResponse,
    WizardRequest,
    compile_experiment,
    compile_specification,
    derive_stage,
    handle_interview,
    render_review,
    write_experiment,
    write_review,
)


def test_the_headless_facade_exports_the_interview_contract_and_compiler() -> None:
    exported = (
        handle_interview,
        derive_stage,
        compile_specification,
        compile_experiment,
        render_review,
        write_experiment,
        write_review,
        InterviewState,
        InterviewStartRequest,
        InterviewTurnRequest,
        InterviewEndRequest,
        InterviewRequest,
        InterviewResult,
        InterviewSuccess,
        InterviewFailure,
        CompileResult,
        Specification,
        WizardRequest,
        UserResponse,
        AnyRequest,
        AnyResponse,
        ChatRequest,
        ChatResponse,
        ChoiceRequest,
        ChoiceResponse,
        FormRequest,
        FormResponse,
        CompilationError,
        InterviewStep,
    )
    assert all(name is not None for name in exported)


def test_the_facade_entrypoint_starts_a_serializable_interview() -> None:
    from tests.fixtures.wizard.scripted import ScriptedInterviewer

    result = handle_interview(
        InterviewStartRequest(
            description="A research assistant",
            known_capability_ids=[],
            capability_confidence="low",
        ),
        interviewer=ScriptedInterviewer(),
        matcher=None,
    )

    assert isinstance(result, InterviewSuccess)
    assert InterviewState.model_validate_json(result.state.model_dump_json())
