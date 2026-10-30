"""The generic browser runner's loop and tools, against a fake page (#484).

No real browser runs here: ``FakePage`` models a one-screen chat with the few Playwright
calls the runner makes. A page that is really loaded in Chromium is tested separately.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from metis.core.trials import TrialConfig
from metis.engine.simulation._fixture_artifacts import build_fixture_artifacts
from metis.engine.simulation.artifacts import ArtifactLedger
from metis.engine.simulation.binding import (
    TargetBindingError,
    load_target_binding,
)
from metis.engine.simulation.runners import browser as browser_module
from metis.engine.simulation.runners.browser import (
    BrowserRunner,
    BrowserRunnerFactory,
)
from metis.engine.simulation.runners.http import HttpRunnerFactory
from metis.engine.simulation.runners.tools import ActionState, run_tool
from metis.engine.simulation.transport_log import TransportLog

from .test_agent_loop import Clock, ScriptedLLM

if TYPE_CHECKING:
    from pathlib import Path

PDF = b"%PDF-1.7\n"
_BINDING = """\
schema_version: 1
identity: {name: Chat}
transport: browser
start_url: https://chat.example/
"""
_LOGIN_BINDING = (
    _BINDING
    + """\
login:
  note: "Type {{secret:APP_USER}} in the email box and {{secret:APP_PASSWORD}} in the password box."
  secrets: [APP_USER, APP_PASSWORD]
"""
)


class FakeLocator:
    def __init__(self, page: FakePage, selector: str) -> None:
        self.page = page
        self.selector = selector

    async def aria_snapshot(self, **_: Any) -> str:
        return self.page.render()

    async def click(self, **_: Any) -> None:
        self.page.click(self.selector.removeprefix("aria-ref="))

    async def fill(self, text: str, **_: Any) -> None:
        self.page.fill(self.selector.removeprefix("aria-ref="), text)

    async def press(self, key: str, **_: Any) -> None:
        self.page.click("e3")

    async def input_value(self, **_: Any) -> str:
        return self.page.fields.get(self.selector.removeprefix("aria-ref="), "")

    async def set_input_files(self, path: str, **_: Any) -> None:
        self.page.attached.append(path.rsplit("/", 1)[-1])


class FakeDownload:
    def __init__(self, name: str, path: Path) -> None:
        self.suggested_filename = name
        self._path = path

    async def path(self) -> Path:
        return self._path


class FakePage:
    """A chat screen, or a sign-in screen until the right words are typed and sent.

    The chat answers ``Echo: <message>`` after two snapshots in which it is still
    "thinking" (a progress bar).
    """

    def __init__(self, tmp_path: Path, *, signed_in: bool = True) -> None:
        self.url = "https://chat.example/c/abc-123"
        self.signed_in = signed_in
        self.fields: dict[str, str] = {}
        self.sent: list[str] = []
        self.reply = ""
        self.thinking = 0
        self.attached: list[str] = []
        self.shows_attached = True
        self.download = FakeDownload("a.pdf", tmp_path / "dl")
        (tmp_path / "dl").write_bytes(PDF)
        self.filled: list[str] = []

    async def goto(self, url: str, **_: Any) -> None:
        self.url = url if not self.signed_in else self.url

    async def title(self) -> str:
        return "Chat"

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector)

    def fill(self, ref: str, text: str) -> None:
        self.filled.append(text)
        self.fields[ref] = text

    def click(self, ref: str) -> None:
        if ref != "e3":
            return
        if not self.signed_in:
            self.signed_in = self.fields.get("e1") == "alice" and bool(
                self.fields.get("e2")
            )
            self.fields = {}
            return
        message = self.fields.pop("e2", "")
        if message:
            self.sent.append(message)
            self.reply, self.thinking = f"Echo: {message}", 2

    def render(self) -> str:
        if not self.signed_in:
            return (
                '- textbox "Email" [ref=e1]\n- textbox "Password" [ref=e2]\n'
                '- button "Sign in" [ref=e3]'
            )
        lines = [
            '- heading "Chat" [ref=e10]',
            '- textbox "Message" [ref=e2]',
            '- button "Send" [ref=e3]',
            '- link "Download a.pdf" [ref=e4]',
            '- radio "Blue" [ref=e5]',
            '- radio "Red" [ref=e6]',
            '- button "Attach" [ref=e7]',
        ]
        if self.attached and self.shows_attached:
            lines.append(f"- listitem [ref=e8]: {self.attached[-1]}")
        if self.thinking:
            self.thinking -= 1
            lines.append("- progressbar [ref=e9]")
        elif self.reply:
            lines.append(f"- paragraph [ref=e11]: {self.reply}")
        return "\n".join(lines)

    @asynccontextmanager
    async def expect_download(self, **_: Any) -> Any:
        class Info:
            value = self._value()

        yield Info

    async def _value(self) -> FakeDownload:
        return self.download


class FakeContext:
    def __init__(self, page: FakePage, kwargs: dict[str, Any]) -> None:
        self.page, self.kwargs, self.closed = page, kwargs, False

    async def new_page(self) -> FakePage:
        return self.page

    async def storage_state(self) -> dict[str, Any]:
        return {"cookies": ["SENTINEL-COOKIE"]}

    async def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, page: FakePage) -> None:
        self.page = page
        self.contexts: list[FakeContext] = []

    async def new_context(self, **kwargs: Any) -> FakeContext:
        self.contexts.append(FakeContext(self.page, kwargs))
        return self.contexts[-1]

    async def close(self) -> None:
        pass


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(browser_module, "_now", fake)
    monkeypatch.setattr(browser_module, "_sleep", fake.sleep)
    return fake


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_USER", "alice")
    monkeypatch.setenv("APP_PASSWORD", "SENTINEL-PASSWORD")


def _inputs(tmp_path: Path, text: str) -> Path:
    inputs = tmp_path / "inputs"
    inputs.mkdir(exist_ok=True)
    (inputs / "app.yaml").write_text(text, encoding="utf-8")
    return inputs


async def _ready(
    tmp_path: Path,
    llm: ScriptedLLM,
    *,
    page: FakePage | None = None,
    binding: str = _BINDING,
    fixtures: list[str] | None = None,
) -> tuple[BrowserRunner, FakePage, FakeBrowser]:
    page = page or FakePage(tmp_path)
    browser = FakeBrowser(page)
    factory = BrowserRunnerFactory(
        load_target_binding(_inputs(tmp_path, binding), "app.yaml", "browser"),
        browser=browser,
        llm=llm,  # type: ignore[arg-type]
        login_dir=tmp_path / "login",
    )
    await factory.start()
    trial = tmp_path / "trial"
    runner = await factory.create(trial, tmp_path, tmp_path)
    held = []
    if fixtures:
        for name in fixtures:
            (tmp_path / name).write_bytes(PDF)
        held = build_fixture_artifacts(fixtures, tmp_path, tmp_path)
    runner.use_ledger(ArtifactLedger(tmp_path, trial, held))
    await runner.setup(TrialConfig(persona="p", scenario="s", response_wait_ms=10000))
    return runner, page, browser


def _send(text: str = "{{1}}") -> list[tuple[str, dict[str, Any]]]:
    return [("type", {"ref": "e2", "text": text}), ("click", {"ref": "e3"})]


def _report(runner: BrowserRunner, **extra: Any) -> Any:
    def build() -> list[tuple[str, dict[str, Any]]]:
        args = {
            "outcome": "done",
            "why": "sent it",
            "reply_from": {"entry": runner.results[-1], "ref": "e11"},
            **extra,
        }
        return [("report", args)]

    return build


def _begin(runner: BrowserRunner, action: str = "Say ⟦hello⟧") -> ActionState:
    runner.begin_action(action)
    return ActionState(first_result=len(runner.results))


async def _call(
    runner: BrowserRunner, state: ActionState, name: str, args: Any
) -> dict[str, Any]:
    return await run_tool(runner, state, name, json.dumps(args), runner.handlers)


@pytest.mark.asyncio
async def test_the_user_types_the_page_waits_and_the_reply_is_cited_by_ref(
    tmp_path: Path, clock: Clock
) -> None:
    llm = ScriptedLLM(
        _send(),
        [("wait_for", {"text_present": "Echo:"})],
    )
    runner, page, _ = await _ready(tmp_path, llm)
    llm._replies.append(_report(runner))

    observation = await runner.act("Say ⟦hello⟧", [])

    assert page.sent == ["hello"]
    assert observation.reply == "- paragraph [ref=e11]: Echo: hello"
    assert (observation.observed, observation.notice) == (True, None)
    assert observation.reading.outcome == "done"


@pytest.mark.asyncio
async def test_each_action_and_page_capture_is_logged_as_request_and_response(
    tmp_path: Path, clock: Clock
) -> None:
    llm = ScriptedLLM([("snapshot", {}), ("report", {"outcome": "done", "why": "x"})])
    runner, _, _ = await _ready(tmp_path, llm)

    await runner.act("Say ⟦hello⟧", [])

    entries = [
        runner.log.get(f"e{i}") for i in range(1, len(runner.log._entries()) + 1)
    ]
    assert [(e.kind, e.role) for e in entries[:2]] == [
        ("request", "action"),
        ("response", "result"),
    ]
    capture = json.loads(runner.log.body_bytes(entries[1]))
    assert set(capture) >= {"url", "title", "snapshot"}
    assert capture["url"] == "https://chat.example/c/abc-123"
    assert entries[1].pairs_with == entries[0].id


@pytest.mark.asyncio
async def test_a_choice_the_user_did_not_name_is_refused(tmp_path: Path) -> None:
    runner, page, _ = await _ready(tmp_path, ScriptedLLM([]))
    state = _begin(runner, "Pick ⟦Red⟧")

    wrong = await _call(runner, state, "click", {"ref": "e5", "choice": "{{1}}"})
    bare = await _call(runner, state, "click", {"ref": "e5"})
    right = await _call(runner, state, "click", {"ref": "e6", "choice": "{{1}}"})

    assert "the user chose 'Red'" in wrong["error"]
    assert "the user's choice" in bare["error"]
    assert "error" not in right


@pytest.mark.asyncio
async def test_nothing_is_typed_when_the_action_quoted_nothing(tmp_path: Path) -> None:
    runner, page, _ = await _ready(tmp_path, ScriptedLLM([]))
    state = _begin(runner, "Look around")

    refused = await _call(runner, state, "type", {"ref": "e2", "text": "hi"})

    assert "quoted nothing" in refused["error"]
    assert page.filled == []


@pytest.mark.asyncio
async def test_a_submission_stays_open_until_wait_for_settles_it(
    tmp_path: Path, clock: Clock
) -> None:
    llm = ScriptedLLM(_send(), [("report", {"outcome": "partial", "why": "waiting"})])
    runner, _, _ = await _ready(tmp_path, llm)

    observation = await runner.act("Say ⟦hello⟧", [])

    assert observation.observed is False
    assert observation.notice is not None and "still open" in observation.notice
    state = _begin(runner, "Say ⟦again⟧")
    await _call(runner, state, "type", {"ref": "e2", "text": "{{1}}"})
    refused = await _call(runner, state, "click", {"ref": "e3"})
    assert "still open" in refused["error"]
    settled = await _call(runner, state, "wait_for", {"text_present": "Echo:"})
    assert settled["condition"] == "holds"
    assert runner.open_submission is None


@pytest.mark.asyncio
async def test_text_left_in_the_field_is_not_a_submission(tmp_path: Path) -> None:
    runner, page, _ = await _ready(tmp_path, ScriptedLLM([]))
    state = _begin(runner)
    await _call(runner, state, "type", {"ref": "e2", "text": "{{1}}"})
    page.click = lambda ref: None  # type: ignore[method-assign]  # the Send button does nothing

    result = await _call(runner, state, "click", {"ref": "e3"})

    assert "not sent" in result["submission"]
    assert runner.open_submission is None


@pytest.mark.asyncio
async def test_a_ref_outside_the_latest_snapshot_is_refused(tmp_path: Path) -> None:
    runner, _, _ = await _ready(tmp_path, ScriptedLLM([]))
    state = _begin(runner)

    refused = await _call(runner, state, "click", {"ref": "e99"})

    assert "not in the latest snapshot" in refused["error"]


@pytest.mark.asyncio
async def test_the_session_id_is_copied_from_the_address(
    tmp_path: Path, clock: Clock
) -> None:
    runner, _, _ = await _ready(tmp_path, ScriptedLLM([]))
    state = _begin(runner)
    result = await _call(runner, state, "snapshot", {})

    session = await _call(
        runner,
        state,
        "session_id_from",
        {"entry": result["capture_entry"], "at": "$.url", "pattern": r"/c/([\w-]+)"},
    )

    assert session["session_id"] == runner.session_id == "abc-123"


@pytest.mark.asyncio
async def test_a_download_is_recorded_and_a_wrong_file_is_not(tmp_path: Path) -> None:
    runner, page, _ = await _ready(tmp_path, ScriptedLLM([]))
    state = _begin(runner)
    await _call(runner, state, "snapshot", {})

    good = await _call(runner, state, "fetch_files", {"links": ["e4"]})
    page.download = FakeDownload("b.pdf", tmp_path / "html")
    (tmp_path / "html").write_bytes(b"<html>login</html>" + b"{")
    (tmp_path / "html").write_bytes(b'{"error": "expired"}')
    bad = await _call(runner, state, "fetch_files", {"links": ["e4"]})

    held = {a.name: a.state for a in runner.ledger.artifacts()}
    assert good["files"][0]["state"] == "received"
    assert bad["files"][0]["state"] == "unfetched"
    assert held == {"a.pdf": "received", "b.pdf": "unfetched"}


@pytest.mark.asyncio
async def test_a_file_already_held_is_not_fetched_twice(tmp_path: Path) -> None:
    runner, _, _ = await _ready(tmp_path, ScriptedLLM([]))
    state = _begin(runner)
    await _call(runner, state, "snapshot", {})
    await _call(runner, state, "fetch_files", {"links": ["e4"]})

    again = await _call(runner, state, "fetch_files", {"links": ["e4"]})

    assert again["files"][0]["skipped"] == "already held"
    assert [a.name for a in runner.ledger.artifacts()] == ["a.pdf"]


@pytest.mark.asyncio
async def test_an_upload_is_recorded_only_when_the_page_shows_the_file(
    tmp_path: Path,
) -> None:
    runner, page, _ = await _ready(tmp_path, ScriptedLLM([]), fixtures=["notes.pdf"])
    state = _begin(runner)
    await _call(runner, state, "snapshot", {})

    shown = await _call(
        runner, state, "choose_file", {"ref": "e7", "file": "notes.pdf"}
    )
    page.shows_attached = False
    hidden = await _call(
        runner, state, "choose_file", {"ref": "e7", "file": "notes.pdf"}
    )
    unknown = await _call(runner, state, "choose_file", {"ref": "e7", "file": "no.pdf"})

    assert shown["ledger"] == "recorded upload"
    assert hidden["ledger"].startswith("not recorded")
    assert "not a file you hold" in unknown["error"]
    assert runner.ledger.artifacts()[0].at_simulated_turn == 1


@pytest.mark.asyncio
async def test_login_types_a_secret_the_log_shows_as_stars_and_context_reuses_state(
    tmp_path: Path, clock: Clock
) -> None:
    page = FakePage(tmp_path, signed_in=False)
    llm = ScriptedLLM(
        [
            ("type", {"ref": "e1", "text": "{{secret:APP_USER}}"}),
            ("type", {"ref": "e2", "text": "{{secret:APP_PASSWORD}}"}),
            ("click", {"ref": "e3"}),
        ],
        [("report", {"outcome": "done", "why": "signed in"})],
    )

    _, page, browser = await _ready(tmp_path, llm, page=page, binding=_LOGIN_BINDING)

    assert page.filled == ["alice", "SENTINEL-PASSWORD"]
    log_text = "".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "login").rglob("*")
        if path.is_file()
    )
    assert "SENTINEL-PASSWORD" not in log_text and "***" in log_text
    assert "SENTINEL-PASSWORD" not in str(llm.requests)
    assert browser.contexts[0].closed
    assert browser.contexts[-1].kwargs["storage_state"] == {
        "cookies": ["SENTINEL-COOKIE"]
    }


@pytest.mark.asyncio
async def test_a_secret_the_binding_does_not_list_is_refused(tmp_path: Path) -> None:
    signed_in = ScriptedLLM([("report", {"outcome": "done", "why": "in"})])
    runner, _, _ = await _ready(tmp_path, signed_in, binding=_LOGIN_BINDING)
    state = _begin(runner)

    refused = await _call(
        runner, state, "type", {"ref": "e2", "text": "{{secret:OTHER}}"}
    )

    assert "not a secret the binding lists" in refused["error"]


@pytest.mark.asyncio
async def test_a_login_that_does_not_finish_fails_the_start(tmp_path: Path) -> None:
    page = FakePage(tmp_path, signed_in=False)
    llm = ScriptedLLM([("report", {"outcome": "not_done", "why": "no such box"})])
    factory = BrowserRunnerFactory(
        load_target_binding(_inputs(tmp_path, _LOGIN_BINDING), "app.yaml", "browser"),
        browser=FakeBrowser(page),
        llm=llm,  # type: ignore[arg-type]
        login_dir=tmp_path / "login",
    )

    with pytest.raises(TargetBindingError, match="login did not finish"):
        await factory.start()


@pytest.mark.asyncio
async def test_the_first_message_holds_the_page_and_no_secret(
    tmp_path: Path, clock: Clock
) -> None:
    llm = ScriptedLLM([("report", {"outcome": "done", "why": "x"})])
    runner, _, _ = await _ready(tmp_path, llm, binding=_LOGIN_BINDING)

    await runner.act("Say ⟦hello⟧", [])

    message = llm.first_message(1)  # request 0 was the sign-in's
    assert "Say {{1}}" in message and "⟦" not in message
    assert '- textbox "Message" [ref=e2]' in message
    assert "SENTINEL" not in message and "alice" not in message


@pytest.mark.asyncio
async def test_a_tool_result_from_an_earlier_round_is_trimmed(tmp_path: Path) -> None:
    llm = ScriptedLLM(
        [("snapshot", {})],
        [("snapshot", {})],
        [("report", {"outcome": "done", "why": "x"})],
    )
    runner, _, _ = await _ready(tmp_path, llm)

    await runner.act("Say ⟦hello⟧", [])

    first_tool = json.loads(llm.requests[2]["messages"][3]["content"])
    assert first_tool["page"].startswith("(logged as e")


def test_the_two_factories_refuse_each_others_bindings(tmp_path: Path) -> None:
    http = _BINDING.replace("transport: browser", "transport: http").replace(
        "start_url: https://chat.example/", "spec_url: https://chat.example/o.json"
    )
    specification: Any = SimpleNamespace(target_binding="app.yaml")
    for text, factory, wanted in (
        (http, BrowserRunnerFactory, "needs a browser binding"),
        (_BINDING, HttpRunnerFactory, "needs a http binding"),
    ):
        inputs = _inputs(tmp_path, text)
        with pytest.raises(TargetBindingError, match=wanted):
            factory.from_specification(specification, inputs)


def test_the_transport_log_is_the_trials_own(tmp_path: Path) -> None:
    assert TransportLog.for_trial(tmp_path / "trial").path.parent.name == "evidence"


@pytest.mark.asyncio
async def test_typing_with_no_quoted_message_is_sent_nothing_and_not_a_turn(
    tmp_path: Path, clock: Clock
) -> None:
    llm = ScriptedLLM(
        [("type", {"ref": "e2", "text": "hi"})],
        [("report", {"outcome": "not_done", "why": "no text to type"})],
        _send(),
        [("wait_for", {"text_present": "Echo:"})],
    )
    runner, page, _ = await _ready(tmp_path, llm)
    llm._replies.append(_report(runner))

    empty = await runner.act("Ask about the leave policy", [])
    sent = await runner.act("Say ⟦hello⟧", [])

    assert page.sent == ["hello"]
    assert empty.sent_nothing
    assert "quoted no message" in (empty.notice or "")
    assert not sent.sent_nothing
    assert sent.notice is None
    assert runner._turn == 1


@pytest.mark.asyncio
async def test_looking_at_the_page_does_not_make_an_unquoted_action_a_turn(
    tmp_path: Path, clock: Clock
) -> None:
    llm = ScriptedLLM(
        [("snapshot", {}), ("type", {"ref": "e2", "text": "hi"})],
        [("report", {"outcome": "unknown", "why": "looked"})],
    )
    runner, _, _ = await _ready(tmp_path, llm)

    observation = await runner.act("Look around", [])

    assert observation.sent_nothing
    assert runner._turn == 0


@pytest.mark.asyncio
async def test_an_action_with_no_quote_that_never_tried_to_type_is_a_turn(
    tmp_path: Path, clock: Clock
) -> None:
    llm = ScriptedLLM([("report", {"outcome": "unknown", "why": "looked"})])
    runner, _, _ = await _ready(tmp_path, llm)

    observation = await runner.act("Look around", [])

    assert not observation.sent_nothing
    assert observation.notice is None
    assert runner._turn == 1


@pytest.mark.asyncio
async def test_clicking_around_before_the_refused_typing_does_not_make_a_turn(
    tmp_path: Path, clock: Clock
) -> None:
    llm = ScriptedLLM(
        [("click", {"ref": "e4"}), ("type", {"ref": "e2", "text": "hi"})],
        [("report", {"outcome": "not_done", "why": "no text"})],
    )
    runner, page, _ = await _ready(tmp_path, llm)

    observation = await runner.act("Look around", [])

    assert page.sent == []
    assert observation.sent_nothing
    assert runner._turn == 0
