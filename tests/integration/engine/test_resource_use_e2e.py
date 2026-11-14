"""E2E stress tests: resource-use graders against the live toy app.

Runs the METIS simulation pipeline against a locally-hosted toy app, extracts
real traces from Langfuse, and validates all six resource-use graders against
them. Gated by ``METIS_RUN_RESOURCE_USE_E2E=1``.

Prerequisites
-------------
- Toy app running at ``TOYAPP_API_URL``
- Langfuse configured (``LANGFUSE_PUBLIC_KEY``, ``LANGFUSE_SECRET_KEY``, ``LANGFUSE_HOST``)
- LLM API keys for the simulation user agent and runner agent
- ``METIS_RUN_RESOURCE_USE_E2E=1``
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from typing import Any
from unittest.mock import MagicMock

import pytest
from tests.conftest import REPO_ROOT

from metis.core import execution_layout
from metis.core.traces import GradingInput
from metis.core.trials import TrialRecord
from metis.library.grader import LLMSettings
from metis.library.graders import (
    ElapsedTimeGrader,
    ExecutionStepCountGrader,
    ModelCallCountGrader,
    MonetaryCostGrader,
    TokenUsageGrader,
    ToolCallCountGrader,
)
from metis.library.graders.resource_use._elapsed_time import ElapsedTimeArgs
from metis.library.graders.resource_use._execution_step_count import (
    ExecutionStepCountArgs,
)
from metis.library.graders.resource_use._model_call_count import ModelCallCountArgs
from metis.library.graders.resource_use._monetary_cost import MonetaryCostArgs
from metis.library.graders.resource_use._token_usage import TokenUsageArgs
from metis.library.graders.resource_use._tool_call_count import ToolCallCountArgs

pytestmark = pytest.mark.skipif(
    os.environ.get("METIS_RUN_RESOURCE_USE_E2E") != "1",
    reason="Set METIS_RUN_RESOURCE_USE_E2E=1 to run live resource-use E2E tests.",
)

_EXAMPLE_DIR = (
    REPO_ROOT / "packages" / "engine" / "examples" / "http-agentic_eval_toyapp-1"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _grade(grader: Any, gi: GradingInput) -> list[Any]:
    client = MagicMock()
    out = asyncio.run(grader.grade(gi, LLMSettings(client=client)))
    client.chat.completions.create.assert_not_called()
    return out.results


def _first(grader: Any, gi: GradingInput) -> Any:
    [result] = _grade(grader, gi)
    return result


# ---------------------------------------------------------------------------
# Module-scoped fixture: simulate + extract
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def experiment_sessions(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, GradingInput]:
    """Run the simulation against the live toy app and fetch all session traces.

    Returns a mapping of ``{session_id: GradingInput}`` for every trial produced
    by the simulation. Runs once per test module.
    """
    tmp = tmp_path_factory.mktemp("resource_use_e2e")

    (tmp / "pyproject.toml").write_text('[project]\nname = "e2e-test"\n')

    input_dir = tmp / "user-inputs"
    shutil.copytree(_EXAMPLE_DIR, input_dir)

    real_env = REPO_ROOT / ".env"
    if real_env.exists():
        shutil.copy2(real_env, tmp / ".env")

    env = os.environ.copy()
    # Ensure TOYAPP_API_URL has no trailing slash — the target binding
    # appends /openapi.json and a double-slash returns 404.
    toyapp = os.environ.get("TOYAPP_API_URL", "").rstrip("/")
    if not toyapp:
        from dotenv import dotenv_values

        vals = dotenv_values(real_env)
        toyapp = (vals.get("TOYAPP_API_URL") or "").rstrip("/")
    if toyapp:
        env["TOYAPP_API_URL"] = toyapp

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "metis_cli",
            "engine",
            "simulate",
            "--input-dir",
            str(input_dir),
            "--no-tui",
            "-v",
        ],
        cwd=str(tmp),
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, (
        f"Simulation failed (exit {result.returncode}):\n"
        f"stdout: {result.stdout[-2000:]}\n"
        f"stderr: {result.stderr[-2000:]}"
    )

    executions = tmp / "experiments" / "execute"
    experiment_dirs = sorted(executions.iterdir(), key=lambda p: p.stat().st_mtime)
    assert experiment_dirs, "No experiment directory was created by the simulation"
    experiment_dir = experiment_dirs[-1]

    record_files = sorted(
        (experiment_dir / execution_layout.TRIALS).glob(
            f"*/{execution_layout.TRIAL_RECORD}"
        ),
        key=lambda p: p.stat().st_mtime,
    )
    assert record_files, "No trial records found after simulation"

    records = [TrialRecord.load_file(f) for f in record_files]
    failed = [r for r in records if r.outcome.stop_reason == "system_error"]
    assert not failed, (
        f"{len(failed)}/{len(records)} trials hit system_error. "
        f"Simulation stderr:\n{result.stderr[-3000:]}\n"
        f"Simulation stdout (tail):\n{result.stdout[-3000:]}"
    )

    from metis.core.model_settings import load_env

    load_env()

    from metis.engine.extractor.langfuse import (
        TraceWaitSettings,
        fetch_session,
        get_langfuse_client,
    )

    langfuse = get_langfuse_client()
    wait = TraceWaitSettings(timeout_seconds=90)

    async def _fetch_all() -> dict[str, GradingInput]:
        sessions: dict[str, GradingInput] = {}
        for record in records:
            sid = record.target_session_id
            assert sid, f"Trial {record.config.scenario} has no target_session_id"
            gi = await fetch_session(
                sid,
                langfuse,
                experiment_root=experiment_dir,
                artifacts=record.artifacts,
                settings=wait,
            )
            assert gi.traces, f"Session {sid} has no traces in Langfuse"
            sessions[sid] = gi
        return sessions

    try:
        return asyncio.run(_fetch_all())
    finally:
        langfuse.shutdown()


@pytest.fixture(scope="module")
def any_session(experiment_sessions: dict[str, GradingInput]) -> GradingInput:
    """A single session's GradingInput for tests that only need one."""
    return next(iter(experiment_sessions.values()))


# ---------------------------------------------------------------------------
# ElapsedTimeGrader
# ---------------------------------------------------------------------------


class TestElapsedTimeE2E:
    def test_loose_budget_passes(
        self, experiment_sessions: dict[str, GradingInput]
    ) -> None:
        grader = ElapsedTimeGrader(ElapsedTimeArgs(max_seconds=600.0))
        for gi in experiment_sessions.values():
            result = _first(grader, gi)
            assert result.status == "scored"
            assert result.score == 1.0
            assert result.scope == "session"

    def test_tight_budget_fails(
        self, experiment_sessions: dict[str, GradingInput]
    ) -> None:
        grader = ElapsedTimeGrader(ElapsedTimeArgs(max_seconds=0.001))
        for gi in experiment_sessions.values():
            result = _first(grader, gi)
            assert result.status == "scored"
            assert result.score == 0.0

    def test_measurement_is_positive(
        self, experiment_sessions: dict[str, GradingInput]
    ) -> None:
        grader = ElapsedTimeGrader(ElapsedTimeArgs(max_seconds=600.0))
        for gi in experiment_sessions.values():
            result = _first(grader, gi)
            elapsed = result.measurements["elapsed_seconds"]
            assert elapsed > 0, "A real session must take some time"
            assert elapsed < 600, "Session should finish well within the 10-min timeout"


# ---------------------------------------------------------------------------
# ExecutionStepCountGrader
# ---------------------------------------------------------------------------


class TestExecutionStepCountE2E:
    def test_loose_budget_passes(
        self, experiment_sessions: dict[str, GradingInput]
    ) -> None:
        grader = ExecutionStepCountGrader(ExecutionStepCountArgs(max_steps=1000))
        for gi in experiment_sessions.values():
            result = _first(grader, gi)
            assert result.status == "scored"
            assert result.score == 1.0

    def test_tight_budget_fails(
        self, experiment_sessions: dict[str, GradingInput]
    ) -> None:
        grader = ExecutionStepCountGrader(ExecutionStepCountArgs(max_steps=1))
        for gi in experiment_sessions.values():
            result = _first(grader, gi)
            assert result.status == "scored"
            assert result.score == 0.0, (
                f"RAG app should use more than 1 step, "
                f"got {result.measurements['execution_steps']}"
            )

    def test_step_count_at_least_one(
        self, experiment_sessions: dict[str, GradingInput]
    ) -> None:
        grader = ExecutionStepCountGrader(ExecutionStepCountArgs(max_steps=1000))
        for gi in experiment_sessions.values():
            result = _first(grader, gi)
            assert result.measurements["execution_steps"] >= 1


# ---------------------------------------------------------------------------
# ModelCallCountGrader
# ---------------------------------------------------------------------------


class TestModelCallCountE2E:
    def test_loose_budget_passes(
        self, experiment_sessions: dict[str, GradingInput]
    ) -> None:
        grader = ModelCallCountGrader(ModelCallCountArgs(max_calls=100))
        for gi in experiment_sessions.values():
            result = _first(grader, gi)
            assert result.status == "scored"
            assert result.score == 1.0

    def test_tight_budget_fails(
        self, experiment_sessions: dict[str, GradingInput]
    ) -> None:
        grader = ModelCallCountGrader(ModelCallCountArgs(max_calls=1))
        for gi in experiment_sessions.values():
            result = _first(grader, gi)
            assert result.status == "scored"
            # Multi-agent RAG app makes multiple model calls
            assert result.measurements["model_calls"] >= 1

    def test_model_calls_positive(
        self, experiment_sessions: dict[str, GradingInput]
    ) -> None:
        grader = ModelCallCountGrader(ModelCallCountArgs(max_calls=100))
        for gi in experiment_sessions.values():
            result = _first(grader, gi)
            assert result.measurements["model_calls"] >= 1, (
                "A RAG app must make at least one model call"
            )


# ---------------------------------------------------------------------------
# ToolCallCountGrader
# ---------------------------------------------------------------------------


class TestToolCallCountE2E:
    def test_loose_budget_passes(
        self, experiment_sessions: dict[str, GradingInput]
    ) -> None:
        grader = ToolCallCountGrader(ToolCallCountArgs(max_calls=100))
        for gi in experiment_sessions.values():
            result = _first(grader, gi)
            assert result.status == "scored"
            assert result.score == 1.0

    def test_measurement_non_negative(
        self, experiment_sessions: dict[str, GradingInput]
    ) -> None:
        grader = ToolCallCountGrader(ToolCallCountArgs(max_calls=100))
        for gi in experiment_sessions.values():
            result = _first(grader, gi)
            assert result.measurements["tool_calls"] >= 0


# ---------------------------------------------------------------------------
# MonetaryCostGrader
# ---------------------------------------------------------------------------


class TestMonetaryCostE2E:
    def test_loose_budget_passes(
        self, experiment_sessions: dict[str, GradingInput]
    ) -> None:
        grader = MonetaryCostGrader(MonetaryCostArgs(max_cost=100.0))
        for gi in experiment_sessions.values():
            result = _first(grader, gi)
            assert result.status == "scored"
            assert result.score == 1.0

    def test_tight_budget_fails(
        self, experiment_sessions: dict[str, GradingInput]
    ) -> None:
        grader = MonetaryCostGrader(MonetaryCostArgs(max_cost=0.0000001))
        for gi in experiment_sessions.values():
            result = _first(grader, gi)
            assert result.status == "scored"
            assert result.score == 0.0

    def test_cost_is_positive(
        self, experiment_sessions: dict[str, GradingInput]
    ) -> None:
        grader = MonetaryCostGrader(MonetaryCostArgs(max_cost=100.0))
        for gi in experiment_sessions.values():
            result = _first(grader, gi)
            assert result.measurements["cost_usd"] > 0


# ---------------------------------------------------------------------------
# TokenUsageGrader
# ---------------------------------------------------------------------------


class TestTokenUsageE2E:
    def test_loose_budget_passes(
        self, experiment_sessions: dict[str, GradingInput]
    ) -> None:
        grader = TokenUsageGrader(TokenUsageArgs(max_total_tokens=10_000_000))
        for gi in experiment_sessions.values():
            result = _first(grader, gi)
            assert result.status == "scored"
            assert result.score == 1.0

    def test_tight_budget_fails(
        self, experiment_sessions: dict[str, GradingInput]
    ) -> None:
        grader = TokenUsageGrader(TokenUsageArgs(max_total_tokens=1))
        for gi in experiment_sessions.values():
            result = _first(grader, gi)
            assert result.status == "scored"
            assert result.score == 0.0

    def test_tokens_positive(
        self, experiment_sessions: dict[str, GradingInput]
    ) -> None:
        grader = TokenUsageGrader(TokenUsageArgs(max_total_tokens=10_000_000))
        for gi in experiment_sessions.values():
            result = _first(grader, gi)
            assert result.measurements["total_tokens"] > 0


# ---------------------------------------------------------------------------
# Cross-grader consistency
# ---------------------------------------------------------------------------


class TestCrossGraderConsistency:
    def test_measurement_relationships(
        self, experiment_sessions: dict[str, GradingInput]
    ) -> None:
        """Execution steps >= model calls + tool calls for every session."""
        for gi in experiment_sessions.values():
            elapsed_result = _first(
                ElapsedTimeGrader(ElapsedTimeArgs(max_seconds=600.0)), gi
            )
            steps_result = _first(
                ExecutionStepCountGrader(ExecutionStepCountArgs(max_steps=1000)), gi
            )
            model_result = _first(
                ModelCallCountGrader(ModelCallCountArgs(max_calls=100)), gi
            )
            tool_result = _first(
                ToolCallCountGrader(ToolCallCountArgs(max_calls=100)), gi
            )

            elapsed = elapsed_result.measurements["elapsed_seconds"]
            steps = steps_result.measurements["execution_steps"]
            models = model_result.measurements["model_calls"]
            tools = tool_result.measurements["tool_calls"]

            assert elapsed > 0
            assert models >= 1
            assert steps >= models + tools, (
                f"execution_steps ({steps}) should be >= "
                f"model_calls ({models}) + tool_calls ({tools})"
            )

    def test_all_scored_graders_report_session_scope(
        self, any_session: GradingInput
    ) -> None:
        scored_graders = [
            ElapsedTimeGrader(ElapsedTimeArgs(max_seconds=600.0)),
            ExecutionStepCountGrader(ExecutionStepCountArgs(max_steps=1000)),
            ModelCallCountGrader(ModelCallCountArgs(max_calls=100)),
            ToolCallCountGrader(ToolCallCountArgs(max_calls=100)),
            MonetaryCostGrader(MonetaryCostArgs(max_cost=100.0)),
            TokenUsageGrader(TokenUsageArgs(max_total_tokens=10_000_000)),
        ]
        for grader in scored_graders:
            result = _first(grader, any_session)
            assert result.scope == "session", (
                f"{type(grader).__name__} reported scope '{result.scope}', expected 'session'"
            )

    def test_concurrent_grading(self, any_session: GradingInput) -> None:
        """All six graders run concurrently without interfering."""
        graders = [
            ElapsedTimeGrader(ElapsedTimeArgs(max_seconds=600.0)),
            ExecutionStepCountGrader(ExecutionStepCountArgs(max_steps=1000)),
            ModelCallCountGrader(ModelCallCountArgs(max_calls=100)),
            ToolCallCountGrader(ToolCallCountArgs(max_calls=100)),
            MonetaryCostGrader(MonetaryCostArgs(max_cost=1.0)),
            TokenUsageGrader(TokenUsageArgs(max_total_tokens=1_000_000)),
        ]

        sequential = [_first(g, any_session) for g in graders]

        async def _run_all() -> list[Any]:
            client = MagicMock()
            llm = LLMSettings(client=client)
            outputs = await asyncio.gather(
                *(g.grade(any_session, llm) for g in graders)
            )
            return [out.results[0] for out in outputs]

        concurrent = asyncio.run(_run_all())

        for seq, con, grader in zip(sequential, concurrent, graders, strict=True):
            name = type(grader).__name__
            assert seq.status == con.status, f"{name}: status differs"
            assert seq.score == con.score, f"{name}: score differs"
            assert seq.measurements == con.measurements, f"{name}: measurements differ"


# ---------------------------------------------------------------------------
# Multi-session stress
# ---------------------------------------------------------------------------


class TestMultiSessionStress:
    def test_all_sessions_have_traces(
        self, experiment_sessions: dict[str, GradingInput]
    ) -> None:
        assert len(experiment_sessions) >= 1, "Need at least one session"
        for sid, gi in experiment_sessions.items():
            assert gi.traces, f"Session {sid} has no traces"

    def test_budget_boundary_sweep(
        self, experiment_sessions: dict[str, GradingInput]
    ) -> None:
        """For each session, verify the exact boundary: measured value passes, one below fails."""
        for gi in experiment_sessions.values():
            # Elapsed time
            measured = _first(
                ElapsedTimeGrader(ElapsedTimeArgs(max_seconds=600.0)), gi
            ).measurements["elapsed_seconds"]
            if measured > 0.01:
                assert (
                    _first(
                        ElapsedTimeGrader(ElapsedTimeArgs(max_seconds=measured + 1.0)),
                        gi,
                    ).score
                    == 1.0
                )
                assert (
                    _first(
                        ElapsedTimeGrader(
                            ElapsedTimeArgs(max_seconds=max(0.001, measured - 0.001))
                        ),
                        gi,
                    ).score
                    == 0.0
                )

            # Execution step count
            steps = _first(
                ExecutionStepCountGrader(ExecutionStepCountArgs(max_steps=1000)), gi
            ).measurements["execution_steps"]
            steps_int = int(steps)
            if steps_int >= 2:
                assert (
                    _first(
                        ExecutionStepCountGrader(
                            ExecutionStepCountArgs(max_steps=steps_int + 1)
                        ),
                        gi,
                    ).score
                    == 1.0
                )
                assert (
                    _first(
                        ExecutionStepCountGrader(
                            ExecutionStepCountArgs(max_steps=steps_int - 1)
                        ),
                        gi,
                    ).score
                    == 0.0
                )

            # Model call count
            models = _first(
                ModelCallCountGrader(ModelCallCountArgs(max_calls=100)), gi
            ).measurements["model_calls"]
            models_int = int(models)
            if models_int >= 2:
                assert (
                    _first(
                        ModelCallCountGrader(
                            ModelCallCountArgs(max_calls=models_int + 1)
                        ),
                        gi,
                    ).score
                    == 1.0
                )
                assert (
                    _first(
                        ModelCallCountGrader(
                            ModelCallCountArgs(max_calls=models_int - 1)
                        ),
                        gi,
                    ).score
                    == 0.0
                )

            # Tool call count
            tools = _first(
                ToolCallCountGrader(ToolCallCountArgs(max_calls=100)), gi
            ).measurements["tool_calls"]
            tools_int = int(tools)
            if tools_int >= 2:
                assert (
                    _first(
                        ToolCallCountGrader(ToolCallCountArgs(max_calls=tools_int + 1)),
                        gi,
                    ).score
                    == 1.0
                )
                assert (
                    _first(
                        ToolCallCountGrader(ToolCallCountArgs(max_calls=tools_int - 1)),
                        gi,
                    ).score
                    == 0.0
                )

            # Monetary cost
            cost = _first(
                MonetaryCostGrader(MonetaryCostArgs(max_cost=100.0)), gi
            ).measurements["cost_usd"]
            if cost > 0.0001:
                assert (
                    _first(
                        MonetaryCostGrader(MonetaryCostArgs(max_cost=cost + 0.01)), gi
                    ).score
                    == 1.0
                )
                assert (
                    _first(
                        MonetaryCostGrader(
                            MonetaryCostArgs(max_cost=max(0.0000001, cost - 0.0000001))
                        ),
                        gi,
                    ).score
                    == 0.0
                )

            # Token usage
            tokens = _first(
                TokenUsageGrader(TokenUsageArgs(max_total_tokens=10_000_000)), gi
            ).measurements["total_tokens"]
            tokens_int = int(tokens)
            if tokens_int >= 2:
                assert (
                    _first(
                        TokenUsageGrader(
                            TokenUsageArgs(max_total_tokens=tokens_int + 1)
                        ),
                        gi,
                    ).score
                    == 1.0
                )
                assert (
                    _first(
                        TokenUsageGrader(
                            TokenUsageArgs(max_total_tokens=tokens_int - 1)
                        ),
                        gi,
                    ).score
                    == 0.0
                )
