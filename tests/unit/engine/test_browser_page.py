"""The generic browser runner against a static page in headless Chromium (#484).

The fake-page tests in ``test_browser_runner.py`` cannot show that Playwright's
accessibility snapshot has the ``[ref=eN]`` lines the runner parses, or that a download,
an upload and a sign-in work in a real browser. These do, against HTML the browser is
handed for a made-up origin, so nothing leaves the machine. They skip when Playwright or
Chromium is missing; on macOS, running them needs the sandbox off.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio

from metis.core.trials import TrialConfig
from metis.engine.simulation._fixture_artifacts import build_fixture_artifacts
from metis.engine.simulation.artifacts import ArtifactLedger
from metis.engine.simulation.binding import load_target_binding
from metis.engine.simulation.runners.browser import (
    BrowserRunner,
    BrowserRunnerFactory,
)
from metis.engine.simulation.runners.tools import ActionState, run_tool

from .test_agent_loop import ScriptedLLM

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

pytest.importorskip("playwright.async_api")
from playwright.async_api import async_playwright  # noqa: E402

PDF = b"%PDF-1.7\n"
ORIGIN = "https://chat.example"
_BINDING = f"""\
schema_version: 1
identity: {{name: Chat}}
transport: browser
start_url: {ORIGIN}/
"""
_LOGIN_BINDING = (
    _BINDING
    + """\
login:
  note: "Type {{secret:APP_USER}} in the email box and {{secret:APP_PASSWORD}} in the password box, then press Sign in."
  secrets: [APP_USER, APP_PASSWORD]
"""
)

_CHAT = """\
<h1>Chat</h1>
<div id="log"></div>
<input aria-label="Message" id="m">
<button id="send">Send</button>
<a href="/report.pdf" download>Download report.pdf</a>
<input type="file" aria-label="Attach" id="f">
<ul id="files"></ul>
<script>
  document.getElementById('send').onclick = () => {
    const box = document.getElementById('m'), text = box.value;
    if (!text) return;
    box.value = '';
    const log = document.getElementById('log');
    log.innerHTML = '<div role="progressbar" aria-label="Thinking"></div>';
    setTimeout(() => { log.innerHTML = '<p>Echo: ' + text + '</p>'; }, 300);
  };
  document.getElementById('f').onchange = (e) => {
    const li = document.createElement('li');
    li.textContent = e.target.files[0].name;
    document.getElementById('files').appendChild(li);
  };
</script>
"""

_SIGN_IN = """\
<h1>Sign in</h1>
<input aria-label="Email" id="u">
<input type="password" aria-label="Password" id="p">
<button id="go">Sign in</button>
<script>
  document.getElementById('go').onclick = () => {
    if (document.getElementById('u').value === 'alice'
        && document.getElementById('p').value === 'SENTINEL-PASSWORD') {
      document.body.innerHTML = '<h1>Welcome</h1>';
    }
  };
</script>
"""


class PagesBrowser:
    """A real browser whose contexts answer the made-up origin from memory."""

    def __init__(
        self, browser: Any, pages: dict[str, tuple[bytes, str, dict[str, str]]]
    ) -> None:
        self._browser = browser
        self._pages = pages

    async def new_context(self, **options: Any) -> Any:
        context = await self._browser.new_context(**options)

        async def answer(route: Any) -> None:
            path = route.request.url.removeprefix(ORIGIN) or "/"
            if path not in self._pages:
                await route.fulfill(status=404, body="not found")
                return
            body, kind, headers = self._pages[path]
            await route.fulfill(
                status=200, body=body, content_type=kind, headers=headers
            )

        await context.route(f"{ORIGIN}/**", answer)
        return context

    async def close(self) -> None:
        await self._browser.close()


def _html(body: str) -> tuple[bytes, str, dict[str, str]]:
    return f"<!doctype html><html><body>{body}</body></html>".encode(), "text/html", {}


@pytest_asyncio.fixture
async def real_browser() -> AsyncIterator[Any]:
    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(headless=True)
        except Exception as exc:  # no Chromium installed, or the sandbox forbids it
            pytest.skip(f"Chromium cannot be launched: {type(exc).__name__}")
        yield browser
        await browser.close()


def _pages(start: str = _CHAT) -> dict[str, tuple[bytes, str, dict[str, str]]]:
    return {
        "/": _html(start),
        "/report.pdf": (PDF, "application/pdf", {"content-disposition": "attachment"}),
    }


async def _ready(
    tmp_path: Path,
    browser: Any,
    llm: ScriptedLLM,
    *,
    binding: str = _BINDING,
    pages: dict[str, tuple[bytes, str, dict[str, str]]] | None = None,
    fixtures: list[str] | None = None,
) -> tuple[BrowserRunner, BrowserRunnerFactory]:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "app.yaml").write_text(binding, encoding="utf-8")
    factory = BrowserRunnerFactory(
        load_target_binding(inputs, "app.yaml", "browser"),
        browser=PagesBrowser(browser, pages or _pages()),
        llm=llm,  # type: ignore[arg-type]
        login_dir=tmp_path / "login",
    )
    await factory.start()
    trial = tmp_path / "trial"
    runner = await factory.create(trial, tmp_path, tmp_path)
    held = []
    for name in fixtures or []:
        (tmp_path / name).write_bytes(PDF)
        held = build_fixture_artifacts(fixtures or [], tmp_path, tmp_path)
    runner.use_ledger(ArtifactLedger(tmp_path, trial, held))
    await runner.setup(TrialConfig(persona="p", scenario="s"))
    return runner, factory


def _find(runner: BrowserRunner, role: str, name: str) -> str:
    """The ref the real snapshot gave an element: what the model would read off it."""
    return next(ref for ref, found in runner.refs.items() if found == (role, name))


async def _call(runner: BrowserRunner, name: str, args: Any) -> dict[str, Any]:
    state = ActionState(first_result=len(runner.results))
    return await run_tool(runner, state, name, json.dumps(args), runner.handlers)


@pytest.mark.asyncio
async def test_the_real_snapshot_gives_refs_the_runner_can_act_on(
    tmp_path: Path, real_browser: Any
) -> None:
    runner, _ = await _ready(tmp_path, real_browser, ScriptedLLM([]))
    try:
        runner.begin_action("Say ⟦hello⟧")
        await _call(runner, "snapshot", {})

        assert ("textbox", "Message") in runner.refs.values()
        assert ("button", "Send") in runner.refs.values()
        assert all(ref.startswith("e") for ref in runner.refs)
    finally:
        await runner.teardown()


@pytest.mark.asyncio
async def test_the_user_types_sends_waits_and_the_reply_is_cited_by_ref(
    tmp_path: Path, real_browser: Any
) -> None:
    llm = ScriptedLLM([])
    runner, _ = await _ready(tmp_path, real_browser, llm)
    try:
        await runner.act(
            "Say ⟦hello⟧", []
        )  # a first look; the scripted agent just stops
        box, send = _find(runner, "textbox", "Message"), _find(runner, "button", "Send")
        llm._replies[:] = [
            [("type", {"ref": box, "text": "{{1}}"}), ("click", {"ref": send})],
            [("wait_for", {"text_present": "Echo: hello"})],
            lambda: [
                (
                    "report",
                    {
                        "outcome": "done",
                        "why": "sent it",
                        "reply_from": {
                            "entry": runner.results[-1],
                            "ref": _find(runner, "paragraph", ""),
                        },
                    },
                )
            ],
        ]

        observation = await runner.act("Say ⟦hello⟧", [])

        assert observation.reply is not None and "Echo: hello" in observation.reply
        assert (observation.observed, observation.notice) == (True, None)
    finally:
        await runner.teardown()


@pytest.mark.asyncio
async def test_a_download_and_an_upload_are_recorded(
    tmp_path: Path, real_browser: Any
) -> None:
    runner, _ = await _ready(
        tmp_path, real_browser, ScriptedLLM([]), fixtures=["notes.pdf"]
    )
    try:
        runner.begin_action("Look")
        await _call(runner, "snapshot", {})

        received = await _call(
            runner,
            "fetch_files",
            {"links": [_find(runner, "link", "Download report.pdf")]},
        )
        uploaded = await _call(
            runner,
            "choose_file",
            {"ref": _find(runner, "button", "Attach"), "file": "notes.pdf"},
        )

        assert received["files"][0]["state"] == "received"
        assert uploaded["ledger"] == "recorded upload"
        held = {a.name: (a.source, a.state) for a in runner.ledger.artifacts()}
        assert held["report.pdf"] == ("target", "received")
        assert held["notes.pdf"][0] == "fixture"
    finally:
        await runner.teardown()


@pytest.mark.asyncio
async def test_a_login_types_secrets_that_the_logs_show_as_stars(
    tmp_path: Path, real_browser: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_USER", "alice")
    monkeypatch.setenv("APP_PASSWORD", "SENTINEL-PASSWORD")
    llm = ScriptedLLM([])
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "app.yaml").write_text(_LOGIN_BINDING, encoding="utf-8")
    factory = BrowserRunnerFactory(
        load_target_binding(inputs, "app.yaml", "browser"),
        browser=PagesBrowser(real_browser, _pages(_SIGN_IN)),
        llm=llm,  # type: ignore[arg-type]
        login_dir=tmp_path / "login",
    )
    # the scripted agent reads refs off the real snapshot, so it must look first
    llm._replies[:] = [
        [("snapshot", {})],
        lambda: [
            ("type", {"ref": _ref(llm, "Email"), "text": "{{secret:APP_USER}}"}),
            ("type", {"ref": _ref(llm, "Password"), "text": "{{secret:APP_PASSWORD}}"}),
            ("click", {"ref": _ref(llm, "Sign in", "button")}),
        ],
        [("report", {"outcome": "done", "why": "signed in"})],
    ]

    await factory.start()

    texts = "".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "login").rglob("*")
        if path.is_file()
    )
    assert "***" in texts
    assert "SENTINEL-PASSWORD" not in texts and "SENTINEL-PASSWORD" not in str(
        llm.requests
    )
    assert factory._storage_state is not None  # noqa: SLF001
    await factory.close()


def _ref(llm: ScriptedLLM, name: str, role: str = "textbox") -> str:
    """The ref of ``role "name"`` in the newest snapshot the scripted agent was shown."""
    for message in reversed(llm.requests[-1]["messages"]):
        if message["role"] == "tool":
            page = json.loads(message["content"]).get("page", "")
            for line in page.splitlines():
                if f'{role} "{name}"' in line and "[ref=" in line:
                    return line.split("[ref=")[1].split("]")[0]
    raise AssertionError(f"no {role} {name!r} in the snapshot the agent saw")
