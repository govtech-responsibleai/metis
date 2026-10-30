from __future__ import annotations

import io
import json
import zipfile

import pytest
import yaml
from fastapi import UploadFile
from fastapi.testclient import TestClient

from metis.api.routes.wizard import package as package_route
from metis.wizard import (
    ConnectionTransport,
    InterviewState,
    compile_specification,
    set_connection,
)
from tests.fixtures.wizard.connections import PLANTED_SECRET, connection
from tests.fixtures.wizard.context import interview_context
from tests.fixtures.wizard.specifications import research_assistant

pytestmark = pytest.mark.usefixtures("export_clock")


def _specification() -> str:
    return research_assistant().model_dump_json()


def test_package_returns_a_portable_zip_with_specification_and_fixtures(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/wizard/package",
        data={"specification": _specification()},
        files=[("files", ("policy.pdf", b"policy bytes", "application/pdf"))],
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["access-control-expose-headers"] == "Content-Disposition"
    assert "20261016-223045-manual.zip" in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == {
            "20261016-223045-manual/inputs/",
            "20261016-223045-manual/outputs/specification.yaml",
            "20261016-223045-manual/outputs/fixtures/",
            "20261016-223045-manual/outputs/fixtures/policy.pdf",
        }
        assert (
            archive.read("20261016-223045-manual/outputs/fixtures/policy.pdf")
            == b"policy bytes"
        )


def test_package_includes_unreferenced_fixture_bytes_without_server_state(
    make_client,
) -> None:
    request = {
        "specification": _specification(),
    }
    files = [
        ("files", ("policy.pdf", b"policy bytes", "application/pdf")),
        ("files", ("notes.txt", b"notes", "text/plain")),
    ]

    first = make_client().post("/api/v1/wizard/package", data=request, files=files)
    second = make_client().post(
        "/api/v1/wizard/package",
        data=request,
        files=[("files", ("policy.pdf", b"policy bytes", "application/pdf"))],
    )

    assert first.status_code == second.status_code == 200
    with zipfile.ZipFile(io.BytesIO(first.content)) as archive:
        assert (
            archive.read("20261016-223045-manual/outputs/fixtures/notes.txt")
            == b"notes"
        )
    with zipfile.ZipFile(io.BytesIO(second.content)) as archive:
        assert (
            "20261016-223045-manual/outputs/fixtures/notes.txt"
            not in archive.namelist()
        )


def test_package_rejects_a_specification_with_a_missing_fixture(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/wizard/package",
        data={"specification": _specification()},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "compilation_failed"
    assert "policy.pdf" in response.json()["message"]


def test_package_rejects_an_invalid_specification(client: TestClient) -> None:
    response = client.post(
        "/api/v1/wizard/package",
        data={"specification": "not json"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "type": "failure",
        "code": "validation_error",
        "message": "Supply one valid Interview state or manual Specification.",
        "retryable": False,
    }


def test_package_rejects_unsafe_fixture_names(client: TestClient) -> None:
    response = client.post(
        "/api/v1/wizard/package",
        data={"specification": _specification()},
        files=[("files", ("../policy.pdf", b"policy bytes", "application/pdf"))],
    )

    assert response.status_code == 400
    assert response.json()["code"] == "compilation_failed"


def test_package_rejects_duplicate_fixture_identities(client: TestClient) -> None:
    response = client.post(
        "/api/v1/wizard/package",
        data={"specification": _specification()},
        files=[
            ("files", ("policy.pdf", b"one", "application/pdf")),
            ("files", ("POLICY.PDF", b"two", "application/pdf")),
        ],
    )

    assert response.status_code == 400
    assert response.json()["code"] == "compilation_failed"


def test_package_rejects_excess_fixture_parts_before_reading_bodies(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/wizard/package",
        data={"specification": _specification()},
        files=[
            ("files", (f"fixture-{index}.txt", b"x", "text/plain"))
            for index in range(21)
        ],
    )

    assert response.status_code == 400
    assert response.json()["code"] == "compilation_failed"


class CloseTrackingStream(io.BytesIO):
    """Track direct route cleanup without relying on multipart parser details."""

    def __init__(self, content: bytes, *, failure: BaseException | None = None) -> None:
        super().__init__(content)
        self.failure = failure
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if self.failure is not None:
            raise self.failure
        return super().read(size)


def test_package_closes_uploads_after_success() -> None:
    stream = CloseTrackingStream(b"fixture")
    response = package_route(
        _specification(), [UploadFile(filename="policy.pdf", file=stream)]
    )

    assert response.status_code == 200
    assert stream.closed
    assert stream.read_sizes
    assert all(size > 0 for size in stream.read_sizes)


def test_package_closes_uploads_after_unexpected_failure() -> None:
    stream = CloseTrackingStream(b"fixture", failure=RuntimeError("read failed"))

    with pytest.raises(RuntimeError, match="read failed"):
        package_route(
            _specification(), [UploadFile(filename="policy.pdf", file=stream)]
        )

    assert stream.closed


def test_interview_export_preserves_the_state_used_to_compile(
    client: TestClient,
) -> None:
    state = InterviewState(
        specification=research_assistant(),
        context=interview_context(),
        confirmed=True,
        history=[{"role": "user", "text": "Check the policy."}],
    )
    response = client.post(
        "/api/v1/wizard/package",
        data={"state": state.model_dump_json()},
        files=[("files", ("policy.pdf", b"policy bytes", "application/pdf"))],
    )
    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        'attachment; filename="20261016-223045-interview.zip"'
    )
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == {
            "20261016-223045-interview/inputs/",
            "20261016-223045-interview/inputs/interview_state.json",
            "20261016-223045-interview/outputs/specification.yaml",
            "20261016-223045-interview/outputs/fixtures/",
            "20261016-223045-interview/outputs/fixtures/policy.pdf",
        }
        saved = InterviewState.model_validate_json(
            archive.read("20261016-223045-interview/inputs/interview_state.json")
        )
        assert saved == state
        compiled = compile_specification(saved.specification)
        assert yaml.safe_load(
            archive.read("20261016-223045-interview/outputs/specification.yaml")
        ) == compiled.specification.model_dump(mode="json")
        for task in compiled.specification.tasks:
            for name in task.fixtures:
                assert (
                    archive.read(f"20261016-223045-interview/outputs/fixtures/{name}")
                    == b"policy bytes"
                )


@pytest.mark.parametrize(
    "fields", [{}, {"state": "{}"}, {"state": "{}", "specification": _specification()}]
)
def test_package_requires_one_valid_source(
    client: TestClient, fields: dict[str, str]
) -> None:
    response = client.post("/api/v1/wizard/package", data=fields)
    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"


@pytest.mark.parametrize("transport", [None, *ConnectionTransport])
def test_an_interview_export_writes_the_binding_only_in_run_mode(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    transport: ConnectionTransport | None,
) -> None:
    # a secret in the environment must not reach the archive
    monkeypatch.setenv("APP_KEY", PLANTED_SECRET)
    state = InterviewState(
        specification=research_assistant(),
        context=interview_context(),
        confirmed=True,
    )
    if transport is not None:
        state = set_connection(state, connection(transport))

    response = client.post(
        "/api/v1/wizard/package",
        data={"state": state.model_dump_json()},
        files=[("files", ("policy.pdf", b"policy bytes", "application/pdf"))],
    )

    assert response.status_code == 200
    root = "20261016-223045-interview"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        specification = yaml.safe_load(
            archive.read(f"{root}/outputs/specification.yaml")
        )
        if transport is None:
            assert f"{root}/outputs/target-binding.yaml" not in names
            assert "target_binding" not in specification
            assert specification["runner_factory_ref"] == (
                "metis.engine.simulation.runners.http.HttpRunnerFactory"
            )
        else:
            binding = yaml.safe_load(
                archive.read(f"{root}/outputs/target-binding.yaml")
            )
            assert binding["transport"] == transport.value
            assert specification["target_binding"] == "target-binding.yaml"
            assert specification["runner_factory_ref"].startswith(
                "metis.engine.simulation.runners."
            )
        for name in names:
            assert PLANTED_SECRET.encode() not in archive.read(name)


@pytest.mark.parametrize("transport", list(ConnectionTransport))
def test_a_manual_export_with_a_connection_names_the_binding_and_the_generic_runner(
    client: TestClient, transport: ConnectionTransport
) -> None:
    response = client.post(
        "/api/v1/wizard/package",
        data={
            "specification": _specification(),
            "connection": connection(transport).model_dump_json(),
        },
        files=[("files", ("policy.pdf", b"policy bytes", "application/pdf"))],
    )

    assert response.status_code == 200
    root = "20261016-223045-manual"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        binding = yaml.safe_load(archive.read(f"{root}/outputs/target-binding.yaml"))
        specification = yaml.safe_load(
            archive.read(f"{root}/outputs/specification.yaml")
        )
        assert f"{root}/inputs/interview_state.json" not in archive.namelist()
    assert binding["transport"] == transport.value
    assert specification["target_binding"] == "target-binding.yaml"
    assert specification["runner_factory_ref"].startswith(
        "metis.engine.simulation.runners."
    )


def test_a_manual_export_refuses_a_binding_with_a_credential_in_a_url(
    client: TestClient,
) -> None:
    target = connection().model_dump(mode="json")
    target["binding"]["spec_url"] = (
        f"https://alice:{PLANTED_SECRET}@app.example/openapi.json"
    )

    response = client.post(
        "/api/v1/wizard/package",
        data={"specification": _specification(), "connection": json.dumps(target)},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"
    assert "spec_url" in response.json()["message"]
    assert PLANTED_SECRET not in response.text


def test_an_interview_export_takes_no_separate_connection(client: TestClient) -> None:
    state = InterviewState(
        specification=research_assistant(), context=interview_context(), confirmed=True
    )

    response = client.post(
        "/api/v1/wizard/package",
        data={
            "state": state.model_dump_json(),
            "connection": connection().model_dump_json(),
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"
