"""The simulation's transport log: every request and response, retries included (#477)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from metis.core.target_binding import TargetBinding
from metis.engine.simulation.experiment import TrialPlanItem, _worker, trial_folder_name
from metis.engine.simulation.runner import Runner
from metis.engine.simulation.transport_log import (
    INLINE_LIMIT,
    ArtifactRef,
    FileBody,
    LoggingTransport,
    TransportLog,
)
from metis.engine.simulation.types import Persona, Scenario

_STAMP = datetime(2026, 10, 21, 6, 15, 0, tzinfo=UTC)
_CANARY = "canary-s3cret-7f3a"


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def _client(
    tmp_path: Path, handler: Any, secret_headers: tuple[str, ...] = ()
) -> httpx.AsyncClient:
    transport = LoggingTransport(
        httpx.MockTransport(handler),
        TransportLog.for_trial(tmp_path),
        secret_headers=secret_headers,
    )
    return httpx.AsyncClient(transport=transport, base_url="https://app.example")


def _log_rows(tmp_path: Path) -> list[dict[str, Any]]:
    return _rows(tmp_path / "evidence" / "log.jsonl")


@pytest.mark.asyncio
async def test_a_response_pairs_with_the_request_it_answers(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"session": "s-1"})

    async with _client(tmp_path, handler) as client:
        await client.post("/api/v1/chat?draft=1", json={"message": "hello"})

    request, response = _log_rows(tmp_path)
    assert (request["id"], request["kind"], request["role"]) == (
        "e1",
        "request",
        "action",
    )
    assert request["pairs_with"] is None
    assert (response["id"], response["kind"], response["role"]) == (
        "e2",
        "response",
        "result",
    )
    assert response["pairs_with"] == "e1"
    # The summary is written by code and leaves the query out, which may hold secrets.
    assert request["summary"] == "POST /api/v1/chat"
    assert response["summary"] == "POST /api/v1/chat -> 201"
    assert json.loads(request["body"]["text"]) == {"message": "hello"}
    assert json.loads(response["body"]["text"]) == {"session": "s-1"}
    assert datetime.fromisoformat(response["at"]) >= datetime.fromisoformat(
        request["at"]
    )


@pytest.mark.asyncio
async def test_every_attempt_is_its_own_pair(tmp_path: Path) -> None:
    statuses = iter([503, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(next(statuses))

    async with _client(tmp_path, handler) as client:
        await client.get("/api/v1/sessions")
        await client.get("/api/v1/sessions")

    rows = _log_rows(tmp_path)
    assert [(r["id"], r["pairs_with"]) for r in rows] == [
        ("e1", None),
        ("e2", "e1"),
        ("e3", None),
        ("e4", "e3"),
    ]
    assert [r["summary"] for r in rows[1::2]] == [
        "GET /api/v1/sessions -> 503",
        "GET /api/v1/sessions -> 200",
    ]


@pytest.mark.asyncio
async def test_a_failed_attempt_still_gets_a_result(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async with _client(tmp_path, handler) as client:
        with pytest.raises(httpx.ConnectError):
            await client.get("/api/v1/sessions")

    request, result = _log_rows(tmp_path)
    assert result["pairs_with"] == request["id"]
    assert result["role"] == "result"
    assert result["summary"] == "GET /api/v1/sessions -> ConnectError"
    # Not the exception's own message: a transport can echo request content
    # (including a secret header value) into str(exc). See
    # test_a_malformed_header_value_does_not_leak_into_the_log.
    assert result["body"]["text"] == (
        "ConnectError: request failed before a response was received"
    )


@pytest.mark.asyncio
async def test_a_malformed_header_value_does_not_leak_into_the_log(
    tmp_path: Path,
) -> None:
    """h11 echoes a header's raw bytes into LocalProtocolError's message when the
    value itself is malformed (e.g. a secret pasted with a trailing CRLF). That
    message must never reach the log, even though it never passes through our own
    header-redaction step."""

    class _LeakyInner(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            # Mirrors h11.Connection.send's own wording for an illegal header value,
            # https://github.com/python-hyper/h11/blob/master/h11/_writers.py
            value = request.headers.raw[-1][1]
            raise httpx.LocalProtocolError(f"Illegal header value {value!r}")

    log = TransportLog.for_trial(tmp_path)
    transport = LoggingTransport(_LeakyInner(), log, secret_headers=("x-gateway-key",))
    async with httpx.AsyncClient(
        transport=transport, base_url="https://app.example"
    ) as client:
        with pytest.raises(httpx.LocalProtocolError):
            await client.get(
                "/api/v1/sessions",
                headers={"x-gateway-key": f"{_CANARY}\r\nEvil: true"},
            )

    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert files
    assert all(_CANARY.encode() not in p.read_bytes() for p in files)
    request, result = _log_rows(tmp_path)
    assert result["pairs_with"] == request["id"]
    assert result["summary"] == "GET /api/v1/sessions -> LocalProtocolError"


@pytest.mark.asyncio
async def test_the_caller_still_reads_the_response(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"payload")

    async with (
        _client(tmp_path, handler) as client,
        client.stream("GET", "/download") as response,
    ):
        body = b"".join([chunk async for chunk in response.aiter_bytes()])

    assert body == b"payload"


@pytest.mark.asyncio
async def test_a_secret_appears_in_no_written_file(tmp_path: Path) -> None:
    """Authorization and every named secret header are redacted, in either direction."""
    binding = TargetBinding.model_validate(
        {
            "schema_version": 1,
            "identity": {"name": "app"},
            "transport": "http",
            "spec_url": "https://app.example/openapi.json",
            "secret_headers": [
                {"match": "POST /api/**", "header": "X-Gateway-Key", "env": "KEY"}
            ],
        }
    )
    names = tuple(h.header for h in binding.secret_headers)
    assert names == ("X-Gateway-Key",)

    def handler(request: httpx.Request) -> httpx.Response:
        # A server that echoes the credential back must not get it into the log.
        return httpx.Response(
            200, headers={"x-gateway-key": _CANARY}, json={"ok": True}
        )

    async with _client(tmp_path, handler, names) as client:
        await client.post(
            "/api/v1/chat",
            json={"message": "hi"},
            headers={
                "Authorization": f"Bearer {_CANARY}",
                "x-gateway-key": _CANARY,
                "Accept": "application/json",
            },
        )
    TransportLog.for_trial(tmp_path).supersede(now=_STAMP)
    async with _client(tmp_path, handler, names) as client:
        await client.post(
            "/api/v1/chat",
            content=b"x" * (INLINE_LIMIT + 1),
            headers={"Authorization": _CANARY},
        )

    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert len(files) == 3  # both attempts' logs and the spilled body
    assert all(_CANARY.encode() not in p.read_bytes() for p in files)
    superseded = _rows(tmp_path / "evidence" / "log-superseded-20261021T061500Z.jsonl")
    request, response = superseded
    assert request["headers"]["authorization"] == "***"
    assert request["headers"]["x-gateway-key"] == "***"
    assert request["headers"]["accept"] == "application/json"
    assert response["headers"]["x-gateway-key"] == "***"


def test_a_body_of_exactly_the_limit_stays_inline(tmp_path: Path) -> None:
    log = TransportLog.for_trial(tmp_path)
    log.append("request", "POST /a", b"a" * INLINE_LIMIT)

    [row] = _log_rows(tmp_path)
    assert row["body"]["type"] == "inline"
    assert not list((tmp_path / "evidence").glob("*.bin"))


def test_a_larger_body_goes_to_its_own_file(tmp_path: Path) -> None:
    log = TransportLog.for_trial(tmp_path)
    big = b"a" * (INLINE_LIMIT + 1)
    entry_id = log.append("request", "POST /a", big)

    [row] = _log_rows(tmp_path)
    assert row["body"] == {"type": "file", "path": f"{entry_id}.bin"}
    assert (tmp_path / "evidence" / f"{entry_id}.bin").read_bytes() == big


def test_a_body_that_is_not_text_is_stored_as_base64(tmp_path: Path) -> None:
    png = b"\x89PNG\xff"
    TransportLog.for_trial(tmp_path).append("request", "POST /a", png)

    [row] = _log_rows(tmp_path)
    assert row["body"]["type"] == "inline"
    assert row["body"]["encoding"] == "base64"
    assert base64.b64decode(row["body"]["text"]) == png


def test_a_downloaded_artifact_is_a_reference_not_a_copy(tmp_path: Path) -> None:
    """A stand-in for the artifact write path (#479): the file and its digest."""
    artifact = tmp_path / "artifacts" / "report.pdf"
    artifact.parent.mkdir()
    artifact.write_bytes(b"%PDF-" + b"x" * (INLINE_LIMIT * 2))
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    log = TransportLog.for_trial(tmp_path)
    request_id = log.append("request", "GET /files/f1/content", b"")

    log.append(
        "response",
        "GET /files/f1/content -> 200",
        ArtifactRef(path="artifacts/report.pdf", sha256=digest),
        pairs_with=request_id,
    )

    _, row = _log_rows(tmp_path)
    assert row["body"] == {
        "type": "artifact",
        "path": "artifacts/report.pdf",
        "sha256": digest,
    }
    assert not list((tmp_path / "evidence").glob("*.bin"))
    assert "%PDF" not in (tmp_path / "evidence" / "log.jsonl").read_text()


def test_supersede_without_a_log_does_nothing(tmp_path: Path) -> None:
    assert TransportLog.for_trial(tmp_path).supersede(now=_STAMP) is None


def test_supersede_keeps_an_earlier_attempts_log_and_its_bodies(tmp_path: Path) -> None:
    first = TransportLog.for_trial(tmp_path)
    big = b"a" * (INLINE_LIMIT + 1)
    first.append("request", "POST /a", big)

    dest = first.supersede(now=_STAMP)

    evidence = tmp_path / "evidence"
    assert dest == evidence / "log-superseded-20261021T061500Z.jsonl"
    assert not first.path.exists()
    # The moved log still resolves its body, now under the superseded folder.
    [row] = _rows(dest)
    assert (evidence / row["body"]["path"]).read_bytes() == big
    # The next attempt starts again at e1, without clashing with the kept e1.bin.
    second = TransportLog.for_trial(tmp_path)
    assert second.append("request", "POST /a", big) == "e1"
    assert (evidence / "e1.bin").read_bytes() == big


def test_supersede_twice_in_one_second_keeps_both(tmp_path: Path) -> None:
    for _ in range(2):
        log = TransportLog.for_trial(tmp_path)
        log.append("request", "GET /a", b"")
        log.supersede(now=_STAMP)

    names = sorted(p.name for p in (tmp_path / "evidence").iterdir())
    assert names == [
        "log-superseded-20261021T061500Z-2.jsonl",
        "log-superseded-20261021T061500Z.jsonl",
    ]


def test_appending_to_an_existing_log_continues_its_ids(tmp_path: Path) -> None:
    TransportLog.for_trial(tmp_path).append("request", "GET /a", b"")

    assert TransportLog.for_trial(tmp_path).append("request", "GET /b", b"") == "e2"


def test_a_response_must_answer_an_earlier_request(tmp_path: Path) -> None:
    log = TransportLog.for_trial(tmp_path)

    with pytest.raises(ValueError, match="e9"):
        log.append("response", "GET /a -> 200", b"", pairs_with="e9")
    assert not log.path.exists()


def test_an_artifact_path_cannot_leave_the_trial() -> None:
    for path in ("/etc/passwd", "../outside.bin", "artifacts/../../x"):
        with pytest.raises(ValueError, match="inside the trial"):
            ArtifactRef(path=path, sha256="0" * 64)


@pytest.mark.asyncio
async def test_a_retried_trial_keeps_the_earlier_attempts_log(tmp_path: Path) -> None:
    """The worker moves an earlier attempt's log aside before the runner is built."""
    scenario = Scenario(id="s", description="d", persona_refs=["p"], max_turns=1)
    persona = Persona(id="p", name="p", description="a user")
    run_dir = tmp_path / "outputs" / "trials" / trial_folder_name(scenario, persona, 1)
    TransportLog.for_trial(run_dir).append("request", "GET /earlier", b"")

    class _Factory:
        async def create(self, *_args: object) -> Runner:
            raise RuntimeError("stop after the log is moved")

    with pytest.raises(RuntimeError, match="stop after the log is moved"):
        await _worker(
            worker_id=0,
            runner_factory=_Factory(),  # type: ignore[arg-type]
            worker_trials=[TrialPlanItem(scenario, persona, 1)],
            experiment_root=tmp_path,
            fixtures_dir=tmp_path / "fixtures",
            fixture_content_descriptions={},
            console_lock=asyncio.Lock(),
            started_scenarios=set(),
            trial_max_retries=0,
            trial_retry_delay_seconds=0,
        )

    evidence = run_dir / "evidence"
    assert not (evidence / "log.jsonl").exists()
    [kept] = evidence.glob("log-superseded-*.jsonl")
    assert _rows(kept)[0]["summary"] == "GET /earlier"


def _artifact(trial: Path, content: bytes) -> ArtifactRef:
    (trial / "artifacts").mkdir(exist_ok=True)
    (trial / "artifacts" / "report.pdf").write_bytes(content)
    return ArtifactRef(
        path="artifacts/report.pdf", sha256=hashlib.sha256(content).hexdigest()
    )


def test_get_returns_the_entry_with_that_id(tmp_path: Path) -> None:
    log = TransportLog.for_trial(tmp_path)
    log.append("request", "GET /a", b"")
    second = log.append("request", "GET /b", b"")

    assert log.get(second).summary == "GET /b"


def test_get_names_an_unknown_id(tmp_path: Path) -> None:
    log = TransportLog.for_trial(tmp_path)
    log.append("request", "GET /a", b"")

    with pytest.raises(ValueError, match="no entry e9"):
        log.get("e9")


def test_body_bytes_reads_utf8_and_base64_inline_bodies(tmp_path: Path) -> None:
    log = TransportLog.for_trial(tmp_path)
    text_id = log.append("request", "POST /a", "héllo".encode())
    binary_id = log.append("request", "POST /b", b"\xff\x00")

    assert log.body_bytes(log.get(text_id)) == "héllo".encode()
    assert log.body_bytes(log.get(binary_id)) == b"\xff\x00"


def test_body_bytes_reads_a_body_stored_in_a_file(tmp_path: Path) -> None:
    log = TransportLog.for_trial(tmp_path)
    big = b"x" * (INLINE_LIMIT + 1)
    entry_id = log.append("response", "GET /big", big)

    assert log.body_bytes(log.get(entry_id)) == big


def test_body_bytes_reads_an_artifact_from_the_trial_folder(tmp_path: Path) -> None:
    log = TransportLog.for_trial(tmp_path)
    entry_id = log.append("response", "GET /f", _artifact(tmp_path, b"%PDF"))

    assert log.body_bytes(log.get(entry_id)) == b"%PDF"


def test_body_bytes_refuses_an_artifact_that_changed_since_it_was_logged(
    tmp_path: Path,
) -> None:
    log = TransportLog.for_trial(tmp_path)
    entry_id = log.append("response", "GET /f", _artifact(tmp_path, b"%PDF"))
    (tmp_path / "artifacts" / "report.pdf").write_bytes(b"tampered")

    with pytest.raises(ValueError, match="sha256"):
        log.body_bytes(log.get(entry_id))


def test_body_bytes_refuses_a_file_body_that_leaves_the_evidence_folder(
    tmp_path: Path,
) -> None:
    log = TransportLog.for_trial(tmp_path)
    entry_id = log.append("response", "GET /big", b"x" * (INLINE_LIMIT + 1))
    entry = log.get(entry_id).model_copy(update={"body": FileBody(path="../secret")})

    with pytest.raises(ValueError, match="outside"):
        log.body_bytes(entry)
