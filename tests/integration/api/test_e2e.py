"""Offline end-to-end over HTTP: walk the interview to DONE, then compile an engine-valid experiment.

This drives the wizard's own corridor (`walk`) through the HTTP door instead of in process, so the
door and the wizard gate share one answer script. It reaches DONE over the Interview lifecycle, compiles the
finished Specification over `/compile`, and loads the returned experiment through the engine's own gate —
the same check the wizard's Slice B gate makes, now proven through the API. No network, no gateway.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import TypeAdapter

from metis.wizard.contracts import (
    InterviewEndRequest,
    InterviewRequest,
    InterviewResult,
    InterviewStartRequest,
)
from tests.fixtures.wizard.scripted import ScriptedInterviewer, walk


def test_interview_lifecycle_compiles_an_engine_valid_experiment(
    make_client,
    tmp_path: Path,
) -> None:
    client = make_client(ScriptedInterviewer())
    adapter: TypeAdapter[InterviewResult] = TypeAdapter(InterviewResult)

    def send(request: InterviewRequest) -> object:
        if isinstance(request, InterviewStartRequest):
            path = "/api/v1/wizard/interview/start"
        elif isinstance(request, InterviewEndRequest):
            path = "/api/v1/wizard/interview/end"
        else:
            path = "/api/v1/wizard/interview/turn"
        response = client.post(path, json=request.model_dump(mode="json"))
        assert response.status_code == 200, response.text
        return adapter.validate_python(response.json())

    result = walk(send=send)

    assert result.state.confirmed
    assert result.state.pending is None

    compiled = client.post(
        "/api/v1/wizard/compile",
        json=result.state.specification.model_dump(mode="json"),
    )
    assert compiled.status_code == 200

    experiment_path = tmp_path / "specification.yaml"
    experiment_path.write_text(compiled.json()["specification.yaml"], encoding="utf-8")

    from metis.engine.simulation.types import Specification

    experiment = Specification.load_file(experiment_path)
    assert experiment.scenarios
    assert all(scenario.grader_refs for scenario in experiment.resolved_tasks())
