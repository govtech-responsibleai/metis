"""The shared judge call: one evidence item in, one result out, with every failure reported."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any, ClassVar

import pytest

from metis.core.grading import GraderResult
from metis.core.trace_processing import (
    Problem,
    render_artifact,
    render_session,
    turns,
)
from metis.core.traces import Observation, Trace
from metis.library.aggregation import AGGREGATION_DEFINITIONS
from metis.library.grader import Grader, JudgeArgs, LLMSettings
from metis.library.judge import judge
from metis.library.taxonomy import (
    Aggregation,
    GraderTaxonomy,
    GraderType,
    JudgmentForm,
    ReferenceType,
    Scope,
)
from tests.fixtures.criterion_judge import judge_client

if TYPE_CHECKING:
    from pathlib import Path

    from metis.core.grading import GradingOutput
    from metis.core.traces import GradingInput


class _Args(JudgeArgs):
    pass


class _Grader(Grader[_Args]):
    args_model = _Args
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=None,
        scopes=(Scope.SESSION,),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.RUBRIC_BASED,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        raise NotImplementedError


_TURNS = turns(
    (
        Trace(
            id="t1",
            session_id="s",
            observations=(Observation(id="r", trace_id="t1", input="q", output="a"),),
        ),
    )
)
TEXT = render_session(_TURNS, tool_results=True)


def _reply(
    score: object = 1, *, status: str = "scored", reason: str = "Grounded."
) -> dict:
    return {"status": status, "score": score, "reason": reason}


def _judge(
    reply: object,
    *,
    label: str = "session",
    evidence: object = TEXT,
    max_input_tokens: int = 100_000,
    context: dict[str, Any] | None = None,
    **client_kwargs: Any,
):
    requests: list[dict[str, Any]] = []
    content = reply if isinstance(reply, str) else json.dumps(reply)
    client = judge_client(content, requests, **client_kwargs)
    args = _Args(model="test-judge", max_input_tokens=max_input_tokens)

    async def run():
        async with client:
            return await judge(
                _Grader(args),
                LLMSettings(client),
                label,
                evidence,
                "Check it.",
                **(context or {}),
            )

    return asyncio.run(run()), requests


def test_sends_the_criteria_scope_rule_and_transcript() -> None:
    result, [request] = _judge(_reply(1))
    assert (result.status, result.score, result.scope) == ("scored", 1.0, "session")
    assert result.reason == "Grounded."
    system = request["input"][0]["content"]
    assert "<criteria>\nCheck it.\n</criteria>" in system
    assert "Judge the whole conversation as one unit." in system
    assert "untrusted evidence" in system
    assert "Return status scored and score 1" in system
    assert request["input"][1]["content"] == [
        {"type": "input_text", "text": "## Turn 1\nUser: q\nAssistant: a"}
    ]
    assert request["text"]["format"]["name"] == "binary_judgment"


@pytest.mark.parametrize(
    ("reply", "status", "score"),
    [
        (_reply(1), "scored", 1.0),
        (_reply(0), "scored", 0.0),
        (_reply(None, status="not_applicable"), "errored", None),
        (_reply(0.5), "errored", None),
    ],
)
def test_the_judgment_form_decides_the_result(reply, status, score) -> None:
    result, _ = _judge(reply)
    assert (result.status, result.score) == (status, score)


def _rule(status: str, score: float | None, reason: str) -> GraderResult:
    return GraderResult(status=status, score=score, reason=reason)  # type: ignore[arg-type]


PASS, FAIL = _rule("scored", 1.0, "met."), _rule("scored", 0.0, "unmet.")
ERROR = _rule("errored", None, "undecided.")


@pytest.mark.parametrize(
    ("rule", "results", "status", "score"),
    [
        (Aggregation.NONE_SINGLE_SCORE, [PASS], "scored", 1.0),
        (Aggregation.NONE_SINGLE_SCORE, [ERROR], "errored", None),
        (Aggregation.PASS_IF_ALL, [PASS, PASS], "scored", 1.0),
        (Aggregation.PASS_IF_ALL, [PASS, FAIL], "scored", 0.0),
        (Aggregation.PASS_IF_ALL, [PASS, ERROR], "errored", None),
        (Aggregation.PASS_IF_ALL, [ERROR, FAIL], "scored", 0.0),
        (Aggregation.PASS_IF_ANY, [FAIL, PASS], "scored", 1.0),
        (Aggregation.PASS_IF_ANY, [ERROR, PASS], "scored", 1.0),
        (Aggregation.PASS_IF_ANY, [FAIL, ERROR], "errored", None),
        (Aggregation.PASS_IF_ANY, [FAIL, FAIL], "scored", 0.0),
    ],
)
def test_aggregation_rules(rule, results, status, score) -> None:
    combined = AGGREGATION_DEFINITIONS[rule](results, "turn:2")
    assert (combined.status, combined.score, combined.scope) == (
        status,
        score,
        "turn:2",
    )


def test_a_combined_reason_names_each_deciding_rule() -> None:
    combined = AGGREGATION_DEFINITIONS[Aggregation.PASS_IF_ALL]([PASS, FAIL, FAIL], "s")
    assert combined.reason == "Not every rule is met: unmet. unmet."
    combined = AGGREGATION_DEFINITIONS[Aggregation.PASS_IF_ALL]([PASS, ERROR], "s")
    assert combined.reason == "No rule failed, but some could not be judged: undecided."


def test_sends_a_rendered_file_as_an_input_file(tmp_path: Path) -> None:
    report = tmp_path / "report.pdf"
    report.write_bytes(b"%PDF-1.4 body")
    result, [request] = _judge(
        _reply(1), label="artifact:report.pdf", evidence=render_artifact(report)
    )
    assert result.scope == "artifact:report.pdf"
    [attached] = request["input"][1]["content"]
    assert (attached["type"], attached["filename"]) == ("input_file", "report.pdf")
    assert attached["file_data"].startswith("data:application/pdf;base64,")


def test_sends_context_text_before_the_evidence_and_context_files_after(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4 source")
    report = tmp_path / "report.pdf"
    report.write_bytes(b"%PDF-1.4 report")
    _, [request] = _judge(
        _reply(1),
        evidence=render_artifact(report),
        context={
            "context_text": "## Turn 1\nUser: q",
            "context_files": [render_artifact(source)],
        },
    )
    parts = request["input"][1]["content"]
    assert [(p["type"], p.get("filename")) for p in parts] == [
        ("input_text", None),
        ("input_file", "report.pdf"),
        ("input_file", "source.pdf"),
    ]
    assert parts[0]["text"] == "## Turn 1\nUser: q"


@pytest.mark.parametrize(
    "client_kwargs",
    [
        {"content": "not json"},
        {"content": json.dumps(_reply(1)), "status": "incomplete"},
        {"content": "", "refusal": "I cannot assess this."},
        {"content": "unavailable", "status_code": 400},
    ],
)
def test_a_failed_or_unusable_reply_is_errored(client_kwargs) -> None:
    content = client_kwargs.pop("content")
    result, _ = _judge(content, **client_kwargs)
    assert (result.status, result.scope) == ("errored", "session")
    assert result.reason.startswith("Judge failed:")


def test_a_problem_is_errored_without_a_call() -> None:
    problem = Problem(kind="missing", detail="The reply cannot be read.")
    result, requests = _judge(_reply(1), label="turn:1", evidence=problem)
    assert (result.status, result.reason, result.scope) == (
        "errored",
        "The reply cannot be read.",
        "turn:1",
    )
    assert requests == []


def test_the_text_budget_ignores_a_file(tmp_path: Path) -> None:
    big = tmp_path / "big.txt"
    big.write_bytes(b"x" * 20_000)
    result, requests = _judge(
        _reply(1), evidence=render_artifact(big), max_input_tokens=10_000
    )
    assert result.status == "scored"
    assert len(requests) == 1
    over, requests = _judge(_reply(1), max_input_tokens=1_000)
    assert over.status == "errored"
    assert "the limit is 1,000" in over.reason
    assert requests == []
