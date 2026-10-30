"""The runner agent's tool schemas and dispatcher (#481)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest
import structlog.testing

from metis.core.trials import TrialConfig
from metis.engine.simulation.artifacts import ArtifactLedger
from metis.engine.simulation.binding import load_target_binding
from metis.engine.simulation.runners.http import HttpRunner, HttpRunnerFactory
from metis.engine.simulation.runners.tools import (
    SHARED_HANDLERS,
    TOOLS,
    ActionState,
    run_tool,
)
from metis.engine.simulation.user_agent.agent import render_observation

if TYPE_CHECKING:
    from pathlib import Path

SPEC_URL = "https://app.example/openapi.json"
_BINDING = (
    f"schema_version: 1\nidentity: {{name: App}}\ntransport: http\nspec_url: {SPEC_URL}\n"
    "forbidden_calls: ['DELETE /**']\n"
)
API = "/api/v1"


class Target:
    """A fake app: a chat that lists a file, a status, a download and a broken path."""

    def __init__(self) -> None:
        self.seen: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        path = request.url.path
        if path == "/openapi.json":
            return httpx.Response(200, json={"servers": [{"url": API}]})
        if path == f"{API}/chat":
            return httpx.Response(
                201,
                json={
                    "sessionId": "s-1",
                    "reply": "hi",
                    "files": [{"id": "f1", "name": "a.txt"}],
                },
            )
        if path == f"{API}/accepted":
            return httpx.Response(202, json={"reply": "working on it"})
        if path == f"{API}/rejects":
            return httpx.Response(
                422,
                json={"error": {"code": "invalid_request", "message": "bad session"}},
            )
        if path == f"{API}/rejects-long":
            return httpx.Response(500, text="x" * 3000)
        if path == f"{API}/gone":
            return httpx.Response(404, json={"detail": "no such session"})
        if path == f"{API}/long":
            return httpx.Response(
                200, json={"filler": "x" * 5000, "result": {"message": "the tail"}}
            )
        if path == f"{API}/post-only" and request.method != "POST":
            return httpx.Response(405, json={"detail": "Method Not Allowed"})
        if path == f"{API}/status":
            return httpx.Response(200, json={"state": "done"})
        if path == f"{API}/names":
            return httpx.Response(200, text="a.txt\nb.txt")
        if path == f"{API}/dl/f1":
            return httpx.Response(
                200, content=b"hello", headers={"content-type": "text/plain"}
            )
        if path == f"{API}/boom":
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json={})

    def sent(self, path: str) -> list[httpx.Request]:
        return [r for r in self.seen if r.url.path == f"{API}{path}"]


async def _ready(tmp_path: Path) -> tuple[HttpRunner, Target, ActionState]:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "app.yaml").write_text(_BINDING, encoding="utf-8")
    target = Target()
    factory = HttpRunnerFactory(
        load_target_binding(inputs, "app.yaml"), transport=httpx.MockTransport(target)
    )
    await factory.start()
    trial = tmp_path / "trial"
    runner = await factory.create(trial, tmp_path, tmp_path)
    runner.use_ledger(ArtifactLedger(tmp_path, trial))
    await runner.setup(TrialConfig(persona="p", scenario="s"))
    runner.begin_action("Say ⟦hello⟧")
    return runner, target, ActionState(first_result=len(runner.results))


async def _call(
    runner: HttpRunner, state: ActionState, name: str, args: Any
) -> dict[str, Any]:
    return await run_tool(runner, state, name, json.dumps(args))


async def _chat(runner: HttpRunner, state: ActionState) -> dict[str, Any]:
    return await _call(
        runner,
        state,
        "http_request",
        {"method": "POST", "path": "/chat", "json": {"text": "{{1}}"}},
    )


def test_the_tools_are_the_seven_the_agent_may_call() -> None:
    names = {tool["function"]["name"] for tool in TOOLS}

    assert names == {
        "operation",
        "http_request",
        "poll_until",
        "fetch_files",
        "session_id_from",
        "note",
        "report",
    }
    assert all(tool["function"]["parameters"]["type"] == "object" for tool in TOOLS)


@pytest.mark.asyncio
async def test_http_request_sends_the_users_words_and_returns_the_log_entries(
    tmp_path: Path,
) -> None:
    runner, target, state = await _ready(tmp_path)

    result = await _chat(runner, state)

    assert result["status"] == 201
    assert result["response_entry"] in runner.results
    assert json.loads(target.sent("/chat")[0].content) == {"text": "hello"}


@pytest.mark.asyncio
async def test_a_refused_call_goes_back_as_an_error_and_sends_nothing(
    tmp_path: Path,
) -> None:
    runner, target, state = await _ready(tmp_path)

    result = await _call(
        runner, state, "http_request", {"method": "DELETE", "path": "/chat"}
    )

    assert result["error"].startswith("refused, nothing was sent: ")
    assert "forbidden" in result["error"]
    assert target.sent("/chat") == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "raw"),
    [
        ("http_request", "{not json"),
        ("http_request", "[1, 2]"),
        ("no_such_tool", "{}"),
        ("http_request", '{"method": "GET"}'),
        ("report", '{"outcome": "done"}'),
    ],
)
async def test_bad_arguments_and_unknown_tools_are_errors_not_exceptions(
    tmp_path: Path, name: str, raw: str
) -> None:
    runner, target, state = await _ready(tmp_path)

    result = await run_tool(runner, state, name, raw)

    assert result["error"].startswith("refused, nothing was sent: ")
    assert target.sent("/chat") == []


@pytest.mark.asyncio
async def test_poll_until_takes_in_as_the_done_values(tmp_path: Path) -> None:
    runner, _, state = await _ready(tmp_path)
    await _chat(runner, state)

    result = await _call(
        runner,
        state,
        "poll_until",
        {"path": "/status", "at": "$.state", "in": ["done"]},
    )

    assert result["condition"] == "holds"
    assert runner.open_submission is None


@pytest.mark.asyncio
async def test_poll_until_without_a_condition_is_refused(tmp_path: Path) -> None:
    runner, _, state = await _ready(tmp_path)

    result = await _call(
        runner, state, "poll_until", {"path": "/status", "at": "$.state"}
    )

    assert "exactly one of" in result["error"]


@pytest.mark.asyncio
async def test_fetch_files_downloads_what_a_listing_names(tmp_path: Path) -> None:
    runner, _, state = await _ready(tmp_path)
    reply = await _chat(runner, state)

    result = await _call(
        runner,
        state,
        "fetch_files",
        {
            "listing": {"entry": reply["response_entry"], "at": "$.files"},
            "id_key": "id",
            "name_key": "name",
            "download_path": "/dl/{id}",
        },
    )

    assert [f["outcome"] for f in result["files"]] == ["received"]
    assert [a.name for a in runner.ledger.artifacts()] == ["a.txt"]


@pytest.mark.asyncio
async def test_session_id_from_records_the_id_from_a_submissions_reply(
    tmp_path: Path,
) -> None:
    runner, _, state = await _ready(tmp_path)
    reply = await _chat(runner, state)
    pointer = {"entry": reply["response_entry"], "at": "$.sessionId"}

    assert "error" not in await _call(runner, state, "session_id_from", pointer)

    assert runner.session_id == "s-1"


@pytest.mark.asyncio
async def test_session_id_from_refuses_an_earlier_actions_non_submission_result(
    tmp_path: Path,
) -> None:
    runner, _, state = await _ready(tmp_path)
    await _chat(runner, state)
    status = await _call(
        runner, state, "http_request", {"method": "GET", "path": "/status"}
    )
    runner.begin_action("Say ⟦more⟧")

    result = await _call(
        runner,
        state,
        "session_id_from",
        {"entry": status["response_entry"], "at": "$.state"},
    )

    assert result["error"].startswith("refused, nothing was sent: ")
    assert runner.session_id is None


@pytest.mark.asyncio
async def test_note_keeps_what_the_agent_learned(tmp_path: Path) -> None:
    runner, _, state = await _ready(tmp_path)

    await _call(runner, state, "note", {"text": "the target wants JSON"})

    assert runner.notes == ["the target wants JSON"]


@pytest.mark.asyncio
async def test_report_resolves_the_reply_and_keeps_the_reading_apart(
    tmp_path: Path,
) -> None:
    runner, _, state = await _ready(tmp_path)
    reply = await _chat(runner, state)

    result = await _call(
        runner,
        state,
        "report",
        {
            "outcome": "done",
            "why": "sent it",
            "next_options": "ask more",
            "submission": "answered",
            "reply_from": {"entry": reply["response_entry"], "at": "$.reply"},
            "promised": [{"entry": reply["response_entry"], "at": "$.files[0].name"}],
        },
    )

    assert "error" not in result
    assert state.report is not None
    assert state.report.reply == "hi"
    assert state.report.promised == ["a.txt"]
    assert (state.report.reading.outcome, state.report.reading.why) == (
        "done",
        "sent it",
    )
    assert state.report.reading.next_options == "ask more"


async def _submit(
    runner: HttpRunner, state: ActionState, path: str = "/chat"
) -> dict[str, Any]:
    return await _call(
        runner,
        state,
        "http_request",
        {"method": "POST", "path": path, "json": {"text": "{{1}}"}},
    )


@pytest.mark.asyncio
async def test_a_reply_cited_from_the_submissions_own_200_settles_it(
    tmp_path: Path,
) -> None:
    runner, _, state = await _ready(tmp_path)
    reply = await _chat(runner, state)
    assert runner.open_submission is not None

    result = await _call(
        runner,
        state,
        "report",
        {
            "outcome": "done",
            "why": "the answer came back in the POST",
            "submission": "answered",
            "reply_from": {"entry": reply["response_entry"], "at": "$.reply"},
        },
    )

    assert "error" not in result
    assert runner.open_submission is None
    observation = runner._observation(state, None)
    assert observation.observed
    assert observation.reply == "hi"
    assert observation.notice is None
    assert not observation.submission_unresolved


@pytest.mark.asyncio
async def test_a_202_stays_open_even_when_the_report_cites_it(tmp_path: Path) -> None:
    runner, _, state = await _ready(tmp_path)
    reply = await _submit(runner, state, "/accepted")

    await _call(
        runner,
        state,
        "report",
        {
            "outcome": "partial",
            "why": "accepted, the answer comes later",
            "submission": "pending",
            "reply_from": {"entry": reply["response_entry"], "at": "$.reply"},
        },
    )

    assert runner.open_submission is not None
    assert not runner._observation(state, None).observed


@pytest.mark.asyncio
async def test_citing_a_later_call_does_not_settle_the_submission(
    tmp_path: Path,
) -> None:
    runner, _, state = await _ready(tmp_path)
    await _chat(runner, state)
    status = await _call(
        runner,
        state,
        "http_request",
        {"method": "GET", "path": "/status"},
    )

    await _call(
        runner,
        state,
        "report",
        {
            "outcome": "done",
            "why": "read the session",
            "submission": "pending",
            "reply_from": {"entry": status["response_entry"], "at": "$.state"},
        },
    )

    assert runner.open_submission is not None


@pytest.mark.asyncio
async def test_a_report_without_a_reply_leaves_the_submission_open(
    tmp_path: Path,
) -> None:
    runner, _, state = await _ready(tmp_path)
    await _chat(runner, state)

    await _call(
        runner,
        state,
        "report",
        {"outcome": "unknown", "why": "no idea", "submission": "pending"},
    )

    assert runner.open_submission is not None


@pytest.mark.asyncio
async def test_a_wrong_reply_path_does_not_keep_an_answered_submission_open(
    tmp_path: Path,
) -> None:
    """The target answered inside the 200; a bad citation costs the reply only."""
    runner, _, state = await _ready(tmp_path)
    reply = await _chat(runner, state)
    wrong = {
        "outcome": "done",
        "why": "the answer came back in the POST",
        "submission": "answered",
        "reply_from": {"entry": reply["response_entry"], "at": "$.body.reply"},
    }

    refused = await _call(runner, state, "report", wrong)

    assert "error" in refused
    assert runner.open_submission is None
    right = {**wrong, "reply_from": {**wrong["reply_from"], "at": "$.reply"}}
    assert "error" not in await _call(runner, state, "report", right)
    observation = runner._observation(state, None)
    assert observation.observed
    assert observation.reply == "hi"
    assert not observation.submission_unresolved


@pytest.mark.asyncio
async def test_an_answered_submission_with_no_cited_reply_says_so(
    tmp_path: Path,
) -> None:
    runner, _, state = await _ready(tmp_path)
    await _chat(runner, state)

    await _call(
        runner,
        state,
        "report",
        {"outcome": "done", "why": "answered", "submission": "answered"},
    )

    observation = runner._observation(state, None)
    assert observation.observed
    assert observation.reply is None
    assert observation.notice is not None
    assert "no reply was recorded" in observation.notice


@pytest.mark.asyncio
async def test_a_report_must_say_whether_an_open_submission_is_answered(
    tmp_path: Path,
) -> None:
    runner, _, state = await _ready(tmp_path)
    await _chat(runner, state)

    result = await _call(runner, state, "report", {"outcome": "done", "why": "sent"})

    assert "submission" in result["error"]
    assert state.report is None
    assert runner.open_submission is not None


@pytest.mark.asyncio
async def test_a_200_the_agent_calls_pending_stays_open(tmp_path: Path) -> None:
    runner, _, state = await _ready(tmp_path)
    await _chat(runner, state)

    await _call(
        runner,
        state,
        "report",
        {"outcome": "partial", "why": "queued", "submission": "pending"},
    )

    assert runner.open_submission is not None


@pytest.mark.asyncio
async def test_a_202_cannot_be_called_answered(tmp_path: Path) -> None:
    runner, _, state = await _ready(tmp_path)
    await _submit(runner, state, "/accepted")

    result = await _call(
        runner,
        state,
        "report",
        {"outcome": "done", "why": "it answered", "submission": "answered"},
    )

    assert "poll_until" in result["error"]
    assert runner.open_submission is not None


@pytest.mark.asyncio
async def test_a_report_with_nothing_open_needs_no_submission_field(
    tmp_path: Path,
) -> None:
    runner, _, state = await _ready(tmp_path)

    result = await _call(runner, state, "report", {"outcome": "done", "why": "read"})

    assert "error" not in result


@pytest.mark.asyncio
async def test_the_agent_gets_the_whole_response_body(tmp_path: Path) -> None:
    runner, _, state = await _ready(tmp_path)

    reply = await _submit(runner, state, "/long")

    assert json.loads(reply["body"])["result"]["message"] == "the tail"


@pytest.mark.asyncio
async def test_a_4xx_poll_still_leaves_the_submission_unresolved(
    tmp_path: Path,
) -> None:
    runner, _, state = await _ready(tmp_path)
    await _chat(runner, state)
    gone = await _call(
        runner, state, "poll_until", {"path": "/gone", "at": "$.state", "in": ["done"]}
    )

    await _call(
        runner,
        state,
        "report",
        {
            "outcome": "not_done",
            "why": "the poll failed",
            "reply_from": {"entry": gone["response_entry"], "at": "$.detail"},
        },
    )

    observation = runner._observation(state, None)
    assert observation.submission_unresolved
    assert observation.notice is not None
    assert "never settled" in observation.notice
    assert "status 4" not in observation.notice


@pytest.mark.asyncio
async def test_a_reply_cited_from_an_earlier_action_is_refused(tmp_path: Path) -> None:
    runner, _, state = await _ready(tmp_path)
    earlier = await _chat(runner, state)
    runner.begin_action("Say ⟦again⟧")
    state = ActionState(first_result=len(runner.results))

    result = await _call(
        runner,
        state,
        "report",
        {
            "outcome": "done",
            "why": "x",
            "submission": "pending",
            "reply_from": {"entry": earlier["response_entry"], "at": "$.reply"},
        },
    )

    assert "not one of the entries you may cite" in result["error"]
    assert state.report is None


@pytest.mark.asyncio
async def test_a_promised_name_must_be_a_single_line(tmp_path: Path) -> None:
    runner, _, state = await _ready(tmp_path)
    names = await _call(
        runner, state, "http_request", {"method": "GET", "path": "/names"}
    )

    result = await _call(
        runner,
        state,
        "report",
        {
            "outcome": "partial",
            "why": "x",
            "promised": [{"entry": names["response_entry"]}],
        },
    )

    assert "single line" in result["error"]
    assert state.report is None


@pytest.mark.asyncio
async def test_a_transport_failure_is_an_error_and_is_remembered(
    tmp_path: Path,
) -> None:
    runner, _, state = await _ready(tmp_path)

    result = await _call(
        runner, state, "http_request", {"method": "GET", "path": "/boom"}
    )

    assert "error" in result
    assert state.transport_failed is True


@pytest.mark.asyncio
async def test_run_tool_uses_the_handlers_it_is_given(tmp_path: Path) -> None:
    runner, _, state = await _ready(tmp_path)

    async def ping(_runner: Any, _state: ActionState, args: dict[str, Any]) -> Any:
        return {"pong": args}

    given = await run_tool(runner, state, "ping", '{"a": 1}', {"ping": ping})
    default = await run_tool(runner, state, "ping", "{}")

    assert given == {"pong": {"a": 1}}
    assert default["error"].startswith("refused, nothing was sent: there is no tool")


def test_the_handlers_any_runner_can_share() -> None:
    assert set(SHARED_HANDLERS) == {"session_id_from", "note", "report"}


@pytest.mark.asyncio
async def test_a_rejected_submission_is_shown_to_the_user_as_an_error(
    tmp_path: Path,
) -> None:
    runner, _, state = await _ready(tmp_path)
    rejected = await _submit(runner, state, "/rejects")
    await _call(
        runner, state, "report", {"outcome": "not_done", "why": "the target said no"}
    )

    observation = runner._observation(state, None)

    assert rejected["status"] == 422
    assert observation.reply is None
    assert observation.observed
    assert not observation.submission_unresolved
    assert runner.open_submission is None
    assert observation.notice is not None
    assert "422" in observation.notice
    assert "invalid_request" in observation.notice
    assert "error" in observation.notice
    assert "assistant" not in observation.notice
    shown = render_observation(observation)
    assert "422" in shown
    assert "invalid_request" in shown


@pytest.mark.asyncio
async def test_a_rejection_notice_holds_only_a_short_excerpt_of_the_body(
    tmp_path: Path,
) -> None:
    runner, _, state = await _ready(tmp_path)
    await _submit(runner, state, "/rejects-long")
    await _call(runner, state, "report", {"outcome": "not_done", "why": "no"})

    notice = runner._observation(state, None).notice

    assert notice is not None
    assert "500" in notice
    assert len(notice) < 500


@pytest.mark.asyncio
async def test_a_rejection_is_reported_once(tmp_path: Path) -> None:
    runner, _, state = await _ready(tmp_path)
    await _submit(runner, state, "/rejects")
    await _call(runner, state, "report", {"outcome": "not_done", "why": "no"})
    assert runner._observation(state, None).notice is not None

    runner.begin_action("Say ⟦again⟧")
    state = ActionState(first_result=len(runner.results))
    await _submit(runner, state)
    await _call(
        runner,
        state,
        "report",
        {
            "outcome": "done",
            "why": "ok",
            "submission": "answered",
            "reply_from": {"entry": runner.results[-1], "at": "$.reply"},
        },
    )

    observation = runner._observation(state, None)
    assert observation.notice is None
    assert observation.reply == "hi"


@pytest.mark.asyncio
async def test_a_failed_call_that_is_not_a_submission_adds_no_rejection(
    tmp_path: Path,
) -> None:
    runner, _, state = await _ready(tmp_path)
    await _call(runner, state, "http_request", {"method": "GET", "path": "/gone"})
    await _call(runner, state, "report", {"outcome": "unknown", "why": "looked"})

    assert runner._observation(state, None).notice is None


async def _begin_without_a_quote(
    runner: HttpRunner, action: str = "Ask about the leave policy"
) -> ActionState:
    runner.begin_action(action)
    return ActionState(first_result=len(runner.results))


@pytest.mark.asyncio
async def test_a_submission_with_no_quoted_message_is_reported_as_sent_nothing(
    tmp_path: Path,
) -> None:
    runner, target, _ = await _ready(tmp_path)
    state = await _begin_without_a_quote(runner)

    refused = await _submit(runner, state)
    await _call(runner, state, "report", {"outcome": "not_done", "why": "no text"})
    observation = runner._observation(state, None)

    assert refused["error"].startswith("refused, nothing was sent: ")
    assert target.sent("/chat") == []
    assert observation.sent_nothing
    assert observation.notice is not None
    assert "quoted no message" in observation.notice
    assert "quoted no message" in render_observation(observation)


@pytest.mark.asyncio
async def test_reads_before_the_refused_submission_do_not_make_the_action_a_turn(
    tmp_path: Path,
) -> None:
    runner, target, _ = await _ready(tmp_path)
    state = await _begin_without_a_quote(runner)

    # What the runner agent does first on a real target: a health check, a session open.
    await _call(runner, state, "http_request", {"method": "GET", "path": "/status"})
    await _submit(runner, state)
    await _call(runner, state, "report", {"outcome": "not_done", "why": "no text"})
    observation = runner._observation(state, None)

    assert len(runner.results) > state.first_result  # the read was logged
    assert target.sent("/chat") == []
    assert observation.sent_nothing
    assert "quoted no message" in (observation.notice or "")


@pytest.mark.asyncio
async def test_an_action_that_never_tried_to_submit_is_not_sent_nothing(
    tmp_path: Path,
) -> None:
    runner, _, _ = await _ready(tmp_path)
    state = await _begin_without_a_quote(runner, "Fetch the report")

    await _call(runner, state, "report", {"outcome": "unknown", "why": "waited"})
    observation = runner._observation(state, None)

    assert not observation.sent_nothing
    assert observation.notice is None


@pytest.mark.asyncio
async def test_an_action_with_a_quoted_message_is_sent_and_not_sent_nothing(
    tmp_path: Path,
) -> None:
    runner, target, state = await _ready(tmp_path)

    await _chat(runner, state)
    await _call(
        runner,
        state,
        "report",
        {
            "outcome": "done",
            "why": "ok",
            "submission": "answered",
            "reply_from": {"entry": runner.results[-1], "at": "$.reply"},
        },
    )
    observation = runner._observation(state, None)

    assert json.loads(target.sent("/chat")[0].content) == {"text": "hello"}
    assert not observation.sent_nothing
    assert observation.notice is None
    assert observation.reply == "hi"


@pytest.mark.asyncio
async def test_the_refusal_is_reported_once(tmp_path: Path) -> None:
    runner, _, _ = await _ready(tmp_path)
    state = await _begin_without_a_quote(runner)
    await _submit(runner, state)
    await _call(runner, state, "report", {"outcome": "not_done", "why": "no text"})
    assert runner._observation(state, None).sent_nothing

    state = await _begin_without_a_quote(runner, "Wait")
    await _call(runner, state, "report", {"outcome": "unknown", "why": "waited"})

    assert not runner._observation(state, None).sent_nothing


@pytest.mark.asyncio
async def test_every_tool_call_is_logged_with_its_outcome(tmp_path: Path) -> None:
    runner, _, state = await _ready(tmp_path)

    with structlog.testing.capture_logs() as logs:
        await _chat(runner, state)
        await _call(runner, state, "http_request", {"method": "DELETE", "path": "/x"})

    calls = [e for e in logs if e["event"] == "runner_agent_tool_call"]
    assert [(e["tool"], e["result"]) for e in calls] == [
        ("http_request", "ok"),
        ("http_request", "refused"),
    ]
    assert calls[0]["detail"] == "POST /chat -> 201"
    assert "forbidden" in calls[1]["detail"]


@pytest.mark.asyncio
async def test_a_refusal_for_quoting_nothing_is_logged_with_its_reason(
    tmp_path: Path,
) -> None:
    runner, _, _ = await _ready(tmp_path)
    state = await _begin_without_a_quote(runner)

    with structlog.testing.capture_logs() as logs:
        await _submit(runner, state)

    (call,) = [e for e in logs if e["event"] == "runner_agent_tool_call"]
    assert call["result"] == "refused"
    assert "quoted nothing to send" in call["detail"]
