"""The engine traces its own model calls to the METIS-internal Langfuse, and never to the
target's Langfuse that the extractor reads.

Spans are captured where the real Langfuse span processor would export them, after its
per-project filter, so a span that would reach a project shows up in that project's list.
Model replies come from an ``httpx.MockTransport``. Nothing touches the network.
"""

from __future__ import annotations

import asyncio
import atexit
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from langfuse import Langfuse
from langfuse._client import resource_manager
from langfuse._client.resource_manager import LangfuseResourceManager
from langfuse._client.span_processor import LangfuseSpanProcessor
from langfuse.openai import AsyncOpenAI
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from pydantic import BaseModel

from metis.core.grading import GraderResult, GradingOutput
from metis.core.profile import Criterion
from metis.core.traces import GradingInput, Observation, Trace
from metis.engine import tracing
from metis.engine.evaluation.orchestrator import SessionFacts, grade_session
from metis.engine.simulation.experiment import TrialPlanItem, _worker
from metis.engine.simulation.llm_calls import LLMCallLog, parse_completion
from metis.engine.simulation.types import Persona, Scenario
from metis.library.grader import Grader, GraderArgs, LLMSettings
from tests.unit.engine.test_experiment_worker import (
    MockRunnerFactory,
    _make_canned_record,
)

INTERNAL = {
    "METIS_INTERNAL_LANGFUSE_PUBLIC_KEY": "pk-internal",
    "METIS_INTERNAL_LANGFUSE_SECRET_KEY": "sk-internal",
    "METIS_INTERNAL_LANGFUSE_BASE_URL": "https://internal.example",
}
TARGET = {
    "LANGFUSE_PUBLIC_KEY": "pk-target",
    "LANGFUSE_SECRET_KEY": "sk-target",
    "LANGFUSE_BASE_URL": "https://target.example",
}

exported: dict[str, list[ReadableSpan]] = {}


class _CapturingProcessor(LangfuseSpanProcessor):
    """The Langfuse processor with its project filter, keeping spans in place of exporting."""

    def __init__(self, *, public_key: str, **_kwargs: Any) -> None:
        self.public_key = public_key
        self.blocked_instrumentation_scopes = []
        exported.setdefault(public_key, [])

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        pass

    def on_end(self, span: ReadableSpan) -> None:
        if self._is_langfuse_span(span) and not self._is_langfuse_project_span(span):
            return
        exported[self.public_key].append(span)

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int | None = None) -> bool:
        return True


@pytest.fixture(autouse=True)
def langfuse_projects(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Fresh Langfuse clients that export into ``exported``; earlier clients are restored.

    The clients share one tracer provider, as in a real process, so only the per-project
    filter keeps a span out of the other project.
    """
    for name in (*INTERNAL, *TARGET):
        monkeypatch.delenv(name, raising=False)
    provider = TracerProvider()
    monkeypatch.setattr(resource_manager, "LangfuseSpanProcessor", _CapturingProcessor)
    monkeypatch.setattr(
        resource_manager, "_init_tracer_provider", lambda **_kw: provider
    )
    earlier = dict(LangfuseResourceManager._instances)
    LangfuseResourceManager._instances.clear()
    exported.clear()
    tracing.tracing_key.cache_clear()
    yield
    tracing.tracing_key.cache_clear()
    # A shutdown joins Langfuse's daemon threads, which takes a second per client. These
    # clients export nothing, so their exit hooks are dropped in its place.
    for instance in LangfuseResourceManager._instances.values():
        atexit.unregister(instance.shutdown)
    LangfuseResourceManager._instances.clear()
    LangfuseResourceManager._instances.update(earlier)


def _evaluate_registers_the_target_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """``LANGFUSE_*`` set and a target client built, as ``metis engine evaluate`` does."""
    for name, value in TARGET.items():
        monkeypatch.setenv(name, value)
    Langfuse()


def _model(answer: str) -> AsyncOpenAI:
    """The drop-in client, answering every chat call with ``{"answer": answer}``."""

    def reply(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "c1",
                "object": "chat.completion",
                "created": 0,
                "model": "served-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": json.dumps({"answer": answer}),
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 2,
                    "total_tokens": 5,
                },
            },
        )

    return AsyncOpenAI(
        api_key="k",
        base_url="https://model.example/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(reply)),
    )


class _Answer(BaseModel):
    answer: str


# ── simulation ──────────────────────────────────────────────────────────────


def _simulate_one_trial(
    tmp_path: Path, model: AsyncOpenAI
) -> tuple[list[str], Scenario, Persona]:
    """One trial through the real worker. The trial makes one user agent call."""
    scenario = Scenario(
        id="refund",
        task_id="TC-1",
        description="Ask for a refund",
        persona_refs=["tester"],
        num_trials=1,
        max_turns=1,
        grader_refs=[],
    )
    persona = Persona(id="tester", name="tester", description="A test persona")
    answers: list[str] = []

    async def execute() -> Any:
        response = await parse_completion(
            model,
            LLMCallLog.for_trial(tmp_path),
            component="user_agent",
            model="requested-model",
            messages=[{"role": "user", "content": "hello"}],
            response_format=_Answer,
        )
        answers.append(response.choices[0].message.parsed.answer)
        return _make_canned_record(scenario, persona)

    experiment_root = tmp_path / "refunds-20260101-000000"
    with (
        patch("metis.engine.simulation.trial.UserAgent", lambda **_kw: object()),
        patch("metis.engine.simulation.trial.Orchestrator") as orchestrator,
    ):
        orchestrator.return_value = AsyncMock(execute=execute)
        asyncio.run(
            _worker(
                worker_id=0,
                runner_factory=MockRunnerFactory(),
                worker_trials=[TrialPlanItem(scenario, persona, 1)],
                experiment_root=experiment_root,
                fixtures_dir=tmp_path / "fixtures",
                fixture_content_descriptions={},
                console_lock=asyncio.Lock(),
                started_scenarios=set(),
                trial_max_retries=0,
                trial_retry_delay_seconds=0,
                experiment_id="refunds",
            )
        )
    return answers, scenario, persona


def test_a_trial_traces_its_model_calls_to_the_internal_langfuse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name, value in INTERNAL.items():
        monkeypatch.setenv(name, value)
    _evaluate_registers_the_target_client(monkeypatch)

    answers, _, _ = _simulate_one_trial(tmp_path, _model("hi"))

    assert answers == ["hi"]
    assert exported["pk-target"] == []
    spans = {span.name: span for span in exported["pk-internal"]}
    assert set(spans) == {"TC-1 x tester #1", "user_agent"}
    trial = spans["TC-1 x tester #1"].attributes or {}
    assert trial["session.id"] == "refunds-20260101-000000/TC-1/tester/1"
    assert trial["langfuse.trace.metadata.experiment_id"] == "refunds"
    assert trial["langfuse.trace.metadata.persona_id"] == "tester"
    assert trial["langfuse.trace.metadata.attempt"] == 1
    generation = spans["user_agent"]
    assert generation.parent is not None
    assert generation.context.trace_id == spans["TC-1 x tester #1"].context.trace_id


def test_a_simulation_call_outside_any_trace_still_names_the_internal_langfuse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name, value in INTERNAL.items():
        monkeypatch.setenv(name, value)
    _evaluate_registers_the_target_client(monkeypatch)

    asyncio.run(
        parse_completion(
            _model("hi"),
            LLMCallLog.for_experiment(tmp_path),
            component="artifact_summarizer",
            model="requested-model",
            messages=[{"role": "user", "content": "describe it"}],
            response_format=_Answer,
        )
    )

    assert exported["pk-target"] == []
    assert [span.name for span in exported["pk-internal"]] == ["artifact_summarizer"]


# ── grading ─────────────────────────────────────────────────────────────────


class _JudgeGrader(Grader[GraderArgs]):
    """Asks the judge once, with no Langfuse key, as a library grader does."""

    args_model = GraderArgs

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        response = await llm.client.chat.completions.create(
            model="judge-model", messages=[{"role": "user", "content": "score it"}]
        )
        reason = json.loads(response.choices[0].message.content or "{}")["answer"]
        return GradingOutput(
            results=[GraderResult(status="scored", score=1.0, reason=reason)]
        )


def _grade_one_session(model: AsyncOpenAI) -> list[str | None]:
    criterion = Criterion(
        id="AC-1",
        name="Assessment",
        description="Assess the session.",
        grader_fqn=f"{__name__}._JudgeGrader",
    )
    grading_input = GradingInput(
        traces=(
            Trace(
                id="t1",
                session_id="target-session",
                observations=(Observation(id="o1", trace_id="t1", output="hi"),),
            ),
        )
    )
    records = asyncio.run(
        grade_session(
            [criterion],
            {"AC-1": _JudgeGrader(GraderArgs())},
            grading_input,
            LLMSettings(client=model),
            SessionFacts(
                session_id="target-session",
                scenario_id="refund",
                task_id="TC-1",
                trial_index=1,
                trace_session_id="refunds-20260101-000000/TC-1/tester/1",
            ),
        )
    )
    return [result.reason for record in records for result in record.results]


def test_a_grader_traces_its_judge_calls_to_the_internal_langfuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in INTERNAL.items():
        monkeypatch.setenv(name, value)
    tracing.tracing_key()
    _evaluate_registers_the_target_client(monkeypatch)

    reasons = _grade_one_session(_model("well done"))

    assert reasons == ["well done"]
    assert exported["pk-target"] == []
    spans = {span.name: span for span in exported["pk-internal"]}
    assert set(spans) == {"AC-1", "OpenAI-generation"}
    run = spans["AC-1"].attributes or {}
    assert run["session.id"] == "refunds-20260101-000000/TC-1/tester/1"
    assert run["langfuse.trace.metadata.criterion_id"] == "AC-1"
    assert run["langfuse.trace.metadata.session_id"] == "target-session"
    results = [{"status": "scored", "score": 1.0, "reason": "well done"}]
    assert json.loads(str(run["langfuse.observation.output"])) == results
    assert json.loads(str(run["langfuse.trace.output"])) == results
    assert spans["OpenAI-generation"].context.trace_id == spans["AC-1"].context.trace_id


# ── tracing off ─────────────────────────────────────────────────────────────


def test_without_the_internal_langfuse_nothing_reaches_the_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The target's keys are set and its client exists, but tracing is off, so the calls
    go untraced and still return their answers."""
    _evaluate_registers_the_target_client(monkeypatch)

    answers, _, _ = _simulate_one_trial(tmp_path, _model("hi"))
    reasons = _grade_one_session(_model("well done"))

    assert answers == ["hi"]
    assert reasons == ["well done"]
    assert tracing.tracing_key() not in TARGET.values()
    assert exported == {"pk-target": []}


@pytest.mark.parametrize("missing", list(INTERNAL))
def test_tracing_is_off_unless_all_three_internal_variables_are_set(
    missing: str,
) -> None:
    env = {**TARGET, **INTERNAL}
    del env[missing]

    key = tracing.register_tracing(env)

    assert key not in env.values()
    assert LangfuseResourceManager._instances[key].tracing_enabled is False
