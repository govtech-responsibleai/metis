"""Grade a METIS run's saved sessions again, offline, in a chosen trace layout.

The same conversations are graded with the same graders and judge, so any difference in the
verdicts comes from the layout (or, between two ``turn_root`` passes, from the judge itself).

``turn_root`` grades the traces as saved. ``http_root`` first wraps each trace the way
FastAPI's request tracing does: a parentless ``POST /api/v1/chat`` span marked as the root, a
``fastapi.endpoint`` span under it, and the target's own turn span under that.

The output folder holds copies of the run's trial records and a new
``outputs/reports/results.json``, so it reads like a run: ``metis-testbed
touchstone-verdicts`` exports it for a Touchstone app's answer key.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from typing import TYPE_CHECKING, Any, Literal

from metis.core import SessionTraces
from metis.core import execution_layout as layout
from metis.core.reporting import EvaluationResults, GraderRecord
from metis.core.traces import GradingInput
from metis.core.trials import TrialRecord
from metis.engine.evaluation import (
    JudgeGateway,
    SessionFacts,
    build_grader,
    build_llm_settings,
    grade_session,
)
from metis.engine.simulation.types import Specification

if TYPE_CHECKING:
    from pathlib import Path

TraceLayout = Literal["turn_root", "http_root"]


def http_root(rows: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    """The trace's rows with FastAPI's request span and endpoint span above the root."""
    copied = [dict(row) for row in rows]
    roots = [row for row in copied if not row.get("parentObservationId")]
    if len(roots) != 1:
        raise ValueError(f"expected one parentless observation, found {len(roots)}")
    turn = roots[0]
    request_id, endpoint_id = f"{turn['id']}-http", f"{turn['id']}-endpoint"
    timing = {key: turn.get(key) for key in ("startTime", "endTime", "latency")}
    common = {
        key: turn.get(key)
        for key in ("traceId", "projectId", "level", "environment", "version")
    }
    request = {
        **common,
        **timing,
        "id": request_id,
        "parentObservationId": None,
        "type": "SPAN",
        "name": "POST /api/v1/chat",
        "input": None,
        "output": None,
        "metadata": {},
        "isRootObservation": "True",
    }
    endpoint = {
        **request,
        "id": endpoint_id,
        "parentObservationId": request_id,
        "name": "fastapi.endpoint",
        "isRootObservation": "False",
    }
    for row in copied:
        row["isRootObservation"] = "False"
    turn["parentObservationId"] = endpoint_id
    return [request, endpoint, *copied]


def load_traces(
    experiment: Path, session_id: str, trace_layout: TraceLayout
) -> SessionTraces:
    saved = SessionTraces.load_file(
        experiment / layout.TRACES / layout.trace_file_name(session_id)
    )
    if trace_layout == "turn_root":
        return saved
    return SessionTraces.model_validate(
        {
            "session_id": saved.session_id,
            "traces": [
                {"id": trace.id, "observations": http_root(trace.observations)}
                for trace in saved.traces
            ],
        }
    )


async def regrade(
    experiment: Path, trace_layout: TraceLayout, out: Path, concurrency: int
) -> int:
    """Grade every saved session into ``out``; returns how many sessions were graded."""
    specification = Specification.load_file(experiment / layout.SPECIFICATION)
    criteria_by_id = {c.id: c for b in specification.behaviours() for c in b.criteria}
    default_judge_model = specification.experiment.defaults.judge_model
    graders = {
        cid: build_grader(
            criterion, default_judge_model=default_judge_model, env=os.environ
        )
        for cid, criterion in criteria_by_id.items()
    }
    gateway = JudgeGateway.from_env(os.environ)
    if gateway is None:
        raise ValueError("No judge API key is set; see the model guide.")
    llm = build_llm_settings(gateway)

    record_paths = sorted((experiment / layout.TRIALS).glob(f"*/{layout.TRIAL_RECORD}"))
    records = [TrialRecord.load_file(path) for path in record_paths]
    shutil.rmtree(out, ignore_errors=True)
    for record_path in record_paths:
        target = out / record_path.relative_to(experiment)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(record_path, target)

    gate = asyncio.Semaphore(concurrency)

    async def one(record: TrialRecord) -> list[GraderRecord]:
        session_id = record.target_session_id
        if (
            not session_id
            or not (
                experiment / layout.TRACES / layout.trace_file_name(session_id)
            ).exists()
        ):
            return []
        traces = load_traces(experiment, session_id, trace_layout).to_traces()
        criteria = [
            criteria_by_id[ref.criterion_id] for ref in record.config.grader_refs
        ]
        async with gate:
            return await grade_session(
                criteria,
                graders,
                GradingInput(traces=traces),
                llm,
                SessionFacts(
                    session_id=session_id,
                    scenario_id=record.config.scenario,
                    task_id=record.config.task_id,
                    trial_index=record.config.trial_index,
                    trace_session_id=f"regrade-{trace_layout}/{session_id}",
                ),
            )

    try:
        graded = await asyncio.gather(*(one(record) for record in records))
    finally:
        await llm.client.close()
    results = EvaluationResults(
        run_id=f"{experiment.name}-regrade-{trace_layout}",
        records=[r for session in graded for r in session],
    )
    results.save(out / layout.RESULTS)
    return sum(1 for session in graded if session)
