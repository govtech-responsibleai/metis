"""The Execution and Decision Quality and Task and Output Quality graders, with a mocked judge.

The shared steps (evidence items, prompt layout, judgment form, aggregation) are tested in
``test_judge.py`` and ``tests/unit/core``. These tests check what each grader owns: its required
settings, the text its settings put in the prompt, its evidence checks, and the scope of its
results.
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

import metis.library.graders as catalog
from metis.core.artifacts import Artifact
from metis.core.traces import GradingInput, Observation, Trace
from metis.library.grader import LLMSettings
from metis.library.taxonomy import Scope
from tests.fixtures.criterion_judge import judge_client

if TYPE_CHECKING:
    from pathlib import Path

    from metis.core.grading import GraderResult

VERDICT = {"status": "scored", "score": 1, "reason": "Met."}

REQUIRED: dict[str, dict[str, Any]] = {
    "ActionChoiceAppropriatenessGrader": {},
    "AdaptationToChangedConditionsGrader": {},
    "AppropriateHandlingOfCapabilityLimitsGrader": {},
    "AttributionAccuracyGrader": {},
    "AvoidingUnproductiveRepetitionGrader": {},
    "ClaimSupportByEvidenceGrader": {},
    "ContentFidelityGrader": {},
    "CoordinationQualityGrader": {},
    "ErrorDetectionGrader": {},
    "ErrorRecoveryGrader": {},
    "EvidenceSourceSuitabilityGrader": {
        "suitability_requirements": ["Published after 2024"],
        "sources": ["The 2025 product manual"],
    },
    "FactualAccuracyGrader": {"ground_truth": ["Paris is the capital of France."]},
    "FormatSchemaComplianceGrader": {"format_requirements": ["Use a bulleted list."]},
    "OutcomeVerificationGrader": {},
    "OutputCorrectnessGrader": {"correctness_conditions": ["The total is 42."]},
    "PlanningQualityGrader": {},
    "ReasoningValidityGrader": {},
    "RequiredComponentCompletenessGrader": {"required_components": ["A summary"]},
    "SpeechRecognitionAccuracyGrader": {
        "reference_transcript": "Book a table for two."
    },
    "StateTrackingGrader": {},
    "StoppingAppropriatenessGrader": {},
    "TaskConstraintAdherenceGrader": {"constraints": ["Spend under 100 dollars."]},
    "TaskSuccessGrader": {},
    "ToolArgumentCorrectnessGrader": {},
    "ToolChoiceAppropriatenessGrader": {},
    "UseOfPriorInformationGrader": {},
}
ARTIFACT_GOAL = {"TaskSuccessGrader": {"success_conditions": ["Lists two items."]}}
MULTI_RULE = {
    "EvidenceSourceSuitabilityGrader": "sources",
    "RequiredComponentCompletenessGrader": "required_components",
    "TaskConstraintAdherenceGrader": "constraints",
}


def _session(*, agent: str | None = "planner", **extra: Any) -> GradingInput:
    """Two turns. The second calls a search tool, inside an agent when ``agent`` is set, so the
    session offered the agent ``search``."""
    first = Trace(
        id="t1",
        session_id="s",
        observations=(Observation(id="r1", trace_id="t1", input="hi", output="hello"),),
    )
    tool_parent = "a2" if agent else "r2"
    observations = [
        Observation(id="r2", trace_id="t2", input="find x", output="found x"),
        Observation(
            id="tool",
            trace_id="t2",
            type="TOOL",
            name="search",
            input={"q": "x"},
            output={"hits": 1},
            parent_observation_id=tool_parent,
        ),
    ]
    if agent:
        observations.insert(
            1,
            Observation(
                id="a2",
                trace_id="t2",
                type="AGENT",
                name=agent,
                parent_observation_id="r2",
            ),
        )
    second = Trace(id="t2", session_id="s", observations=tuple(observations))
    return GradingInput(traces=(first, second), **extra)


TOOL_GRADERS = {
    "ActionChoiceAppropriatenessGrader",
    "AppropriateHandlingOfCapabilityLimitsGrader",
    "ToolArgumentCorrectnessGrader",
    "ToolChoiceAppropriatenessGrader",
}


def _grader(name: str, **args: Any):
    cls = getattr(catalog, name)
    return cls(
        cls.args_model.model_validate({"model": "judge", **REQUIRED[name], **args})
    )


def _grade(
    grader, gi: GradingInput, reply: object
) -> tuple[list[GraderResult], list[dict]]:
    requests: list[dict] = []
    content = (
        [json.dumps(r) for r in reply] if isinstance(reply, list) else json.dumps(reply)
    )
    client = judge_client(content, requests)

    async def run():
        async with client:
            return await grader.grade(gi, LLMSettings(client))

    return asyncio.run(run()).results, requests


@pytest.mark.parametrize("name", sorted(REQUIRED))
def test_the_default_judges_one_item_and_names_it(name: str) -> None:
    grader = _grader(name)
    [result], [request] = _grade(grader, _session(), VERDICT)
    assert result.status == "scored", result.reason
    assert result.score == 1.0
    expected_scope = "turn:2" if grader.taxonomy.scopes[0] == Scope.TRACE else "session"
    assert result.scope == expected_scope
    system = request["input"][0]["content"]
    assert "untrusted evidence" in system
    for value in REQUIRED[name].values():
        for text in value if isinstance(value, list) else [value]:
            assert text in system, f"{name} leaves {text!r} out of the prompt"


@pytest.mark.parametrize("name", sorted(REQUIRED))
def test_an_empty_session_is_errored_without_a_judge_call(name: str) -> None:
    [result], requests = _grade(
        _grader(name, **({"available_tools": ["t"]} if name in TOOL_GRADERS else {})),
        GradingInput(traces=()),
        VERDICT,
    )
    assert result.status == "errored"
    assert requests == []


@pytest.mark.parametrize(
    "name", sorted(n for n, required in REQUIRED.items() if required)
)
def test_the_measure_reference_is_required(name: str) -> None:
    cls = getattr(catalog, name)
    with pytest.raises(ValidationError):
        cls.args_model.model_validate({"model": "judge"})


@pytest.mark.parametrize(
    "name",
    sorted(
        n
        for n in REQUIRED
        if "task_description" in getattr(catalog, n).args_model.model_fields
    ),
)
def test_a_task_description_is_optional_and_reaches_the_prompt(name: str) -> None:
    _, [unset] = _grade(_grader(name), _session(), VERDICT)
    assert "Infer what the user asked for" in unset["input"][0]["content"]
    _, [set_] = _grade(
        _grader(name, task_description="Book a flight to Osaka."),
        _session(),
        VERDICT,
    )
    assert "Book a flight to Osaka." in set_["input"][0]["content"]


def _no_tool_calls() -> GradingInput:
    return GradingInput(traces=_session().traces[:1])


def test_tool_arguments_need_recorded_tool_calls() -> None:
    [result], requests = _grade(
        _grader("ToolArgumentCorrectnessGrader", available_tools=["search: Searches"]),
        _no_tool_calls(),
        VERDICT,
    )
    assert result.status == "errored"
    assert "no recorded tool calls" in result.reason
    assert requests == []


def test_tool_choice_judges_a_session_with_no_tool_calls() -> None:
    [result], [request] = _grade(
        _grader(
            "ToolChoiceAppropriatenessGrader", available_tools=["search: Searches"]
        ),
        _no_tool_calls(),
        VERDICT,
    )
    assert (result.status, result.score) == ("scored", 1.0)
    assert "search: Searches" in request["input"][0]["content"]


def test_tool_choice_without_a_tool_list_is_errored_without_a_judge_call() -> None:
    [result], requests = _grade(
        _grader("ToolChoiceAppropriatenessGrader"), _no_tool_calls(), VERDICT
    )
    assert result.status == "errored"
    assert "set available_tools" in result.reason
    assert requests == []


@pytest.mark.parametrize(
    "name",
    [
        "ActionChoiceAppropriatenessGrader",
        "AppropriateHandlingOfCapabilityLimitsGrader",
    ],
)
def test_without_a_tool_list_the_judge_does_not_guess_the_tools(name: str) -> None:
    _, [without] = _grade(_grader(name), _no_tool_calls(), VERDICT)
    assert "No tool list is given" in without["input"][0]["content"]


@pytest.mark.parametrize("name", sorted(TOOL_GRADERS))
def test_the_tool_list_setting_reaches_the_prompt(name: str) -> None:
    grader = _grader(name, available_tools=["search(query): Searches the index"])
    _, [request] = _grade(grader, _session(), VERDICT)
    system = request["input"][0]["content"]
    assert "<available_tools>\n1. search(query): Searches the index\n" in system
    assert "No tool list is given" not in system


@pytest.mark.parametrize("name", sorted(TOOL_GRADERS))
def test_without_the_setting_the_tool_list_is_the_tools_the_session_offered(
    name: str,
) -> None:
    _, [request] = _grade(_grader(name), _session(), VERDICT)
    assert "<available_tools>\n1. search (planner)\n" in request["input"][0]["content"]


def test_coordination_needs_a_recorded_agent() -> None:
    [result], requests = _grade(
        _grader("CoordinationQualityGrader"), _session(agent=None), VERDICT
    )
    assert result.status == "errored"
    assert "delegation" in result.reason
    assert requests == []


def test_session_graders_see_tool_results() -> None:
    _, [request] = _grade(_grader("ErrorRecoveryGrader"), _session(), VERDICT)
    [evidence] = request["input"][1]["content"]
    assert 'Tool result [ok]: {"hits": 1}' in evidence["text"]


@pytest.mark.parametrize(
    "name",
    sorted(
        n for n in REQUIRED if Scope.ARTIFACT in getattr(catalog, n).taxonomy.scopes
    ),
)
def test_artifact_scope_judges_the_latest_revision(name: str, tmp_path: Path) -> None:
    draft, final = tmp_path / "draft", tmp_path / "final"
    for folder, text in ((draft, "- one"), (final, "- one\n- two")):
        folder.mkdir()
        (folder / "report.txt").write_text(text)
    files = tuple(
        Artifact(
            name="report.txt",
            source="target",
            state="received",
            path=str(folder / "report.txt"),
            at_simulated_turn=turn,
        )
        for folder, turn in ((draft, 1), (final, 2))
    )
    grader = _grader(
        name, scope="artifact", artifact="report.txt", **ARTIFACT_GOAL.get(name, {})
    )
    results, requests = _grade(grader, _session(artifacts=files), VERDICT)
    assert [r.scope for r in results] == ["artifact:report.txt"]
    [attached] = [
        part
        for part in requests[0]["input"][1]["content"]
        if part["type"] == "input_file"
    ]
    assert attached["filename"] == "report.txt"
    assert attached["file_data"].endswith(base64.b64encode(b"- one\n- two").decode())


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("TaskSuccessGrader", {"success_conditions": ["Lists two items."]}),
        ("TaskSuccessGrader", {"task_description": "Summarise the report."}),
        ("TaskConstraintAdherenceGrader", {}),
    ],
)
def test_artifact_scope_prompt_judges_only_the_file(
    name: str, args: dict[str, Any], tmp_path: Path
) -> None:
    path = tmp_path / "report.txt"
    path.write_text("- one\n- two")
    file = Artifact(
        name="report.txt", source="target", state="received", path=str(path)
    )
    grader = _grader(name, scope="artifact", artifact="report.txt", **args)
    _, [request] = _grade(grader, _session(artifacts=(file,)), VERDICT)
    criteria = request["input"][0]["content"].split("</criteria>")[0]
    assert "Judge only the attached file." in criteria
    assert "user's messages" not in criteria
    assert "tool results" not in criteria


SOURCE_GRADERS = sorted(
    [
        "AttributionAccuracyGrader",
        "ClaimSupportByEvidenceGrader",
        "ContentFidelityGrader",
    ]
)


@pytest.mark.parametrize("name", SOURCE_GRADERS)
def test_the_prompt_names_the_session_as_the_source(name: str) -> None:
    _, [request] = _grade(_grader(name), _session(), VERDICT)
    system = request["input"][0]["content"]
    assert (
        "the content that the user gave the agent or that the agent retrieved" in system
    )
    assert "the criterion does not apply" in system


@pytest.mark.parametrize("name", SOURCE_GRADERS)
def test_the_earlier_turns_are_sources_for_the_judged_reply(name: str) -> None:
    _, [request] = _grade(_grader(name), _session(), VERDICT)
    context, judged = request["input"][1]["content"]
    assert context["text"].startswith("## Turn 1\nUser: hi")
    assert judged["text"].startswith("## Turn 2\nUser: find x")


def _fixture(tmp_path: Path) -> Artifact:
    path = tmp_path / "minutes.txt"
    path.write_text("The meeting moved to Friday.")
    return Artifact(
        name="minutes.txt", source="fixture", state="received", path=str(path)
    )


@pytest.mark.parametrize("name", SOURCE_GRADERS)
def test_the_files_the_user_gave_reach_the_request(name: str, tmp_path: Path) -> None:
    _, [request] = _grade(
        _grader(name), _session(artifacts=(_fixture(tmp_path),)), VERDICT
    )
    files = [p for p in request["input"][1]["content"] if p["type"] == "input_file"]
    assert [f["filename"] for f in files] == ["minutes.txt"]


@pytest.mark.parametrize("name", SOURCE_GRADERS)
def test_on_a_file_the_session_and_the_given_files_are_the_sources(
    name: str, tmp_path: Path
) -> None:
    path = tmp_path / "report.txt"
    path.write_text("Friday.")
    output = Artifact(
        name="report.txt", source="target", state="received", path=str(path)
    )
    grader = _grader(name, scope="artifact", artifact="report.txt")
    _, [request] = _grade(
        grader, _session(artifacts=(output, _fixture(tmp_path))), VERDICT
    )
    parts = request["input"][1]["content"]
    assert parts[0]["text"].startswith("## Turn 1\nUser: hi")
    assert [p.get("filename") for p in parts[1:]] == ["report.txt", "minutes.txt"]
    assert (
        "The first attached file is the assessed output."
        in request["input"][0]["content"]
    )


def test_task_success_on_a_file_needs_a_goal() -> None:
    with pytest.raises(ValidationError, match="task_description or success_conditions"):
        _grader("TaskSuccessGrader", scope="artifact", artifact="report.txt")


@pytest.mark.parametrize("name", sorted(MULTI_RULE))
def test_multi_rule_graders_judge_each_rule_and_pass_only_if_all_pass(
    name: str,
) -> None:
    rules = ["First rule.", "Second rule."]
    grader = _grader(name, **{MULTI_RULE[name]: rules})
    reply = [
        {"status": "scored", "score": 1, "reason": "Yes."},
        {"status": "scored", "score": 0, "reason": "No."},
    ]
    [result], requests = _grade(grader, _session(), reply)
    assert (result.status, result.score) == ("scored", 0.0)
    assert len(requests) == 2
    assert "First rule." in requests[0]["input"][0]["content"]
    assert "Second rule." in requests[1]["input"][0]["content"]
    assert "Second rule." not in requests[0]["input"][0]["content"]


@pytest.mark.parametrize(
    "name",
    sorted(
        n for n in REQUIRED if getattr(catalog, n).taxonomy.scopes[0] == Scope.TRACE
    ),
)
def test_trace_graders_can_judge_every_turn(name: str) -> None:
    results, requests = _grade(_grader(name, turn="each"), _session(), VERDICT)
    assert [r.scope for r in results] == ["turn:1", "turn:2"]
    assert len(requests) == 2


class TestFormatSchemaCompliance:
    SCHEMA = json.dumps(
        {"type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}}
    )

    def _run(self, reply: str, **args: Any):
        cls = catalog.FormatSchemaComplianceGrader
        grader = cls(
            cls.args_model.model_validate(
                {"model": "judge", "json_schema_spec": self.SCHEMA, **args}
            )
        )
        gi = GradingInput(
            traces=(
                Trace(
                    id="t1",
                    session_id="s",
                    observations=(
                        Observation(id="r", trace_id="t1", input="q", output=reply),
                    ),
                ),
            )
        )
        return _grade(grader, gi, VERDICT)

    def test_a_valid_reply_passes_without_a_judge_call(self) -> None:
        [result], requests = self._run('{"a": 1}')
        assert (result.status, result.score, result.scope) == ("scored", 1.0, "turn:1")
        assert requests == []

    @pytest.mark.parametrize("reply", ['{"a": "x"}', "not json"])
    def test_an_invalid_reply_fails_without_a_judge_call(self, reply: str) -> None:
        [result], requests = self._run(reply)
        assert (result.status, result.score) == ("scored", 0.0)
        assert requests == []

    def test_prose_rules_go_to_the_judge_after_the_schema_passes(self) -> None:
        [result], [request] = self._run(
            '{"a": 1}', format_requirements=["Use one key."]
        )
        assert result.status == "scored"
        assert "Use one key." in request["input"][0]["content"]

    def test_it_needs_a_requirement_or_a_schema(self) -> None:
        cls = catalog.FormatSchemaComplianceGrader
        with pytest.raises(ValidationError):
            cls.args_model.model_validate({"model": "judge"})
