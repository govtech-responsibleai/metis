"""The Reliability and Robustness graders, with a mocked judge.

The shared steps (selection, prompt layout, judgment form, aggregation) are tested in
``test_judge.py`` and ``tests/unit/core``. These tests check what each grader owns: its
taxonomy, its settings and the text they put in the prompt, the evidence its judge reads, and
its evidence checks.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

from metis.core.trace_processing import render_session, turns
from metis.core.traces import GradingInput, Observation, Trace
from metis.library.grader import LLMSettings
from metis.library.graders import (
    LongTaskPerformanceStabilityGrader,
    RobustnessToContextDegradationGrader,
    RobustnessToToolFailuresGrader,
)
from metis.library.graders.reliability_and_robustness._long_task_performance_stability import (
    LongTaskPerformanceStabilityArgs,
)
from metis.library.scope import SCOPE_DEFINITIONS
from metis.library.taxonomy import (
    Aggregation,
    GraderType,
    JudgmentForm,
    Measure,
    ReferenceType,
    Scope,
)
from tests.fixtures.criterion_judge import judge_client

if TYPE_CHECKING:
    from metis.core.grading import GraderResult

PASS = {"status": "scored", "score": 1, "reason": "It holds."}
NOT_APPLICABLE = {
    "status": "not_applicable",
    "score": None,
    "reason": "No tool response failed.",
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


def failed_tool_session() -> GradingInput:
    return GradingInput(
        traces=(
            turn(1, "Hello.", "Hello. How can I help?"),
            turn(
                2,
                "What is the weather in Paris?",
                "The weather service is down. Please try again later.",
                name="weather",
                input={"city": "Paris"},
                output="ERROR: upstream timeout",
                level="ERROR",
                status_message="upstream timeout",
            ),
        )
    )


def session_of(count: int) -> GradingInput:
    return GradingInput(
        traces=tuple(
            turn(n, f"Step {n}. Answer in French.", f"Etape {n}.")
            for n in range(1, count + 1)
        )
    )


def grade(
    grader_cls, gi: GradingInput, reply: object = PASS, **settings: Any
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


def criteria_of(request: dict[str, Any]) -> str:
    system, _ = system_and_evidence(request)
    return system.split("<criteria>\n")[1].split("\n</criteria>")[0]


@pytest.mark.parametrize(
    ("grader_cls", "measure", "scopes", "grader_type", "aggregation"),
    [
        (
            RobustnessToToolFailuresGrader,
            Measure.ROBUSTNESS_TO_TOOL_FAILURES,
            (Scope.TRACE, Scope.SESSION),
            GraderType.LLM,
            Aggregation.NONE_SINGLE_SCORE,
        ),
        (
            LongTaskPerformanceStabilityGrader,
            Measure.LONG_TASK_PERFORMANCE_STABILITY,
            (Scope.SESSION,),
            GraderType.LLM,
            Aggregation.NONE_SINGLE_SCORE,
        ),
        (
            RobustnessToContextDegradationGrader,
            Measure.ROBUSTNESS_TO_CONTEXT_DEGRADATION,
            (Scope.SUBSESSION, Scope.SESSION),
            GraderType.LLM,
            Aggregation.NONE_SINGLE_SCORE,
        ),
    ],
)
def test_declares_its_taxonomy(
    grader_cls, measure, scopes, grader_type, aggregation
) -> None:
    assert grader_cls.args_model.__name__ == grader_cls.__name__.replace(
        "Grader", "Args"
    )
    assert grader_cls.taxonomy.model_dump() == {
        "measure": measure,
        "scopes": scopes,
        "grader_types": (grader_type,),
        "reference_types": (ReferenceType.RUBRIC_BASED,),
        "judgment_forms": (JudgmentForm.BINARY,),
        "aggregations": (aggregation,),
    }


@pytest.mark.parametrize(
    ("grader_cls", "gi", "settings"),
    [
        (
            RobustnessToToolFailuresGrader,
            failed_tool_session(),
            {
                "task_description": "Report the weather.",
                "acceptable_fallbacks": ("Tell the user the service is down.",),
            },
        ),
        (
            LongTaskPerformanceStabilityGrader,
            session_of(4),
            {"task_description": "Translate each step."},
        ),
        (
            RobustnessToContextDegradationGrader,
            failed_tool_session(),
            {
                "task_description": "Report the weather.",
                "degradation": ("Turn 1 is irrelevant small talk.",),
            },
        ),
    ],
)
def test_each_setting_appears_in_the_criteria(grader_cls, gi, settings) -> None:
    _, requests = grade(grader_cls, gi, **settings)

    criteria = criteria_of(requests[-1])
    for value in settings.values():
        for text in value if isinstance(value, tuple) else (value,):
            assert text in criteria


@pytest.mark.parametrize(
    ("grader_cls", "field"),
    [
        (RobustnessToToolFailuresGrader, "acceptable_fallbacks"),
        (RobustnessToContextDegradationGrader, "degradation"),
    ],
)
def test_rejects_a_blank_list_entry(grader_cls, field) -> None:
    with pytest.raises(ValidationError, match="Blank entries at positions"):
        grader_cls.args_model(model="test-judge", **{field: ("ok", " ")})


def test_tool_failures_judges_only_the_turns_with_tool_calls() -> None:
    [result], [request] = grade(RobustnessToToolFailuresGrader, failed_tool_session())

    assert (result.status, result.score, result.scope) == ("scored", 1.0, "turn:2")
    system, evidence = system_and_evidence(request)
    assert SCOPE_DEFINITIONS[Scope.TRACE].instructions in system
    assert "## Turn 1" not in evidence
    assert "Tool weather: " in evidence
    assert "Tool result [error: upstream timeout]: ERROR: upstream timeout" in evidence


def test_tool_failures_session_scope_judges_the_whole_session() -> None:
    [result], [request] = grade(
        RobustnessToToolFailuresGrader, failed_tool_session(), scope=Scope.SESSION
    )

    assert (result.status, result.scope) == ("scored", "session")
    _, evidence = system_and_evidence(request)
    assert "## Turn 1" in evidence and "## Turn 2" in evidence


@pytest.mark.parametrize("scope", [Scope.TRACE, Scope.SESSION])
def test_tool_failures_without_tool_calls_is_errored_without_a_judge_call(
    scope,
) -> None:
    [result], requests = grade(
        RobustnessToToolFailuresGrader, session_of(2), scope=scope
    )

    assert result.status == "errored"
    assert "no tool calls" in result.reason
    assert requests == []


def test_tool_failures_last_turn_without_tool_calls_is_errored_without_a_judge_call() -> (
    None
):
    gi = GradingInput(
        traces=(*failed_tool_session().traces, turn(3, "Thanks.", "Bye."))
    )
    [result], requests = grade(RobustnessToToolFailuresGrader, gi, turn="last")

    assert result.status == "errored"
    assert requests == []


@pytest.mark.parametrize(
    "grader_cls", [RobustnessToToolFailuresGrader, RobustnessToContextDegradationGrader]
)
def test_not_applicable_is_errored_with_the_judges_reason(grader_cls) -> None:
    results, _ = grade(grader_cls, failed_tool_session(), reply=NOT_APPLICABLE)

    assert {(r.status, r.reason) for r in results} == {
        ("errored", "No tool response failed.")
    }


def test_long_task_judges_the_whole_session_in_one_call() -> None:
    [result], [request] = grade(LongTaskPerformanceStabilityGrader, session_of(4))

    assert (result.status, result.score, result.scope) == ("scored", 1.0, "session")
    system, evidence = system_and_evidence(request)
    assert SCOPE_DEFINITIONS[Scope.SESSION].instructions in system
    assert all(f"## Turn {n}" in evidence for n in (1, 2, 3, 4))


def test_long_task_below_min_turns_is_errored_without_a_judge_call() -> None:
    [result], requests = grade(
        LongTaskPerformanceStabilityGrader, session_of(4), min_turns=5
    )

    assert result.status == "errored"
    assert "at least 5" in result.reason
    assert requests == []


def test_long_task_min_turns_is_at_least_two() -> None:
    with pytest.raises(ValidationError):
        LongTaskPerformanceStabilityArgs(model="test-judge", min_turns=1)


def test_context_degradation_judges_each_turn_with_the_turns_before_it() -> None:
    results, requests = grade(
        RobustnessToContextDegradationGrader, failed_tool_session()
    )

    assert [r.scope for r in results] == ["turns:1-1", "turns:1-2"]
    first, second = (system_and_evidence(r) for r in requests)
    assert SCOPE_DEFINITIONS[Scope.SUBSESSION].instructions in first[0]
    assert "## Turn 2" not in first[1]
    assert "## Turn 1" in second[1] and "## Turn 2" in second[1]
    assert "Tool result [error: upstream timeout]" in second[1]


def test_context_degradation_session_scope_judges_the_whole_session() -> None:
    [result], [request] = grade(
        RobustnessToContextDegradationGrader,
        failed_tool_session(),
        scope=Scope.SESSION,
    )

    assert (result.status, result.scope) == ("scored", "session")
    system, evidence = system_and_evidence(request)
    assert SCOPE_DEFINITIONS[Scope.SESSION].instructions in system
    assert "## Turn 1" in evidence and "## Turn 2" in evidence


GRADERS_WITH_INPUT = [
    (RobustnessToToolFailuresGrader, failed_tool_session()),
    (LongTaskPerformanceStabilityGrader, session_of(4)),
    (RobustnessToContextDegradationGrader, failed_tool_session()),
]
LAST_EVIDENCE = {
    RobustnessToToolFailuresGrader: slice(1, 2),
    LongTaskPerformanceStabilityGrader: slice(0, 4),
    RobustnessToContextDegradationGrader: slice(0, 2),
}


def test_each_grader_sends_its_own_criteria() -> None:
    sent = {criteria_of(grade(g, gi)[1][-1]) for g, gi in GRADERS_WITH_INPUT}
    assert len(sent) == len(GRADERS_WITH_INPUT)


@pytest.mark.parametrize(("grader_cls", "gi"), GRADERS_WITH_INPUT)
def test_the_prompt_has_the_criteria_scope_rules_and_the_rendered_evidence(
    grader_cls, gi
) -> None:
    grader = grader_cls(grader_cls.args_model(model="test-judge"))
    _, requests = grade(grader_cls, gi)
    system, evidence = system_and_evidence(requests[-1])

    assert system.startswith(f"<criteria>\n{grader.criteria()}\n</criteria>")
    assert (
        f"<scope>\n{SCOPE_DEFINITIONS[grader.scope].instructions}\n</scope>" in system
    )
    assert "No task description is given." in system
    assert "<output_instructions>\nReturn status scored" in system
    expected = turns(gi.traces)[LAST_EVIDENCE[grader_cls]]
    assert evidence == render_session(expected, tool_results=True)
    assert "<acceptable_fallbacks>" not in system
    assert "<degradation>" not in system


@pytest.mark.parametrize(
    ("grader_cls", "gi", "settings"),
    [
        (
            RobustnessToToolFailuresGrader,
            failed_tool_session(),
            {"acceptable_fallbacks": ("Tell the user the service is down.",)},
        ),
        (
            RobustnessToContextDegradationGrader,
            failed_tool_session(),
            {"degradation": ("Turn 1 is irrelevant small talk.",)},
        ),
    ],
)
def test_a_list_setting_adds_a_numbered_block_and_keeps_the_rest(
    grader_cls, gi, settings
) -> None:
    default = criteria_of(grade(grader_cls, gi)[1][-1])
    with_setting = criteria_of(grade(grader_cls, gi, **settings)[1][-1])
    [(name, (item,))] = settings.items()

    block = f"\n\n<{name}>\n1. {item}\n</{name}>"
    assert block in with_setting
    assert with_setting.replace(block, "") == default


def test_context_degradation_window_and_last_turn_narrow_what_is_judged() -> None:
    gi = GradingInput(
        traces=(*failed_tool_session().traces, turn(3, "And Rome?", "Sunny."))
    )
    [result], [request] = grade(
        RobustnessToContextDegradationGrader, gi, turn="last", window=2
    )

    assert result.scope == "turns:2-3"
    _, evidence = system_and_evidence(request)
    assert "## Turn 1" not in evidence
    assert "## Turn 2" in evidence and "## Turn 3" in evidence
