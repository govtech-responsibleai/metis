"""The Interaction Quality graders, with a mocked judge.

The shared steps (selection, prompt layout, judgment form) are tested in ``test_judge.py`` and
``tests/unit/core``. These tests check what each grader owns: its taxonomy, its settings and
the text they put in the prompt, the evidence its judge reads, and its evidence checks.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

from metis.core.trace_processing import render_session, turns
from metis.core.traces import GradingInput, Observation, Trace
from metis.library.grader import JudgeArgs, LLMSettings
from metis.library.graders import (
    ActionStatusTransparencyGrader,
    ClarificationAppropriatenessGrader,
    CommunicationClarityGrader,
    CrossTurnCoherenceGrader,
    ExplanationUsefulnessGrader,
    OutputNaturalnessGrader,
    RelevanceGrader,
    ToneAppropriatenessGrader,
    UserCorrectionSupportGrader,
)
from metis.library.scope import SCOPE_DEFINITIONS, SubsessionArgs
from metis.library.taxonomy import (
    Aggregation,
    GraderType,
    JudgmentForm,
    Measure,
    ReferenceType,
    Scope,
)
from tests.fixtures.criterion_judge import judge_client
from tests.fixtures.traces import load_session

if TYPE_CHECKING:
    from metis.core.grading import GraderResult

MEASURES = {
    RelevanceGrader: Measure.RELEVANCE,
    CommunicationClarityGrader: Measure.COMMUNICATION_CLARITY,
    CrossTurnCoherenceGrader: Measure.CROSS_TURN_COHERENCE,
    ClarificationAppropriatenessGrader: Measure.CLARIFICATION_APPROPRIATENESS,
    UserCorrectionSupportGrader: Measure.USER_CORRECTION_AND_OVERRIDE_SUPPORT,
    ActionStatusTransparencyGrader: Measure.ACTION_STATUS_TRANSPARENCY,
    ExplanationUsefulnessGrader: Measure.EXPLANATION_USEFULNESS,
    ToneAppropriatenessGrader: Measure.TONE_APPROPRIATENESS,
    OutputNaturalnessGrader: Measure.OUTPUT_NATURALNESS,
}
GRADERS = list(MEASURES)
WITH_SUBSESSION = [
    RelevanceGrader,
    CommunicationClarityGrader,
    ExplanationUsefulnessGrader,
    ToneAppropriatenessGrader,
    OutputNaturalnessGrader,
]
SESSION_ONLY = [g for g in GRADERS if g not in WITH_SUBSESSION]
VERDICT = {"status": "scored", "score": 1, "reason": "It fits."}
SETTINGS = {
    RelevanceGrader: {"purpose": "Answers billing questions."},
    CommunicationClarityGrader: {"audience": "Members of the public."},
    CrossTurnCoherenceGrader: {},
    ClarificationAppropriatenessGrader: {
        "confirm_before": "Payments.",
        "question_limit": "One question before the first answer.",
    },
    UserCorrectionSupportGrader: {"fixed_rules": "Always verify identity."},
    ActionStatusTransparencyGrader: {
        "disclosure_level": "Only the outcome.",
        "ui_status": "A progress card shows each tool call.",
    },
    ExplanationUsefulnessGrader: {},
    ToneAppropriatenessGrader: {"expected_tone": "Formal and professional."},
    OutputNaturalnessGrader: {"conventions": "Singapore English."},
}


def turn(index: int, user: str, reply: str, **tool: Any) -> Trace:
    trace_id = f"trace-{index}"
    observations = [
        Observation(id=f"root-{index}", trace_id=trace_id, input=user, output=reply)
    ]
    if tool:
        observations.append(
            Observation(
                id=f"tool-{index}",
                trace_id=trace_id,
                parent_observation_id=f"root-{index}",
                type="TOOL",
                **tool,
            )
        )
    return Trace(id=trace_id, session_id="session-1", observations=tuple(observations))


def two_turn_session() -> GradingInput:
    return GradingInput(
        traces=(
            turn(
                1,
                "Find the Q3 sales figures.",
                "I found the figures.",
                name="search",
                input={"query": "Q3 sales"},
                output="ERROR: index unavailable",
                level="ERROR",
                status_message="index unavailable",
            ),
            turn(2, "No, use the median.", "Here is the median by region."),
        )
    )


def grade(
    grader_cls, gi: GradingInput, reply: object = VERDICT, **settings: Any
) -> tuple[list[GraderResult], list[dict[str, Any]]]:
    requests: list[dict[str, Any]] = []
    client = judge_client(json.dumps(reply), requests)
    grader = grader_cls(grader_cls.args_model(model="test-judge", **settings))

    async def run():
        async with client:
            return await grader.grade(gi, LLMSettings(client))

    return asyncio.run(run()).results, requests


def system_and_evidence(request: dict[str, Any]) -> tuple[str, str]:
    system, user = request["input"]
    [evidence] = user["content"]
    return system["content"], evidence["text"]


def criteria_sent(grader_cls, **settings: Any) -> str:
    _, [request] = grade(grader_cls, two_turn_session(), **settings)
    system, evidence = system_and_evidence(request)
    for value in settings.values():
        assert value not in evidence
    return system.split("<criteria>\n")[1].split("\n</criteria>")[0]


@pytest.mark.parametrize("grader_cls", GRADERS)
def test_declares_its_measure_and_scopes(grader_cls) -> None:
    assert grader_cls.args_model.__name__ == grader_cls.__name__.replace(
        "Grader", "Args"
    )
    assert grader_cls.taxonomy.model_dump() == {
        "measure": MEASURES[grader_cls],
        "scopes": (Scope.SESSION, Scope.SUBSESSION)
        if grader_cls in WITH_SUBSESSION
        else (Scope.SESSION,),
        "grader_types": (GraderType.LLM,),
        "reference_types": (ReferenceType.RUBRIC_BASED,),
        "judgment_forms": (JudgmentForm.BINARY,),
        "aggregations": (Aggregation.NONE_SINGLE_SCORE,),
    }


def test_each_grader_sends_its_own_criteria() -> None:
    assert len({criteria_sent(grader_cls) for grader_cls in GRADERS}) == len(GRADERS)


@pytest.mark.parametrize("grader_cls", GRADERS)
def test_the_default_is_one_session_result_on_every_turn(grader_cls) -> None:
    [result], [request] = grade(grader_cls, two_turn_session())

    assert (result.status, result.score, result.scope) == ("scored", 1.0, "session")
    system, evidence = system_and_evidence(request)
    assert SCOPE_DEFINITIONS[Scope.SESSION].instructions in system
    assert "## Turn 1" in evidence and "## Turn 2" in evidence


@pytest.mark.parametrize("grader_cls", WITH_SUBSESSION)
def test_subsession_scope_judges_each_turn_with_the_turns_before_it(
    grader_cls,
) -> None:
    results, requests = grade(grader_cls, two_turn_session(), scope=Scope.SUBSESSION)

    assert [r.scope for r in results] == ["turns:1-1", "turns:1-2"]
    first, second = (system_and_evidence(r) for r in requests)
    assert SCOPE_DEFINITIONS[Scope.SUBSESSION].instructions in first[0]
    assert "## Turn 2" not in first[1]
    assert "## Turn 1" in second[1] and "## Turn 2" in second[1]


@pytest.mark.parametrize("grader_cls", WITH_SUBSESSION)
def test_subsession_window_and_last_turn_narrow_what_is_judged(grader_cls) -> None:
    [result], [request] = grade(
        grader_cls,
        two_turn_session(),
        scope=Scope.SUBSESSION,
        turn="last",
        window=1,
    )

    assert result.scope == "turns:2-2"
    _, evidence = system_and_evidence(request)
    assert "## Turn 1" not in evidence and "## Turn 2" in evidence


@pytest.mark.parametrize("grader_cls", SESSION_ONLY)
def test_a_session_only_grader_rejects_another_scope(grader_cls) -> None:
    assert not issubclass(grader_cls.args_model, SubsessionArgs)
    with pytest.raises(ValueError, match="does not support scope"):
        grader_cls(grader_cls.args_model(model="test-judge", scope=Scope.SUBSESSION))


@pytest.mark.parametrize("grader_cls", GRADERS)
def test_each_grader_has_its_own_optional_settings(grader_cls) -> None:
    shared = {*JudgeArgs.model_fields}
    if grader_cls in WITH_SUBSESSION:
        shared |= set(SubsessionArgs.model_fields)
    fields = set(grader_cls.args_model.model_fields) - shared
    assert fields == set(SETTINGS[grader_cls])
    for name in fields:
        assert grader_cls.args_model.model_fields[name].default is None
        with pytest.raises(ValidationError):
            grader_cls.args_model(model="test-judge", **{name: " "})


@pytest.mark.parametrize("grader_cls", [g for g in GRADERS if SETTINGS[g]])
def test_each_setting_adds_to_its_graders_criteria(grader_cls) -> None:
    default = criteria_sent(grader_cls)
    rules, _, boundaries = default.partition("\n\n<assessment_boundaries>")
    for name, value in SETTINGS[grader_cls].items():
        with_setting = criteria_sent(grader_cls, **{name: value})
        assert with_setting.startswith(rules)
        assert with_setting.endswith(boundaries)
        assert value in with_setting


@pytest.mark.parametrize(
    ("grader_cls", "shows_tools", "shows_user"),
    [
        (RelevanceGrader, True, True),
        (ClarificationAppropriatenessGrader, True, True),
        (UserCorrectionSupportGrader, True, True),
        (ExplanationUsefulnessGrader, True, True),
        (CommunicationClarityGrader, False, True),
        (CrossTurnCoherenceGrader, False, True),
        (ToneAppropriatenessGrader, False, True),
        (OutputNaturalnessGrader, False, False),
    ],
)
def test_each_grader_shows_the_evidence_its_measure_needs(
    grader_cls, shows_tools, shows_user
) -> None:
    _, [request] = grade(grader_cls, two_turn_session())
    _, evidence = system_and_evidence(request)

    assert "I found the figures." in evidence
    assert ("search" in evidence) is shows_tools
    assert ("No, use the median." in evidence) is shows_user
    assert "Tool result" not in evidence


def test_transparency_shows_each_call_with_its_status_and_a_cut_result() -> None:
    long_result = "x" * 700
    gi = GradingInput(
        traces=(
            *two_turn_session().traces,
            turn(3, "Export it.", "Exported.", name="export", output=long_result),
        )
    )
    _, [request] = grade(ActionStatusTransparencyGrader, gi)
    _, evidence = system_and_evidence(request)

    assert evidence == render_session(
        turns(gi.traces), tool_results=True, max_chars=600
    )
    assert "Tool result [error: index unavailable]" in evidence
    assert "x" * 600 + " …[cut off]" in evidence


@pytest.mark.parametrize(
    "grader_cls", [ExplanationUsefulnessGrader, UserCorrectionSupportGrader]
)
def test_a_session_without_the_event_is_errored(grader_cls) -> None:
    reply = {"status": "not_applicable", "score": None, "reason": "None found."}
    [result], _ = grade(grader_cls, two_turn_session(), reply)

    assert (result.status, result.reason) == ("errored", "None found.")
    assert "return status not_applicable" in criteria_sent(grader_cls)


@pytest.mark.parametrize(
    ("grader_cls", "gi", "reason"),
    [
        (RelevanceGrader, GradingInput(traces=()), "no turns"),
        (
            CrossTurnCoherenceGrader,
            GradingInput(traces=(turn(1, "Hi", "Hello"),)),
            "at least two turns",
        ),
        (
            UserCorrectionSupportGrader,
            GradingInput(traces=(turn(1, "Hi", "Hello"),)),
            "later turn",
        ),
        (
            ActionStatusTransparencyGrader,
            GradingInput(traces=(turn(1, "Hi", "Hello"), turn(2, "Bye", "Bye"))),
            "no tool calls",
        ),
    ],
)
def test_missing_evidence_is_errored_without_a_judge_call(
    grader_cls, gi, reason
) -> None:
    [result], requests = grade(grader_cls, gi)

    assert result.status == "errored"
    assert reason in result.reason
    assert requests == []


@pytest.mark.parametrize("grader_cls", GRADERS)
def test_judges_the_helpdesk_session(grader_cls) -> None:
    [result], [request] = grade(grader_cls, load_session())

    assert result.status == "scored"
    _, evidence = system_and_evidence(request)
    assert evidence.count("## Turn ") == 5
