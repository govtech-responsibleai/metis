"""The generic HTTP runner's request tool and the rules code enforces on it (#509)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest
import structlog.testing

from metis.core.trials import TrialConfig
from metis.engine.simulation._fixture_artifacts import build_fixture_artifacts
from metis.engine.simulation.artifacts import ArtifactLedger
from metis.engine.simulation.binding import (
    TargetBindingError,
    load_target_binding,
)
from metis.engine.simulation.evidence import Pointer, PointerError
from metis.engine.simulation.runners import http as http_module
from metis.engine.simulation.runners.http import HttpRunner, HttpRunnerFactory
from metis.engine.simulation.runners.rules import ToolRefused
from metis.engine.simulation.runners.spans import Spans
from metis.engine.simulation.transport_log import TransportLog

if TYPE_CHECKING:
    from pathlib import Path

SPEC_URL = "https://app.example/docs/openapi.json"
SPEC = {"openapi": "3.0.0", "servers": [{"url": "/api/v1"}], "paths": {}}
_BINDING = f"schema_version: 1\nidentity: {{name: App}}\ntransport: http\nspec_url: {SPEC_URL}\n"


class Target:
    """A fake app: the spec, a chat endpoint, an upload endpoint and a rate-limited one."""

    def __init__(self) -> None:
        self.seen: list[httpx.Request] = []
        self.limited = 1  # how many 429s /limited answers before it succeeds
        self.retry_after = "2"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        path = request.url.path
        if path == "/docs/openapi.json":
            return httpx.Response(200, json=SPEC)
        if path == "/api/v1/chat":
            return httpx.Response(201, json={"sessionId": "s-1", "reply": "hi"})
        if path == "/api/v1/files":
            return httpx.Response(200, json={"fileId": "f-1"})
        if path == "/api/v1/sessions":
            return httpx.Response(201, json={"session_id": "s-2", "messages": []})
        if path == "/api/v1/limited" and self.limited:
            self.limited -= 1
            return httpx.Response(429, headers={"retry-after": self.retry_after})
        return httpx.Response(200, json={"ok": True})

    def sent(self, path: str) -> list[httpx.Request]:
        return [r for r in self.seen if r.url.path == path]


async def _runner(
    tmp_path: Path, *, extra: str = "", spec_url: str = SPEC_URL
) -> tuple[HttpRunner, Target]:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    text = _BINDING.replace(SPEC_URL, spec_url) + extra
    (inputs / "app.yaml").write_text(text, encoding="utf-8")
    target = Target()
    factory = HttpRunnerFactory(
        load_target_binding(inputs, "app.yaml"), transport=httpx.MockTransport(target)
    )
    await factory.start()
    trial = tmp_path / "trial"
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "fixtures" / "notes.txt").write_text("hello notes", encoding="utf-8")
    held = build_fixture_artifacts(["notes.txt"], tmp_path / "fixtures", tmp_path)
    runner = await factory.create(trial, tmp_path / "fixtures", tmp_path)
    runner.use_ledger(ArtifactLedger(tmp_path, trial, held))
    return runner, target


async def _ready(tmp_path: Path, **kwargs: Any) -> tuple[HttpRunner, Target]:
    runner, target = await _runner(tmp_path, **kwargs)
    await runner.setup(TrialConfig(persona="p", scenario="s"))
    return runner, target


def _log(tmp_path: Path) -> TransportLog:
    return TransportLog.for_trial(tmp_path / "trial")


# --- quoted text ----------------------------------------------------------------------


def test_spans_are_numbered_for_the_agent_and_substituted_exactly() -> None:
    spans = Spans.of("Ask ⟦what is 2 + 2?⟧ then say ⟦thanks⟧")

    assert spans.masked == "Ask {{1}} then say {{2}}"
    assert spans.substitute({"q": ["{{2}} / {{1}}"]}) == {
        "q": ["thanks / what is 2 + 2?"]
    }
    assert spans.sent == {1, 2}


@pytest.mark.asyncio
async def test_a_placeholder_naming_no_span_is_refused(tmp_path: Path) -> None:
    runner, target = await _ready(tmp_path)
    runner.begin_action("Say ⟦hello⟧")

    with pytest.raises(ToolRefused, match=r"\{\{2\}\} names no quoted span"):
        await runner.http_request("POST", "/chat", json={"m": "{{2}}"})

    assert target.sent("/api/v1/chat") == []


@pytest.mark.asyncio
async def test_a_placeholder_is_replaced_by_the_users_words(tmp_path: Path) -> None:
    runner, target = await _ready(tmp_path)
    runner.begin_action("Say ⟦hello there⟧")

    await runner.http_request("POST", "/chat", json={"m": "{{1}}"})

    assert json.loads(target.sent("/api/v1/chat")[0].content) == {"m": "hello there"}


# --- what code refuses ----------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["chat", "/a//b", "/a/../b", "/a/..", "/a?x=1"])
async def test_a_path_that_is_not_absolute_and_plain_is_refused(
    tmp_path: Path, path: str
) -> None:
    runner, target = await _ready(tmp_path)

    with pytest.raises(ToolRefused, match="absolute path"):
        await runner.http_request("GET", path)

    assert len(target.seen) == 1  # only the specification


@pytest.mark.asyncio
async def test_a_forbidden_call_is_refused_before_anything_is_sent(
    tmp_path: Path,
) -> None:
    runner, target = await _ready(
        tmp_path, extra='forbidden_calls: ["DELETE /api/**"]\n'
    )

    with pytest.raises(ToolRefused, match="forbidden"):
        await runner.http_request("DELETE", "/api/users/7")

    assert len(target.seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["Authorization", "cookie", "HOST"])
async def test_the_agent_cannot_set_a_credential_header(
    tmp_path: Path, name: str
) -> None:
    runner, target = await _ready(tmp_path)

    with pytest.raises(ToolRefused, match="cannot set"):
        await runner.http_request("GET", "/things", headers={name: "x"})

    assert len(target.seen) == 1


# --- credentials and headers ----------------------------------------------------------


@pytest.mark.asyncio
async def test_secret_headers_and_the_credential_are_added_and_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_KEY", "SENTINEL-KEY")
    monkeypatch.setenv("APP_TENANT", "SENTINEL-TENANT")
    runner, target = await _ready(
        tmp_path,
        extra="auth: {secret_env: APP_KEY}\n"
        "secret_headers: [{match: 'GET /things', header: X-Tenant, env: APP_TENANT}]\n",
    )

    await runner.http_request("GET", "/things", headers={"X-Extra": "1"})

    wire = target.sent("/api/v1/things")[0].headers
    assert wire["authorization"] == "Bearer SENTINEL-KEY"
    assert wire["x-tenant"] == "SENTINEL-TENANT"
    assert wire["x-extra"] == "1"
    logged = _log(tmp_path).get(runner.results[-1])
    request = _log(tmp_path).get(logged.pairs_with or "")
    assert request.headers["authorization"] == request.headers["x-tenant"] == "***"
    assert "SENTINEL" not in _log(tmp_path).path.read_text(encoding="utf-8")


@pytest.mark.asyncio
@pytest.mark.parametrize("model_set", [True, False])
async def test_model_headers_are_sent_only_when_their_variables_are_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, model_set: bool
) -> None:
    for var in ("GATEWAY_AGENT_MODEL", "GATEWAY_TOOL_MODEL"):
        monkeypatch.delenv(var, raising=False)
    if model_set:
        monkeypatch.setenv("GATEWAY_AGENT_MODEL", "agent-m")
        monkeypatch.setenv("GATEWAY_TOOL_MODEL", "tool-m")
    runner, target = await _ready(
        tmp_path,
        extra="secret_headers:\n"
        "  - {match: 'POST /chat', header: X-Gateway-Agent-Model, env: GATEWAY_AGENT_MODEL}\n"
        "  - {match: 'POST /chat', header: X-Gateway-Tool-Model, env: GATEWAY_TOOL_MODEL}\n",
    )
    runner.begin_action("Say ⟦hi⟧")

    await runner.http_request("POST", "/chat", json={"m": "{{1}}"})

    headers = target.sent("/api/v1/chat")[0].headers
    assert headers.get("x-gateway-agent-model") == ("agent-m" if model_set else None)
    assert headers.get("x-gateway-tool-model") == ("tool-m" if model_set else None)


# --- the specification ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_server_is_resolved_against_the_spec_url(tmp_path: Path) -> None:
    runner, target = await _ready(tmp_path)

    await runner.http_request("GET", "/things", query={"page": "2"})

    assert str(target.seen[-1].url) == "https://app.example/api/v1/things?page=2"


@pytest.mark.asyncio
async def test_the_spec_is_fetched_once_and_is_not_an_answer(tmp_path: Path) -> None:
    runner, target = await _ready(tmp_path)

    await runner.http_request("GET", "/a")
    await runner.http_request("GET", "/b")

    assert len(target.sent("/docs/openapi.json")) == 1
    assert runner.spec_entry not in runner.results
    assert _log(tmp_path).get(runner.spec_entry).role == "result"


@pytest.mark.asyncio
async def test_a_spec_url_without_a_host_is_refused_when_fetched(
    tmp_path: Path,
) -> None:
    runner, _ = await _runner(tmp_path, spec_url="https:openapi.json")

    with pytest.raises(TargetBindingError, match="no host"):
        await runner.setup(TrialConfig(persona="p", scenario="s"))


# --- 429 ------------------------------------------------------------------------------


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    waited: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waited.append(seconds)

    monkeypatch.setattr(http_module, "_sleep", fake_sleep)
    return waited


@pytest.mark.asyncio
async def test_a_429_is_resent_after_its_retry_after(
    tmp_path: Path, sleeps: list[float]
) -> None:
    runner, target = await _ready(tmp_path)

    result = await runner.http_request("GET", "/limited")

    assert result["status"] == 200
    assert sleeps == [2.0]
    assert len(target.sent("/api/v1/limited")) == 2


@pytest.mark.asyncio
async def test_a_429_is_resent_at_most_three_times(
    tmp_path: Path, sleeps: list[float]
) -> None:
    runner, target = await _ready(tmp_path)
    target.limited = 10

    result = await runner.http_request("GET", "/limited")

    assert result["status"] == 429
    assert len(target.sent("/api/v1/limited")) == 4


@pytest.mark.asyncio
async def test_a_429_is_not_resent_beyond_the_trials_remaining_wait(
    tmp_path: Path, sleeps: list[float]
) -> None:
    runner, target = await _ready(tmp_path)
    target.retry_after = "99999"

    result = await runner.http_request("GET", "/limited")

    assert result["status"] == 429
    assert sleeps == []
    assert len(target.sent("/api/v1/limited")) == 1


# --- submissions ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_submission_with_nothing_quoted_is_refused(tmp_path: Path) -> None:
    runner, target = await _ready(tmp_path)
    runner.begin_action("Open the settings page")

    with pytest.raises(ToolRefused, match="quoted nothing"):
        await runner.http_request("POST", "/chat", json={"m": "hello"})

    assert target.sent("/api/v1/chat") == []


@pytest.mark.asyncio
async def test_a_second_submission_is_refused_while_one_is_open(tmp_path: Path) -> None:
    runner, target = await _ready(tmp_path)
    runner.begin_action("Say ⟦hi⟧")
    await runner.http_request("POST", "/chat", json={"m": "{{1}}"})
    open_submission = runner.open_submission
    runner.begin_action("Say ⟦again⟧")

    with pytest.raises(ToolRefused, match="still open"):
        await runner.http_request("POST", "/chat", json={"m": "{{1}}"})

    assert open_submission is not None
    assert open_submission.turn == 1
    assert runner.answers == [open_submission.response]
    assert len(target.sent("/api/v1/chat")) == 1


@pytest.mark.asyncio
async def test_the_bindings_submissions_replace_the_default_rule(
    tmp_path: Path,
) -> None:
    runner, _ = await _ready(tmp_path, extra="submissions: ['POST /search']\n")
    runner.begin_action("Look at ⟦cats⟧")

    await runner.http_request("POST", "/chat", json={"m": "{{1}}"})
    assert runner.open_submission is None

    await runner.http_request("POST", "/search", json={"q": "{{1}}"})
    assert runner.open_submission is not None


@pytest.mark.asyncio
async def test_the_session_id_comes_from_a_submissions_reply(tmp_path: Path) -> None:
    runner, _ = await _ready(tmp_path)
    runner.begin_action("Say ⟦hi⟧")
    chat = await runner.http_request("POST", "/chat", json={"m": "{{1}}"})

    runner.record_session_id(Pointer(chat["response_entry"], "$.sessionId"))
    assert runner.session_id == "s-1"


@pytest.mark.asyncio
async def test_the_session_id_may_come_from_the_call_that_opens_the_session(
    tmp_path: Path,
) -> None:
    """A two-step target gives the ID before any message is sent (#543)."""
    runner, _ = await _ready(
        tmp_path, extra="submissions: ['POST /api/v1/sessions/*/messages']\n"
    )
    runner.begin_action("Say ⟦hi⟧")
    opened = await runner.http_request("POST", "/sessions", json={})

    assert runner.open_submission is None
    runner.record_session_id(Pointer(opened["response_entry"], "$.session_id"))
    assert runner.session_id == "s-2"

    runner.begin_action("Say ⟦more⟧")
    with pytest.raises(PointerError, match="not one of the entries"):
        runner.record_session_id(Pointer(opened["response_entry"], "$.session_id"))


@pytest.mark.asyncio
async def test_a_session_wildcard_submits_only_the_message_call(tmp_path: Path) -> None:
    runner, _ = await _ready(
        tmp_path, extra="submissions: ['POST /sessions/*/messages']\n"
    )
    runner.begin_action("Say ⟦hi⟧")

    await runner.http_request("POST", "/sessions", json={})
    assert runner.open_submission is None

    await runner.http_request("POST", "/sessions/s-2/messages", json={"m": "{{1}}"})
    assert runner.open_submission is not None


@pytest.mark.asyncio
async def test_recording_the_session_id_is_logged(tmp_path: Path) -> None:
    runner, _ = await _ready(tmp_path)
    runner.begin_action("Say ⟦hi⟧")
    chat = await runner.http_request("POST", "/chat", json={"m": "{{1}}"})

    with structlog.testing.capture_logs() as logs:
        runner.record_session_id(Pointer(chat["response_entry"], "$.sessionId"))

    found = [e for e in logs if e["event"] == "session_id_found"]
    assert len(found) == 1
    assert found[0]["session_id"] == "s-1"
    assert found[0]["entry"] == chat["response_entry"]
    assert found[0]["log_level"] == "info"


# --- the factory ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_honours_tls_verify_and_close_closes_the_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made: list[dict[str, Any]] = []

    class Spy(httpx.AsyncHTTPTransport):
        def __init__(self, **kwargs: Any) -> None:
            made.append(kwargs)
            super().__init__(**kwargs)

        async def aclose(self) -> None:
            made.append({"closed": True})
            await super().aclose()

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", Spy)
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "app.yaml").write_text(_BINDING + "tls_verify: false\n", encoding="utf-8")
    factory = HttpRunnerFactory(load_target_binding(inputs, "app.yaml"))

    await factory.start()
    await factory.close()

    assert made == [{"verify": False}, {"closed": True}]
