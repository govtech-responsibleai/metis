"""A synthetic helpdesk session for trace-processor and demo-grader tests.

``_helpdesk.rows`` builds the raw Langfuse Observations API v2 rows of a five-turn session in
which a coordinator agent answers ticket questions and hands work to two sub-agents.
``load_session`` builds those rows into a ``GradingInput`` the way
``metis.engine.extractor.fetch_session`` does.
"""

from __future__ import annotations

from collections import defaultdict

from metis.core.traces import GradingInput, Observation, Trace
from tests.fixtures.traces._helpdesk import SESSION_ID, rows

__all__ = ["SESSION_ID", "load_session"]


def _root_start(trace: Trace) -> tuple[bool, float]:
    start = trace.root.start_time
    return (start is None, start.timestamp() if start else 0.0)


def load_session() -> GradingInput:
    """The session as graders receive it. It has no artifacts: none were recorded."""
    by_trace: dict[str, list[Observation]] = defaultdict(list)
    for row in rows():
        observation = Observation.model_validate(row)
        by_trace[observation.trace_id].append(observation)
    traces = [
        Trace.from_observations(trace_id, SESSION_ID, observations)
        for trace_id, observations in by_trace.items()
    ]
    return GradingInput(traces=tuple(sorted(traces, key=_root_start)))
