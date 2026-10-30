"""The generic browser runner: the page tools and the rules code enforces on them.

**Status: built and tested offline only; it has never met a live page.** Its tests drive a
fake page and a static one in headless Chromium. Making it work against a real app is the
next piece of work.

``BrowserRunnerFactory`` loads the specification's browser binding, holds one browser for
every trial and, if the binding has a ``login``, signs in once in ``start()``: the runner
agent drives the sign-in, code types the secrets and logs them as ``***``, and the
logged-in storage state stays in memory only. Each trial gets its own context from that
state. The agent acts on the page through ``snapshot``, ``click``, ``type``, ``choose``,
``choose_file``, ``wait_for`` and ``fetch_files``. Every action is logged as a ``request``
and every page capture, ``{url, title, snapshot}``, as a ``response``, so ``report`` can
cite an element of a capture by ``ref``.

The loop in ``_attempt``, ``_run_agent`` and ``_observation`` is a copy of ``HttpRunner``'s,
adapted for a page. Stage 4 merges the two.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import TYPE_CHECKING, Any

import openai
from openai import AsyncOpenAI

from metis.core.logging import get_logger
from metis.core.trials import TrialConfig

from ..artifacts import ArtifactLedger, ArtifactRejected
from ..binding import TargetBindingError, load_target_binding
from ..config import TrialRetryConfig
from ..evidence import Pointer, resolve
from ..exceptions import TrialRecoverableError, TurnRecoverableError
from ..llm_calls import LLMCallLog, create_completion
from ..model_settings import llm_client, runner_agent_settings
from ..runner import Runner
from ..transport_log import TransportLog
from ..types import Observation, Reading
from .browser_prompts import SYSTEM_PROMPT as BROWSER_SYSTEM_PROMPT
from .browser_prompts import first_message
from .http import OpenSubmission, sent_chars
from .prompts import NUDGE
from .rules import ToolRefused
from .spans import Spans, secret_name
from .tools import (
    OUTCOMES,
    SHARED_HANDLERS,
    ActionState,
    pointer_schema,
    run_tool,
    tool_schema,
)

if TYPE_CHECKING:
    from pathlib import Path

    from metis.core.specification import Specification

    from ..binding import LoadedBinding
    from ..types import Promise
    from .tools import Handler

logger = get_logger()

MAX_ROUNDS = 15
"""Most LLM rounds one action may take."""
ACT_MARGIN = 60.0
"""Seconds added to ``response_wait_ms`` for one action's time limit."""
POLL_INTERVAL = 1.0
"""Seconds between looks at the page while ``wait_for`` waits."""
STABLE_DEFAULT = 5.0
"""Seconds the page must stop changing when ``wait_for`` is given no condition."""
UPLOAD_SETTLE = 1.0
"""Seconds given to a page to show a file it was just given."""
_sleep = asyncio.sleep  # names tests replace
_now = time.monotonic

_BUSY = re.compile(r"-\s+(progressbar|status)\b|\[busy\]|aria-busy|\bbusy\b", re.I)
_REF_LINE = re.compile(r'^\s*-\s+(\w+)(?:\s+"((?:[^"\\]|\\.)*)")?.*\[ref=(e\d+)\]')
_PASSWORD_BOX = re.compile(r'textbox "[^"]*(password|passcode)', re.I)
_CHOICE_ROLES = {
    "combobox",
    "listbox",
    "radio",
    "checkbox",
    "switch",
    "slider",
    "option",
    "menuitemradio",
    "menuitemcheckbox",
}
_CLICKABLE = ("button", "link", "menuitem")


def busy(snapshot: str) -> bool:
    """Whether the page is still working: it shows a progress bar or marks a region busy."""
    return any(_BUSY.search(line) for line in snapshot.splitlines())


def trimmed_pages(messages: list[Any]) -> list[Any]:
    """A copy of ``messages`` with the pages of earlier rounds' results shortened.

    The agent points at log entries, never at message text, so a page it has already
    read is replaced by the entry that holds it. The latest round stays whole.
    """
    last = max(
        (i for i, m in enumerate(messages) if m["role"] == "assistant"), default=0
    )
    sent = list(messages)
    for i, message in enumerate(messages[:last]):
        if message["role"] != "tool":
            continue
        result = json.loads(message["content"])
        if isinstance(result.get("page"), str) and "capture_entry" in result:
            size = len(result["page"])
            result["page"] = (
                f"(logged as {result['capture_entry']}, {size:,} characters)"
            )
            sent[i] = {**message, "content": json.dumps(result, ensure_ascii=False)}
    return sent


_REF = {
    "type": "string",
    "description": "an element ref from the latest snapshot, e.g. e12",
}

TOOLS: list[Any] = [
    tool_schema("snapshot", "Look at the page again.", {}),
    tool_schema(
        "click",
        "Click an element. If the click picks one of the choices the page offered, give "
        "the user's choice as `choice` ({{n}}); code checks the element carries that name.",
        {"ref": _REF, "choice": {"type": "string"}},
        "ref",
    ),
    tool_schema(
        "type",
        "Type into a text field: `text` is {{n}} placeholders (or {{secret:NAME}} alone, "
        "to sign in). `press_enter` sends it with Enter.",
        {"ref": _REF, "text": {"type": "string"}, "press_enter": {"type": "boolean"}},
        "ref",
        "text",
    ),
    tool_schema(
        "choose",
        "Pick an option in a dropdown or list: `choice` is {{n}}.",
        {"ref": _REF, "choice": {"type": "string"}},
        "ref",
        "choice",
    ),
    tool_schema(
        "choose_file",
        "Attach a file you hold to a file control: `file` is its name in the file list.",
        {"ref": _REF, "file": {"type": "string"}},
        "ref",
        "file",
    ),
    tool_schema(
        "wait_for",
        "Wait, in code, until a condition holds or the wait limit passes: `text_present` "
        "or `text_absent` (text on the page), `ref_absent`, or `stable_seconds` (the page "
        "stops changing). An open submission settles only through this tool.",
        {
            "text_present": {"type": "string"},
            "text_absent": {"type": "string"},
            "ref_absent": {"type": "string"},
            "stable_seconds": {"type": "number"},
        },
    ),
    tool_schema(
        "fetch_files",
        "Download and record every file behind these download links or buttons, in one "
        "call: `links` are refs from the latest snapshot. Files already held are skipped.",
        {"links": {"type": "array", "items": {"type": "string"}}},
        "links",
    ),
    tool_schema(
        "session_id_from",
        "Record the target's session ID from a logged capture, e.g. `at` `$.url` with a "
        "`pattern`.",
        pointer_schema({"ref": {"type": "string"}})["properties"],
        "entry",
    ),
    tool_schema(
        "note",
        "Keep what you learned about this page for later turns.",
        {"text": {"type": "string"}},
        "text",
    ),
    tool_schema(
        "report",
        "End the action. Call it once, last.",
        {
            "outcome": {"type": "string", "enum": list(OUTCOMES)},
            "why": {"type": "string"},
            "next_options": {"type": "string"},
            "reply_from": pointer_schema({"ref": {"type": "string"}}),
            "promised": {
                "type": "array",
                "items": pointer_schema({"ref": {"type": "string"}}),
            },
        },
        "outcome",
        "why",
    ),
]


class BrowserRunner(Runner):
    """Carries out the runner agent's page actions on one trial, under the rules here."""

    def __init__(
        self,
        binding: LoadedBinding,
        browser: Any,
        log: TransportLog,
        experiment_root: Path,
        *,
        llm_log: LLMCallLog,
        llm: AsyncOpenAI | None = None,
        storage_state: dict[str, Any] | None = None,
    ) -> None:
        self._binding = binding
        self._browser = browser
        self._log = log
        self._root = experiment_root
        self._llm_log = llm_log
        self._llm = llm
        self._owns_llm = False
        self.agent_settings = runner_agent_settings()
        """The runner agent role. ``setup`` resolves it from the trial's config."""
        self._storage_state = storage_state
        self._deadline = 0.0
        self._wait = 0.0
        self._turn = 0
        self._session_id: str | None = None
        self.spans = Spans.of("")
        self.context: Any = None
        self.page: Any = None
        self.snapshot = ""
        """The latest capture's snapshot, as logged (secrets already ``***``)."""
        self.refs: dict[str, tuple[str, str]] = {}
        """Ref to ``(role, name)`` for the latest snapshot; older refs are refused."""
        self.unquoted = False
        """Set when typing was refused because the action quoted no message;
        ``_observation`` reads it once."""
        self.typed: dict[str, str] = {}
        """Ref to the user's text typed and not yet sent."""
        self.choices: list[str] = []
        """The user's choices made and not yet sent."""
        self.results: list[str] = []
        """Capture entries, in order: what a pointer may cite."""
        self.open_submission: OpenSubmission | None = None
        """The submission nothing has settled yet; ``wait_for`` clears it."""
        self.notes: list[str] = []
        """What the agent learned about the page, shown again in each later action."""
        self.failures = 0
        """Page operations that raised; an action that saw one was not observed."""
        login = binding.binding.login
        names = login.secrets if login else []
        self._secrets = {
            env: value.get_secret_value()
            for env in names
            if (value := binding.secret(env)) is not None
        }
        self.handlers: dict[str, Handler] = {
            **SHARED_HANDLERS,
            **{
                name: self._handler(getattr(self, f"_tool_{name}"))
                for name in (
                    "snapshot",
                    "click",
                    "type",
                    "choose",
                    "choose_file",
                    "wait_for",
                    "fetch_files",
                )
            },
        }

    @staticmethod
    def _handler(tool: Any) -> Handler:
        async def call(_runner: Any, _state: ActionState, args: dict[str, Any]) -> Any:
            return await tool(args)

        return call

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def log(self) -> TransportLog:
        return self._log

    def record_session_id(self, pointer: Pointer) -> None:
        """Copy the session ID from a capture this trial logged.

        :raises PointerError: When the pointer does not lead to such a capture.
        """
        value, _ = resolve(pointer, self._log, allowed=self.results)
        self._session_id = str(value)

    async def setup(self, config: TrialConfig) -> None:
        """Open this trial's context from the logged-in state and the start page."""
        self.agent_settings = runner_agent_settings(
            config.runner_agent_model, user_agent_model=config.user_agent_model
        )
        self._deadline = _now() + config.timeout_minutes * 60
        self._wait = config.response_wait_ms / 1000
        self.context = await self._browser.new_context(
            storage_state=self._storage_state, accept_downloads=True
        )
        self.page = await self.context.new_page()
        start = self._binding.start_url
        action = self._action("open", {"url": start})
        try:
            await self.page.goto(start, wait_until="domcontentloaded", timeout=60_000)
        except Exception as exc:
            await self._capture(action, error=self._error(exc))
            raise TrialRecoverableError(
                f"the start page could not be opened ({action})"
            ) from None
        await self._capture(action)

    def begin_action(self, action: str) -> None:
        """Start a turn: number the action's quoted spans. ``act`` calls this first."""
        self._turn += 1
        self.spans = Spans.of(action)

    # ------------------------------------------------------------------ the log

    def _action(self, tool: str, detail: dict[str, Any]) -> str:
        label = " ".join(
            f"{k}={detail[k]}" for k in ("ref", "role", "name", "url") if k in detail
        )
        summary = " ".join(f"{tool} {label}".split())[:200]
        body = json.dumps({"tool": tool, **detail}, ensure_ascii=False).encode()
        return self._log.append("request", summary, body)

    async def _capture(
        self, action: str, *, error: str | None = None
    ) -> tuple[str, str]:
        """Log the page as a result of ``action``: its entry ID and the text for the agent."""
        try:
            title = await self.page.title()
            snapshot = await self.page.locator("body").aria_snapshot(
                mode="ai", timeout=15_000
            )
        except Exception as exc:
            title, snapshot = "", ""
            error = error or self._error(exc)
        snapshot = self._redact(snapshot)
        self.snapshot = snapshot
        self.refs = {}
        for line in snapshot.splitlines():
            if found := _REF_LINE.match(line):
                self.refs[found.group(3)] = (
                    found.group(1),
                    (found.group(2) or "").replace('\\"', '"'),
                )
        url = self.page.url
        body: dict[str, Any] = {"url": url, "title": title, "snapshot": snapshot}
        if error is not None:
            body["error"] = error
        entry = self._log.append(
            "response",
            f"capture {url} ({len(snapshot)} chars)" + (" ERROR" if error else ""),
            json.dumps(body, ensure_ascii=False).encode(),
            pairs_with=action,
        )
        self.results.append(entry)
        text = f"url: {url}\ntitle: {title}\n{snapshot}"
        return entry, text + (f"\nerror: {error}" if error else "")

    async def _done(
        self,
        action: str,
        extra: dict[str, Any] | None = None,
        *,
        error: str | None = None,
    ) -> dict[str, Any]:
        """Capture the page after ``action`` and return it as the tool's result."""
        entry, page = await self._capture(action, error=error)
        return {
            "action_entry": action,
            "capture_entry": entry,
            **(extra or {}),
            "page": page,
        }

    async def _failed(self, action: str, exc: Exception) -> dict[str, Any]:
        self.failures += 1
        return await self._done(action, error=self._error(exc))

    def _error(self, exc: Exception) -> str:
        return self._redact(f"{type(exc).__name__}: {exc}")[:300]

    def _redact(self, text: str) -> str:
        for value in self._secrets.values():
            text = text.replace(value, "***")
        return text

    # ------------------------------------------------------------------ the loop

    async def act(self, action: str, promised: list[Promise]) -> Observation:
        """Carry out ``action``: look at the page, run the agent, build the result.

        :raises TurnRecoverableError: When the runner agent's LLM cannot be reached.
        """
        self.begin_action(action)
        observation = await self._attempt(promised, signing_in=False)
        if observation.sent_nothing:
            self._turn -= 1  # the orchestrator does not count this action as a turn
        return observation

    async def sign_in(self) -> Observation:
        """Have the agent sign in as the binding's ``login`` says; not a user's action."""
        self.spans = Spans.of("")
        return await self._attempt([], signing_in=True)

    def has_password_field(self) -> bool:
        """Whether the page still shows a password box, which a signed-in page does not."""
        return _PASSWORD_BOX.search(self.snapshot) is not None

    async def _attempt(
        self, promised: list[Promise], *, signing_in: bool
    ) -> Observation:
        state = ActionState(
            first_result=len(self.results),
            turn="sign_in" if signing_in else self._turn,
        )
        failures = self.failures
        started = _now()
        limit = min(self._wait + ACT_MARGIN, max(0.0, self._deadline - started))
        _, page = await self._capture(self._action("snapshot", {}))
        stopped = await self._run_agent(
            state, promised, page, started, limit, signing_in
        )
        state.transport_failed = self.failures > failures
        return self._observation(state, stopped)

    async def _run_agent(
        self,
        state: ActionState,
        promised: list[Promise],
        page: str,
        started: float,
        limit: float,
        signing_in: bool,
    ) -> str | None:
        """Ask the LLM for tool calls until it reports. Returns why it stopped early."""
        if self._llm is None:
            self._llm = llm_client(self.agent_settings)
            self._owns_llm = True
        opened = self.open_submission
        messages: list[Any] = [
            {"role": "system", "content": BROWSER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": first_message(
                    binding=self._binding.binding,
                    page=page,
                    spans=self.spans,
                    files=self.ledger.artifacts(),
                    promised=promised,
                    open_submission=(
                        f"the submission logged as {opened.request} "
                        f"(shown in {opened.response})"
                        if opened
                        else None
                    ),
                    notes=self.notes,
                    session_id=self._session_id,
                    rounds=MAX_ROUNDS,
                    signing_in=signing_in,
                ),
            },
        ]
        nudged = False
        for round_number in range(1, MAX_ROUNDS + 1):
            if _now() - started >= limit:
                return "the action's time limit passed before the agent reported"
            sent = trimmed_pages(messages)
            logger.debug(
                "runner_agent_round",
                turn=state.turn,
                round=round_number,
                chars_sent=sent_chars(sent),
            )
            try:
                completion = await create_completion(
                    self._llm,
                    self._llm_log,
                    component="runner_agent",
                    model=self.agent_settings.model,
                    messages=sent,
                    tools=TOOLS,
                    tool_choice="required",
                )
            except openai.OpenAIError as exc:
                raise TurnRecoverableError(
                    f"the runner agent's LLM call failed: {type(exc).__name__}"
                ) from exc
            message = completion.choices[0].message
            calls = [c for c in message.tool_calls or [] if c.type == "function"]
            assistant: dict[str, Any] = {
                "role": "assistant",
                "content": message.content or "",
            }
            if calls:
                assistant["tool_calls"] = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {
                            "name": c.function.name,
                            "arguments": c.function.arguments or "{}",
                        },
                    }
                    for c in calls
                ]
            messages.append(assistant)
            if not calls and not nudged:
                nudged = True
                messages.append({"role": "user", "content": NUDGE})
            for call in calls:
                result = await run_tool(
                    self,
                    state,
                    call.function.name,
                    call.function.arguments,
                    self.handlers,
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
            if state.report is not None:
                return None
        return f"the agent did not report within {MAX_ROUNDS} rounds"

    def _observation(self, state: ActionState, stopped: str | None) -> Observation:
        """Build the result from what was logged; the agent's words only fill ``reading``."""
        notices: list[str] = []
        sent_nothing, self.unquoted = self.unquoted, False  # read once
        if sent_nothing:
            notices.append("Nothing was sent: your action quoted no message.")
        if self.open_submission is not None:
            notices.append(
                f"A submission ({self.open_submission.request}) is still open."
            )
        if state.transport_failed:
            notices.append("A page operation failed.")
        if stopped is not None:
            notices.append(stopped[0].upper() + stopped[1:] + ".")
        report = state.report
        return Observation(
            reply=report.reply if report else None,
            reading=report.reading
            if report
            else Reading(outcome="unknown", why="The runner agent did not report."),
            promised=report.promised if report else [],
            observed=self.open_submission is None and not state.transport_failed,
            notice=" ".join(notices) or None,
            sent_nothing=sent_nothing,
        )

    async def end_chat(self, promised: list[Promise]) -> None:
        """Does nothing: a page has no list of a session's files to collect afterwards.

        Files the page offered during a turn were fetched in that turn.
        """

    async def teardown(self) -> None:
        if self.context is not None:
            await self.context.close()
            self.context = self.page = None
        if self._owns_llm and self._llm is not None:
            await self._llm.close()  # the browser is the factory's

    # ------------------------------------------------------------------ tools

    def _element(self, ref: str) -> tuple[str, str]:
        if ref not in self.refs:
            raise ToolRefused(
                f"{ref!r} is not in the latest snapshot; take a snapshot and use its refs"
            )
        return self.refs[ref]

    def _locator(self, ref: str) -> Any:
        return self.page.locator(f"aria-ref={ref}")

    def _submits(self) -> list[str]:
        return list(self.typed.values()) + self.choices

    def _refuse_if_open(self) -> None:
        if self.open_submission is not None:
            raise ToolRefused(
                f"a submission ({self.open_submission.request}) is still open; "
                "settle it with wait_for first"
            )

    def _users_choice(self, raw: Any) -> str:
        """A choice is the user's only if they quoted it: ``{{n}}`` or the same words."""
        if not isinstance(raw, str) or not raw.strip():
            raise ToolRefused("give the user's choice")
        wanted = self.spans.substitute_text(raw).strip()
        if wanted.casefold() not in {t.strip().casefold() for t in self.spans.texts}:
            raise ToolRefused(
                f"the user did not choose {wanted!r}; only an option the user named "
                "can be picked"
            )
        return wanted

    async def _after_submit(self, action: str) -> dict[str, Any]:
        """The click or Enter that sends pending text: text that left its field was sent."""
        cleared: dict[str, bool] = {}
        for ref in self.typed:
            try:
                value = await self._locator(ref).input_value(timeout=2_000)
            except Exception:
                value = ""  # the field went away with the send
            cleared[ref] = value == ""
        sent = [text for ref, text in self.typed.items() if cleared[ref]] + self.choices
        result = await self._done(action, {"fields_cleared": cleared})
        if sent:
            self.open_submission = OpenSubmission(
                action, result["capture_entry"], self._turn
            )
            result["submission"] = "sent; it stays open until wait_for settles it"
        else:
            result["submission"] = "the text is still in the field: it was not sent"
        self.typed, self.choices = {}, []
        return result

    async def _tool_snapshot(self, args: dict[str, Any]) -> dict[str, Any]:
        return await self._done(self._action("snapshot", {}))

    async def _tool_click(self, args: dict[str, Any]) -> dict[str, Any]:
        ref = str(args.get("ref"))
        role, name = self._element(ref)
        choice = args.get("choice")
        if choice is not None:
            wanted = self._users_choice(choice)
            if wanted.casefold() != name.strip().casefold():
                raise ToolRefused(
                    f"the user chose {wanted!r}, but {ref} is {role} {name!r}"
                )
        elif role in _CHOICE_ROLES:
            raise ToolRefused(
                f"{ref} is a {role}: picking it is the user's choice; give it as `choice`"
            )
        submitting = role in _CLICKABLE and bool(self._submits() or choice)
        if submitting:
            self._refuse_if_open()
        action = self._action("click", {"ref": ref, "role": role, "name": name})
        try:
            await self._locator(ref).click(timeout=15_000)
        except Exception as exc:
            return await self._failed(action, exc)
        if choice is not None:
            self.choices.append(name)
        if submitting:
            return await self._after_submit(action)
        return await self._done(action)

    async def _tool_type(self, args: dict[str, Any]) -> dict[str, Any]:
        ref = str(args.get("ref"))
        role, name = self._element(ref)
        raw = str(args.get("text", ""))
        secret = secret_name(raw, self._secrets.keys() | self._listed_secrets())
        if secret is not None:
            text, logged, users = self._secrets[secret], "***", False
        else:
            if not self.spans.texts:
                self.unquoted = True
                raise ToolRefused(
                    "the user's action quoted nothing to send, so nothing may be typed"
                )
            text = logged = self.spans.substitute_text(raw)
            users = True
        enter = bool(args.get("press_enter"))
        if enter and users:
            self._refuse_if_open()
        action = self._action(
            "type",
            {
                "ref": ref,
                "role": role,
                "name": name,
                "text": logged,
                "press_enter": enter,
            },
        )
        try:
            await self._locator(ref).fill(text, timeout=15_000)
            if users:
                self.typed[ref] = text
            if enter:
                await self._locator(ref).press("Enter", timeout=15_000)
        except Exception as exc:
            return await self._failed(action, exc)
        if enter and self._submits():
            return await self._after_submit(action)
        return await self._done(action)

    def _listed_secrets(self) -> set[str]:
        login = self._binding.binding.login
        return set(login.secrets) if login else set()

    async def _tool_choose(self, args: dict[str, Any]) -> dict[str, Any]:
        ref = str(args.get("ref"))
        role, name = self._element(ref)
        wanted = self._users_choice(args.get("choice"))
        options = self._options_under(ref)
        match = next((o for o in options if o.casefold() == wanted.casefold()), None)
        if match is None:
            raise ToolRefused(
                f"{wanted!r} is not one of the options of {ref}: {options}"
            )
        action = self._action(
            "choose", {"ref": ref, "role": role, "name": name, "choice": match}
        )
        try:
            await self._locator(ref).select_option(label=match, timeout=15_000)
        except Exception as exc:
            return await self._failed(action, exc)
        self.choices.append(match)
        return await self._done(action)

    def _options_under(self, ref: str) -> list[str]:
        lines = self.snapshot.splitlines()
        start = next((i for i, ln in enumerate(lines) if f"[ref={ref}]" in ln), None)
        if start is None:
            return []
        indent = len(lines[start]) - len(lines[start].lstrip())
        options: list[str] = []
        for line in lines[start + 1 :]:
            if line.strip() and len(line) - len(line.lstrip()) <= indent:
                break
            if found := re.match(r'\s*-\s+option\s+"((?:[^"\\]|\\.)*)"', line):
                options.append(found.group(1))
        return options

    async def _tool_choose_file(self, args: dict[str, Any]) -> dict[str, Any]:
        ref = str(args.get("ref"))
        role, name = self._element(ref)
        wanted = str(args.get("file", ""))
        held = next(
            (
                a
                for a in self.ledger.artifacts()
                if a.name == wanted and a.source == "fixture" and a.path
            ),
            None,
        )
        if held is None or held.path is None:
            raise ToolRefused(f"{wanted!r} is not a file you hold")
        path = str(self._root / held.path)
        action = self._action(
            "choose_file", {"ref": ref, "role": role, "name": name, "file": held.name}
        )
        accepted, error = False, None
        try:
            await self._locator(ref).set_input_files(path, timeout=5_000)
            accepted = True
        except Exception:  # not an <input type=file>: the control opens a chooser
            try:
                async with self.page.expect_file_chooser(timeout=10_000) as info:
                    await self._locator(ref).click(timeout=10_000)
                chooser = await info.value
                await chooser.set_files(path)
                accepted = True
            except Exception as exc:
                self.failures += 1
                error = self._error(exc)
        await _sleep(UPLOAD_SETTLE)
        result = await self._done(action, {"file_accepted": accepted}, error=error)
        # recorded only when the control took the file and the page then shows its name
        if accepted and held.name in self.snapshot:
            self.ledger.record_upload(held.name, at_simulated_turn=self._turn)
            result["ledger"] = "recorded upload"
        else:
            result["ledger"] = "not recorded: " + (
                "the page does not show the file's name"
                if accepted
                else "the file was not taken"
            )
        return result

    async def _tool_wait_for(self, args: dict[str, Any]) -> dict[str, Any]:
        keys = ("text_present", "text_absent", "ref_absent", "stable_seconds")
        condition: dict[str, Any] = {
            k: args[k] for k in keys if args.get(k) is not None
        }
        if not condition:
            condition = {"stable_seconds": STABLE_DEFAULT}
        stable_for = float(condition.get("stable_seconds") or 0)
        stop_at = _now() + min(self._wait, max(0.0, self._deadline - _now()))
        last: str | None = None
        since = _now()
        while True:
            try:
                snapshot = self._redact(
                    await self.page.locator("body").aria_snapshot(
                        mode="ai", timeout=15_000
                    )
                )
            except Exception:
                snapshot = ""
            if snapshot != last:
                last, since = snapshot, _now()
            holds = (
                not busy(snapshot)
                and (
                    condition.get("text_present") is None
                    or condition["text_present"] in snapshot
                )
                and (
                    condition.get("text_absent") is None
                    or condition["text_absent"] not in snapshot
                )
                and (
                    condition.get("ref_absent") is None
                    or f"[ref={condition['ref_absent']}]" not in snapshot
                )
                and (not stable_for or _now() - since >= stable_for)
            )
            if holds or _now() + POLL_INTERVAL > stop_at:
                action = self._action("wait_for", {"condition": condition})
                if holds:
                    self.open_submission = None
                result = await self._done(
                    action,
                    {"condition": "holds" if holds else "timed out; still waiting"},
                )
                result["pending"] = self.open_submission is not None
                return result
            await _sleep(POLL_INTERVAL)

    async def _tool_fetch_files(self, args: dict[str, Any]) -> dict[str, Any]:
        refs = [str(r) for r in args.get("links") or []]
        if not refs:
            raise ToolRefused("give the refs of the download links")
        for ref in refs:
            role, _ = self._element(ref)
            if role not in _CLICKABLE:
                raise ToolRefused(f"{ref} is a {role}, not a link or button")
        action = self._action("fetch_files", {"links": refs})
        held = {
            a.name
            for a in self.ledger.artifacts()
            if a.source == "target" and a.state == "received"
        }
        files: list[dict[str, Any]] = []
        for ref in refs:
            try:
                async with self.page.expect_download(timeout=30_000) as info:
                    await self._locator(ref).click(timeout=15_000)
                download = await info.value
                name = download.suggested_filename
                data = (await download.path()).read_bytes()
            except Exception as exc:
                self.failures += 1
                files.append(
                    {
                        "ref": ref,
                        "state": "no download started",
                        "why": self._error(exc),
                    }
                )
                continue
            if name in held:
                files.append({"name": name, "skipped": "already held"})
                continue
            try:
                self.ledger.record_download(name, data, at_simulated_turn=self._turn)
            except ArtifactRejected as exc:
                self.ledger.record_failure(
                    name, "unfetched", str(exc), at_simulated_turn=self._turn
                )
                files.append({"name": name, "state": "unfetched", "why": str(exc)})
                continue
            held.add(name)
            files.append({"name": name, "state": "received"})
        return await self._done(action, {"files": files})


class BrowserRunnerFactory:
    """Builds :class:`BrowserRunner`s for the app the specification's browser binding names."""

    def __init__(
        self,
        binding: LoadedBinding,
        *,
        login_dir: Path,
        browser: Any = None,
        llm: AsyncOpenAI | None = None,
        user_agent_model: str | None = None,
        runner_agent_model: str | None = None,
    ) -> None:
        self._binding = binding
        self._login_dir = login_dir
        """Where the sign-in's transport and LLM logs go: it belongs to no trial."""
        self._models = {
            "user_agent_model": user_agent_model,
            "runner_agent_model": runner_agent_model,
        }
        """The Specification defaults. The sign-in belongs to no trial, so it uses them."""
        self._browser = browser
        """Replaced by a fake in tests; otherwise ``start`` launches Chromium."""
        self._llm = llm
        """Replaced by a fake in tests; otherwise each runner builds its own client."""
        self._playwright: Any = None
        self._storage_state: dict[str, Any] | None = None
        """The logged-in state. A credential: kept in memory, never written."""

    @property
    def binding(self) -> LoadedBinding:
        return self._binding

    @classmethod
    def from_specification(
        cls, specification: Specification, inputs_dir: Path
    ) -> BrowserRunnerFactory:
        """Load ``specification.target_binding`` from the experiment's ``inputs_dir``.

        :raises TargetBindingError: When the specification names no binding, or the
            binding cannot be loaded or is not a browser binding.
        """
        if specification.target_binding is None:
            raise TargetBindingError(
                "BrowserRunnerFactory needs the specification's target_binding, "
                "which is not set"
            )
        binding = load_target_binding(
            inputs_dir, specification.target_binding, "browser"
        )
        defaults = specification.experiment.defaults
        return cls(
            binding,
            login_dir=inputs_dir.parent / "logs" / "login",
            user_agent_model=defaults.user_agent_model,
            runner_agent_model=defaults.runner_agent_model,
        )

    @property
    def retry_defaults(self) -> tuple[int, float]:
        defaults = TrialRetryConfig()
        return defaults.trial_max_retries, defaults.trial_retry_delay_seconds

    async def start(self) -> None:
        """Launch the browser every trial shares, and sign in once if the binding says how.

        :raises TargetBindingError: When the sign-in does not finish.
        """
        if self._browser is None:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
        if self._binding.binding.login is not None:
            await self._sign_in()

    async def _sign_in(self) -> None:
        runner = BrowserRunner(
            self._binding,
            self._browser,
            TransportLog.for_trial(self._login_dir),
            self._login_dir,
            llm_log=LLMCallLog.for_trial(self._login_dir),
            llm=self._llm,
        )
        runner.use_ledger(ArtifactLedger(self._login_dir, self._login_dir))
        try:
            await runner.setup(
                TrialConfig(persona="login", scenario="login", **self._models)
            )
            observation = await runner.sign_in()
            if observation.reading.outcome != "done" or runner.has_password_field():
                raise TargetBindingError(
                    "the login did not finish: "
                    f"{observation.reading.outcome}: {observation.reading.why} "
                    f"(see {self._login_dir})"
                )
            self._storage_state = await runner.context.storage_state()
        finally:
            await runner.teardown()

    async def create(
        self, run_dir: Path, fixtures_dir: Path, experiment_root: Path
    ) -> BrowserRunner:
        """A runner whose actions are logged to this trial's own transport log."""
        assert self._browser is not None, "start() must run before create()"
        return BrowserRunner(
            self._binding,
            self._browser,
            TransportLog.for_trial(run_dir),
            experiment_root,
            llm_log=LLMCallLog.for_trial(run_dir),
            llm=self._llm,
            storage_state=self._storage_state,
        )

    async def close(self) -> None:
        self._storage_state = None
        if self._playwright is not None:
            await self._browser.close()
            await self._playwright.stop()
            self._browser = self._playwright = None
