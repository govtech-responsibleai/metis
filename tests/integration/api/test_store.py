"""The store over HTTP: two browsers share an Interview, and a done Interview gives the engine an
input folder.

Two TestClients over two app objects and one store act as two browsers of one project. The
walk drives the scripted Interview to done through the wizard routes, and the store routes save
each state that the web app saves. The engine's own input gate then reads the input folder.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml
from pydantic import TypeAdapter

from metis.wizard import InterviewState, set_connection
from metis.wizard.contracts import (
    InterviewEndRequest,
    InterviewRequest,
    InterviewResult,
    InterviewStartRequest,
)
from tests.fixtures.api.records import done_state, put_interview, ref, web_record
from tests.fixtures.wizard.connections import connection
from tests.fixtures.wizard.scripted import ScriptedInterviewer, walk

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

TARGET = "8d2f6e10-41b7-4c3a-a5e9-0f1e2d3c4b5a"
POLICY = b"%PDF-1.4 policy bytes"


def _walk(client: TestClient) -> InterviewState:
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

    return walk(send=send).state


def _fixture_parts(state: InterviewState) -> tuple[list[dict[str, Any]], list[Any]]:
    """The fixture refs and parts for each fixture that the Specification refers to."""
    names = sorted(
        {name for task in state.specification.tasks for name in task.fixtures}
    )
    refs = [ref(name, POLICY, "application/pdf") for name in names]
    parts = [("files", (name, POLICY, "application/pdf")) for name in names]
    return refs, parts


def _validate_inputs(input_dir: Path) -> None:
    from metis.engine.cli import _validate_inputs as engine_gate

    engine_gate(input_dir)


def test_an_interview_saved_in_one_browser_opens_in_another(make_client) -> None:
    browser_a = make_client(ScriptedInterviewer())
    browser_b = make_client(ScriptedInterviewer())
    record = web_record(
        TARGET,
        done_state(),
        fixtures=[ref("policy.pdf", POLICY, "application/pdf")],
    )

    saved = put_interview(
        browser_a, record, [("files", ("policy.pdf", POLICY, "application/pdf"))]
    )

    assert saved.status_code == 204, saved.text
    listed = browser_b.get("/api/v1/targets").json()
    assert [row["id"] for row in listed["targets"]] == [TARGET]
    opened = browser_b.get(f"/api/v1/targets/{TARGET}/interview")
    assert opened.status_code == 200
    assert opened.json() == record
    file = browser_b.get(f"/api/v1/targets/{TARGET}/interview/files/policy.pdf")
    assert file.content == POLICY
    assert file.headers["content-type"] == "application/pdf"


def test_each_save_of_a_done_interview_writes_its_specification(
    make_client, project_dir: Path
) -> None:
    client = make_client(ScriptedInterviewer())
    state = _walk(client)
    refs, parts = _fixture_parts(state)

    saved = put_interview(client, web_record(TARGET, state, fixtures=refs), parts)

    assert saved.status_code == 204, saved.text
    first = client.get(f"/api/v1/targets/{TARGET}/specification").json()
    input_dir = Path(first["input_dir"])
    assert input_dir == (
        project_dir.resolve() / "experiments" / "design" / TARGET / "outputs"
    )
    yaml_bytes = (input_dir / "specification.yaml").read_bytes()
    assert first["specification_yaml"] == yaml_bytes.decode("utf-8")
    assert first["sha256"] == hashlib.sha256(yaml_bytes).hexdigest()
    _validate_inputs(input_dir)

    changed = state.model_copy(deep=True)
    changed.specification.experiment.defaults.judge_model = "chosen-judge"
    resaved = put_interview(client, web_record(TARGET, changed, fixtures=refs))

    assert resaved.status_code == 204, resaved.text
    second = client.get(f"/api/v1/targets/{TARGET}/specification").json()
    assert second["sha256"] != first["sha256"]
    document = yaml.safe_load(second["specification_yaml"])
    assert document["defaults"]["judge_model"] == "chosen-judge"
    assert (input_dir / "specification.yaml").read_text() == second[
        "specification_yaml"
    ]

    reopened = changed.model_copy(deep=True)
    reopened.confirmed = False
    back = put_interview(client, web_record(TARGET, reopened, fixtures=refs))

    assert back.status_code == 204, back.text
    assert client.get(f"/api/v1/targets/{TARGET}/specification").json() == second
    assert (input_dir / "specification.yaml").read_text() == second[
        "specification_yaml"
    ]


def test_a_target_has_no_specification_before_its_interview_is_done(
    client: TestClient,
) -> None:
    started = client.post(
        "/api/v1/wizard/interview/start",
        json=InterviewStartRequest(description="A policy assistant").model_dump(
            mode="json"
        ),
    ).json()["state"]

    saved = put_interview(client, web_record(TARGET, started))

    assert saved.status_code == 204, saved.text
    missing = client.get(f"/api/v1/targets/{TARGET}/specification")
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"


@pytest.mark.parametrize("connected", [False, True])
def test_the_outputs_folder_passes_the_engine_gate_and_resolves_its_binding(
    client: TestClient,
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    connected: bool,
) -> None:
    from metis.engine.simulation.binding import load_target_binding

    monkeypatch.setenv("APP_URL", "https://target.example")
    monkeypatch.setenv("APP_KEY", "test-key")

    state = done_state()
    if connected:
        state = set_connection(state, connection())
    record = web_record(
        TARGET, state, fixtures=[ref("policy.pdf", POLICY, "application/pdf")]
    )
    saved = put_interview(
        client, record, [("files", ("policy.pdf", POLICY, "application/pdf"))]
    )
    assert saved.status_code == 204, saved.text
    input_dir = Path(
        client.get(f"/api/v1/targets/{TARGET}/specification").json()["input_dir"]
    )
    target_dir = project_dir.resolve() / "experiments" / "design" / TARGET
    assert input_dir == target_dir / "outputs"
    assert (target_dir / "inputs" / "fixtures" / "policy.pdf").read_bytes() == POLICY

    _validate_inputs(input_dir)

    names = {path.relative_to(input_dir).as_posix() for path in input_dir.rglob("*")}
    expected = {"specification.yaml", "fixtures", "fixtures/policy.pdf"}
    document = yaml.safe_load((input_dir / "specification.yaml").read_text())
    if connected:
        assert names == {*expected, "target-binding.yaml"}
        binding = load_target_binding(input_dir, document["target_binding"])
        assert binding.binding.transport == "http"
    else:
        assert names == expected
        assert "target_binding" not in document
    assert (input_dir / "fixtures" / "policy.pdf").read_bytes() == POLICY
