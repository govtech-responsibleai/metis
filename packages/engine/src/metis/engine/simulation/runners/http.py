"""The generic HTTP runner: the request tool and the rules code enforces on it.

``HttpRunnerFactory`` loads the specification's target binding and holds one HTTP
transport for every trial. Its runner fetches the target's OpenAPI specification once,
and ``http_request`` is the one call the runner agent makes on the target: code checks
the path, the headers and the binding's rules, substitutes the user's quoted words,
adds the credentials, and records which responses answered a submission. ``poll_until``
waits for a submission's reply and ``fetch_files`` downloads the files this conversation
produced. ``act`` runs the runner agent's loop over those tools and builds the
``Observation`` from the evidence the tools logged.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import time
from dataclasses import dataclass
from json import loads
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urljoin, urlsplit

import httpx
import openai
from openai import AsyncOpenAI

from metis.core.logging import get_logger
from metis.core.target_binding import call_matches

from ..artifacts import ArtifactRejected
from ..binding import TargetBindingError, load_target_binding
from ..config import TrialRetryConfig
from ..evidence import Pointer, PointerError, resolve
from ..exceptions import TurnRecoverableError
from ..llm_calls import LLMCallLog, create_completion
from ..model_settings import llm_client, runner_agent_settings
from ..runner import Runner
from ..transport_log import LoggingTransport, TransportLog
from ..types import Observation, Reading
from .prompts import NUDGE, SYSTEM_PROMPT, first_message
from .rules import SUBMIT_METHODS, ToolRefused, check_call, check_headers
from .spans import Spans
from .tools import TOOLS, ActionState, operation_index, run_tool

if TYPE_CHECKING:
    from metis.core.specification import Specification
    from metis.core.trials import TrialConfig

    from ..artifacts import ArtifactLedger
    from ..binding import LoadedBinding
    from ..transport_log import LogEntry
    from ..types import Promise

logger = get_logger()

MAX_429_RESENDS = 3
_TIMEOUT = httpx.Timeout(60.0)
MAX_FILES_PER_LISTING = 100
"""A conversation does not produce more files than this; a bigger listing is not its own."""
POLL_INTERVAL = 5.0
"""Seconds between polls; the binding and ``TrialConfig`` have no field for it."""
REJECTION_EXCERPT = 200
"""How much of a refusing response's body the user agent is shown."""
MAX_ROUNDS = 12
"""Most LLM rounds one action may take."""
ACT_MARGIN = 60.0
"""Seconds added to ``response_wait_ms`` for one action's time limit."""
_MEDIA_TYPES = {".md": "text/markdown", ".markdown": "text/markdown"}
"""Extensions the standard library's table lacks, so an upload is not sent as octet-stream."""
_sleep = asyncio.sleep  # names tests replace
_now = time.monotonic


@dataclass(frozen=True)
class OpenSubmission:
    """A submission the target accepted and nothing has settled yet.

    ``poll_until`` settles it, or a ``report`` whose ``submission`` says it is answered.
    """

    request: str
    """The transport-log entry of the request."""
    response: str
    """The entry of the response that accepted it."""
    turn: int
    status: int | None = None
    """The status of that response, when the runner knows it."""


@dataclass(frozen=True)
class Unresolved:
    """A submission a poll could not settle because the target answered it with a 4xx."""

    submission: OpenSubmission
    response: str
    """The entry of the response that showed the failure."""


@dataclass(frozen=True)
class Rejected:
    """A submission the target refused: its response was not a 2xx."""

    response: str
    """The entry of the refusing response."""
    status: int
    excerpt: str
    """The start of the response body, copied from the transport log."""


class HttpRunner(Runner):
    """Carries out the runner agent's HTTP calls on one trial, under the binding's rules."""

    def __init__(
        self,
        binding: LoadedBinding,
        client: httpx.AsyncClient,
        log: TransportLog,
        experiment_root: Path,
        *,
        llm_log: LLMCallLog,
        llm: AsyncOpenAI | None = None,
    ) -> None:
        self._binding = binding
        self._client = client
        self._log = log
        self._root = experiment_root
        self._llm_log = llm_log
        self._llm = llm
        self._owns_llm = False
        self.agent_settings = runner_agent_settings()
        """The runner agent role. ``setup`` resolves it from the trial's config."""
        self._base = ""
        self._deadline = 0.0
        self._wait = 0.0
        self._last_poll: tuple[str, str, list[Any] | None, list[Any] | None] | None = (
            None
        )
        self._turn = 0
        self._session_id: str | None = None
        self._action_start = 0
        self.spans = Spans.of("")
        self.spec_entry = ""
        """The log entry holding the specification: the target's description, not an answer."""
        self.document: dict[str, Any] = {}
        """The parsed specification; ``operation`` reads definitions from it."""
        self.results: list[str] = []
        """Response entries of the agent's calls, in order: what a pointer may cite."""
        self.answers: list[str] = []
        """Response entries that accepted a submission. #525 uses them to tell this
        conversation's listings from an account-wide one."""
        self.open_submission: OpenSubmission | None = None
        """The accepted submission nothing has settled yet; ``poll_until`` clears it, and
        so does ``settle_answered``."""
        self.unresolved: Unresolved | None = None
        """Set by a 4xx during a poll while a submission was open; a timeout leaves it open."""
        self.rejected: Rejected | None = None
        """Set when a submission got a non-2xx response; ``_observation`` reads it once."""
        self.unquoted = False
        """Set when a submission was refused because the action quoted no message;
        ``_observation`` reads it once."""
        self.notes: list[str] = []
        """What the agent learned about the target, shown again in each later action."""

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def log(self) -> TransportLog:
        return self._log

    def use_ledger(self, ledger: ArtifactLedger) -> None:
        self.ledger = ledger

    async def setup(self, config: TrialConfig) -> None:
        """Fetch and log the specification, once, and work out the server URL."""
        self.agent_settings = runner_agent_settings(
            config.runner_agent_model, user_agent_model=config.user_agent_model
        )
        self._deadline = _now() + config.timeout_minutes * 60
        self._wait = config.response_wait_ms / 1000
        url = self._binding.spec_url
        parts = urlsplit(url)
        if parts.scheme in ("http", "https") and not parts.netloc:
            raise TargetBindingError(
                f"spec_url {self._binding.binding.spec_url!r} has no host"
            )
        if parts.scheme == "file":
            raw = Path(unquote(parts.path)).read_bytes()
            request = self._log.append("request", "GET (specification file)", b"")
            self.spec_entry = self._log.append(
                "response", "GET (specification file) -> 200", raw, pairs_with=request
            )
        else:
            response = await self._client.get(url)
            self.spec_entry = self._log.last_id() or ""
            if not response.is_success:
                raise TargetBindingError(
                    f"the specification could not be fetched: {response.status_code}"
                )
            raw = response.content
        self.document = loads(raw)
        servers = self.document.get("servers") or [{"url": "/"}]
        self._base = urljoin(url, str(servers[0].get("url") or "/")).rstrip("/")
        if not self._base.startswith(("http://", "https://")):
            raise TargetBindingError(
                "the specification's first server is not an http(s) URL; "
                "a file spec needs an absolute one"
            )

    def begin_action(self, action: str) -> None:
        """Start a turn: number the action's quoted spans. ``act`` calls this first."""
        self._turn += 1
        self._action_start = len(self.results)
        self.spans = Spans.of(action)

    def record_session_id(self, pointer: Pointer) -> None:
        """Copy the session ID from a submission's response or from this action's calls.

        A target that opens its session before any message shows the ID in a call that
        is not a submission, so the action's own results are citable too.

        :raises PointerError: When the pointer does not lead to such a response.
        """
        allowed = [*self.answers, *self.results[self._action_start :]]
        value, _ = resolve(pointer, self._log, allowed=allowed)
        self._session_id = str(value)
        logger.info(
            "session_id_found", session_id=self._session_id, entry=pointer.entry
        )

    async def http_request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        json: Any = None,
        multipart: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        file_id_from: str | None = None,
    ) -> dict[str, Any]:
        """Send one request for the runner agent, if the rules allow it.

        :param path: As the specification writes it; code joins it to the server.
        :param json: A body; ``{{n}}`` stands for the user's n-th quoted span.
        :param multipart: Part name to value; ``@name`` is a held file, anything else
            text that may hold placeholders.
        :param file_id_from: A JSON path (``$.fileId``) into the response of a
            one-file upload; code copies the target's ID for the file from it, so
            ``fetch_files`` can tell the user's own upload from the target's files.
        :raises ToolRefused: Whatever breaks a rule; nothing is sent.
        """
        method = method.upper()
        check_call(method, path, self._binding.binding.forbidden_calls)
        extra = check_headers(headers)
        for part, value in (multipart or {}).items():
            if not isinstance(value, str):
                raise ToolRefused(f"multipart part {part!r} must be text or @filename")
        uploads = [v[1:] for v in (multipart or {}).values() if v.startswith("@")]
        if file_id_from is not None and len(uploads) != 1:
            raise ToolRefused(
                "file_id_from needs a multipart request that uploads exactly one held file"
            )
        if json is not None and multipart is not None:
            raise ToolRefused("send json or multipart, not both")
        submission = self._is_submission(method, path, json is not None)
        if submission and self.open_submission is not None:
            raise ToolRefused(
                f"a submission ({self.open_submission.request}) is still open; "
                "it must settle before another is sent"
            )
        if submission and not self.spans.texts:
            self.unquoted = True
            raise ToolRefused(
                "the user's action quoted nothing to send, so nothing may be submitted"
            )
        body = self.spans.substitute(json)
        data, files = self._multipart(multipart)

        wire = {**extra, **self._credentials(method, path)}
        response = await self._send(
            method, path, wire, query, body if json is not None else None, data, files
        )
        response_id = self._log.last_id() or ""
        request_id = self._log.get(response_id).pairs_with or ""
        self.results.append(response_id)
        if submission and response.is_success:
            self.open_submission = OpenSubmission(
                request_id, response_id, self._turn, response.status_code
            )
            self.answers.append(response_id)
        elif submission:
            self.rejected = Rejected(
                response_id,
                response.status_code,
                " ".join(_preview(response).split())[:REJECTION_EXCERPT],
            )
        reply: dict[str, Any] = {
            "request_entry": request_id,
            "response_entry": response_id,
            "status": response.status_code,
            "body": _preview(response),
        }
        if file_id_from is not None and response.is_success:
            try:
                value, _ = resolve(Pointer(response_id, file_id_from), self._log)
            except PointerError as exc:
                reply["file_id_error"] = str(exc)
            else:
                self.ledger.record_upload(
                    uploads[0], at_simulated_turn=self._turn, external_id=str(value)
                )
                reply["file_id"] = str(value)
        return reply

    def settle_answered(self) -> None:
        """Close the open submission because the runner agent read its reply in the response.

        :raises ToolRefused: When the response was a 202, which promises the reply later.
        """
        opened = self.open_submission
        if opened is None:
            return
        if opened.status not in (200, 201):
            raise ToolRefused(
                f"the submission was accepted with {opened.status}, which means the reply "
                "comes later: settle it with `poll_until`"
            )
        self.open_submission = None
        logger.info("submission_answered", entry=opened.response)

    async def poll_until(
        self,
        path: str,
        at: str,
        *,
        not_in: list[Any] | None = None,
        in_: list[Any] | None = None,
    ) -> dict[str, Any]:
        """``GET path`` every few seconds until the JSON value at ``at`` settles.

        :param not_in: Values that mean still waiting; anything else is done.
        :param in_: Values that mean done; anything else is still waiting.
        :raises ToolRefused: Unless exactly one of ``not_in`` and ``in_`` is given, or
            when the path breaks a rule.
        """
        if (not_in is None) == (in_ is None):
            raise ToolRefused(
                "give exactly one of not_in (values that mean still waiting) "
                "or in_ (values that mean done)"
            )
        check_call("GET", path, self._binding.binding.forbidden_calls)
        self._last_poll = (path, at, not_in, in_)
        stop_at = _now() + min(self._wait, max(0.0, self._deadline - _now()))
        wire = self._credentials("GET", path)
        polls = 0
        while True:
            response = await self._send("GET", path, wire, None, None, None, None)
            polls += 1
            response_id = self._log.last_id() or ""
            self.results.append(response_id)
            reply: dict[str, Any] = {
                "response_entry": response_id,
                "status": response.status_code,
                "polls": polls,
                "body": _preview(response),
            }
            if response.status_code != 429:  # _send waited it out; carry on
                if not response.is_success:
                    # A 405 is the runner's own wrong method, not the target's failure.
                    if (
                        400 <= response.status_code < 500
                        and response.status_code != 405
                        and self.open_submission
                    ):
                        self.unresolved = Unresolved(self.open_submission, response_id)
                        self.open_submission = None
                    return reply
                try:
                    value, _ = resolve(Pointer(response_id, at), self._log)
                except PointerError as exc:
                    return {**reply, "error": str(exc)}
                waiting = (
                    value in not_in if not_in is not None else value not in (in_ or [])
                )
                if not waiting:
                    self.open_submission = None
                    return {**reply, "condition": "holds", "value": value}
            if _now() + POLL_INTERVAL > stop_at:
                return {
                    **reply,
                    "condition": "timed out; the submission is still open",
                }
            await _sleep(POLL_INTERVAL)

    async def fetch_files(
        self,
        listing: Pointer,
        id_key: str,
        name_key: str,
        download_path: str,
        where: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Download the files in one logged listing of this conversation's files.

        Code copies each item's ID and name from the listing, sends one ``GET`` per file
        and records what came back; the agent never points at bytes.

        :param listing: Points at an array in a logged result.
        :param download_path: The file's path with exactly one ``{id}``.
        :param where: Keeps only the items whose keys have these values.
        :raises ToolRefused: When the listing is not an array, is not this
            conversation's, is over the cap, or the path breaks a rule.
        :raises PointerError: When the pointer leads nowhere.
        """
        items, entry = resolve(listing, self._log, allowed=self.results)
        if not isinstance(items, list):
            raise ToolRefused("`listing` must point at an array of files")
        if not self._is_this_conversations(entry):
            raise ToolRefused(
                f"{entry.id} is not part of this conversation (it answers no submission "
                "and its request does not name this session); list the session's own "
                "files instead"
            )
        if download_path.count("{id}") != 1:
            raise ToolRefused("download_path needs exactly one {id}")
        forbidden = self._binding.binding.forbidden_calls
        check_call("GET", download_path.replace("{id}", "x"), forbidden)
        if len(items) > MAX_FILES_PER_LISTING:
            raise ToolRefused(
                f"{entry.id} lists {len(items)} files, more than one conversation makes "
                f"(limit {MAX_FILES_PER_LISTING}); list the session's own files"
            )
        held = self.ledger.artifacts()
        uploaded = {a.external_id for a in held if a.source == "fixture"}
        received = {
            a.external_id
            for a in held
            if a.source == "target" and a.state == "received"
        }
        files: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict) or any(
                item.get(k) != v for k, v in (where or {}).items()
            ):
                continue
            name, raw_id = item.get(name_key), item.get(id_key)
            if not isinstance(name, str) or not name:
                files.append(_skipped(None, "no name in the listing"))
            elif raw_id in (None, ""):
                self.ledger.record_failure(
                    name,
                    "unavailable",
                    f"listed with no ID in {entry.id}",
                    at_simulated_turn=self._turn,
                )
                files.append({"name": name, "outcome": "unavailable"})
            elif str(raw_id) in uploaded:
                files.append(_skipped(name, "the user's own upload"))
            elif str(raw_id) in received:
                files.append(_skipped(name, "already held"))
            elif "/" in str(raw_id) or ".." in str(raw_id):
                files.append(_skipped(name, "an ID that is not a single path segment"))
            else:
                done = await self._download(name, str(raw_id), download_path)
                if done["outcome"] == "received":
                    received.add(str(raw_id))
                files.append(done)
        return {"listing": entry.id, "files": files}

    def _is_this_conversations(self, entry: LogEntry) -> bool:
        """Whether a result answers a submission or names this session in its request."""
        if entry.id in self.answers:
            return True
        if self._session_id is None or entry.pairs_with is None:
            return False
        summary = self._log.get(entry.pairs_with).summary  # METHOD /path
        return self._session_id in summary.partition(" ")[2].split("/")

    async def _download(self, name: str, file_id: str, template: str) -> dict[str, Any]:
        """One file: a ``GET``, the byte check and the ledger entry, received or not."""
        path = template.replace("{id}", file_id)
        try:
            check_call("GET", path, self._binding.binding.forbidden_calls)
        except ToolRefused as exc:
            return _skipped(name, str(exc))
        response = await self._send(
            "GET", path, self._credentials("GET", path), None, None, None, None
        )
        response_id = self._log.last_id() or ""
        problem = None if response.is_success else self._log.get(response_id).summary
        if problem is None:
            try:
                self.ledger.record_download(
                    name,
                    response.content,
                    at_simulated_turn=self._turn,
                    external_id=file_id,
                    content_type=response.headers.get("content-type"),
                )
            except ArtifactRejected as exc:
                problem = str(exc)
        if problem is not None:
            self.ledger.record_failure(
                name,
                "unfetched",
                problem,
                at_simulated_turn=self._turn,
                external_id=file_id,
            )
        outcome = "received" if problem is None else "unfetched"
        return {"name": name, "outcome": outcome, "entry": response_id}

    async def resume_poll(self) -> dict[str, Any] | None:
        """Repeat the last poll if a submission is still open; ``act`` calls it first."""
        if self.open_submission is None or self._last_poll is None:
            return None
        path, at, not_in, in_ = self._last_poll
        return await self.poll_until(path, at, not_in=not_in, in_=in_)

    def _is_submission(self, method: str, path: str, has_json: bool) -> bool:
        patterns = self._binding.binding.submissions
        if patterns:
            return any(call_matches(p, method, path) for p in patterns)
        return method in SUBMIT_METHODS and has_json

    def _multipart(
        self, parts: dict[str, str] | None
    ) -> tuple[dict[str, str] | None, dict[str, tuple[str, bytes, str]] | None]:
        if parts is None:
            return None, None
        data: dict[str, str] = {}
        files: dict[str, tuple[str, bytes, str]] = {}
        for part, value in parts.items():
            if not value.startswith("@"):
                data[part] = self.spans.substitute_text(value)
                continue
            name = value[1:]
            held = next((a for a in self.ledger.artifacts() if a.name == name), None)
            if held is None or held.path is None:
                raise ToolRefused(f"{name!r} is not a file you hold")
            kind = _media_type(name)
            files[part] = (name, (self._root / held.path).read_bytes(), kind)
            self.ledger.record_upload(name, at_simulated_turn=self._turn)
        return data or None, files or None

    def _credentials(self, method: str, path: str) -> dict[str, str]:
        """The headers code adds. A secret that is not set adds nothing."""
        binding = self._binding
        found: dict[str, str] = {}
        if binding.binding.auth and (
            key := binding.secret(binding.binding.auth.secret_env)
        ):
            found["Authorization"] = f"Bearer {key.get_secret_value()}"
        for rule in binding.binding.secret_headers:
            value = binding.secret(rule.env)
            if value is not None and call_matches(rule.match, method, path):
                found[rule.header] = value.get_secret_value()
        return found

    async def _send(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        query: dict[str, Any] | None,
        body: Any,
        data: dict[str, str] | None,
        files: dict[str, tuple[str, bytes, str]] | None,
    ) -> httpx.Response:
        """Send, resending a 429 after its ``Retry-After`` while the trial has time."""
        for attempt in range(MAX_429_RESENDS + 1):
            response = await self._client.request(
                method,
                self._base + path,
                params=query,
                headers=headers,
                json=body,
                data=data,
                files=files,
            )
            if response.status_code != 429 or attempt == MAX_429_RESENDS:
                break
            wait = _retry_after(response)
            if wait > self._deadline - _now():
                break
            await _sleep(wait)
        return response

    async def act(self, action: str, promised: list[Promise]) -> Observation:
        """Carry out ``action``: settle an open submission, run the agent, build the result.

        :raises TurnRecoverableError: When the runner agent's LLM cannot be reached.
        """
        self.begin_action(action)
        observation = await self._attempt(promised, closing=False)
        if observation.sent_nothing:
            self._turn -= 1  # the orchestrator does not count this action as a turn
        return observation

    async def _attempt(self, promised: list[Promise], *, closing: bool) -> Observation:
        """The loop ``act`` and ``end_chat`` share: resume, run the agent, observe."""
        state = ActionState(
            first_result=len(self.results), turn="closing" if closing else self._turn
        )
        started = _now()
        limit = min(self._wait + ACT_MARGIN, max(0.0, self._deadline - started))
        try:
            await self.resume_poll()
        except httpx.TransportError:
            state.transport_failed = True
        stopped = await self._run_agent(state, promised, started, limit, closing)
        return self._observation(state, stopped)

    async def _run_agent(
        self,
        state: ActionState,
        promised: list[Promise],
        started: float,
        limit: float,
        closing: bool,
    ) -> str | None:
        """Ask the LLM for tool calls until it reports. Returns why it stopped early."""
        if self._llm is None:
            self._llm = llm_client(self.agent_settings)
            self._owns_llm = True
        messages: list[Any] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": self._first_message(promised, closing)},
        ]
        nudged = False
        for round_number in range(1, MAX_ROUNDS + 1):
            if _now() - started >= limit:
                return "the action's time limit passed before the agent reported"
            sent = trimmed(messages)
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
                    self, state, call.function.name, call.function.arguments
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

    def _first_message(self, promised: list[Promise], closing: bool) -> str:
        opened = self.open_submission
        specification = operation_index(self.document)
        indexed = bool(specification)
        if not indexed:  # nothing to list, so the agent gets the text
            specification = self._log.body_bytes(self._log.get(self.spec_entry)).decode(
                "utf-8", errors="replace"
            )
        return first_message(
            binding=self._binding.binding,
            specification=specification,
            indexed=indexed,
            spans=self.spans,
            files=self.ledger.artifacts(),
            promised=promised,
            open_submission=(
                f"the submission logged as {opened.request} (accepted in {opened.response})"
                if opened
                else None
            ),
            notes=self.notes,
            session_id=self._session_id,
            rounds=MAX_ROUNDS,
            closing=closing,
        )

    def _observation(self, state: ActionState, stopped: str | None) -> Observation:
        """Build the result from what was logged; the agent's words only fill ``reading``."""
        notices: list[str] = []
        unsettled = (unresolved := self.unresolved) is not None
        if unresolved is not None:
            self.unresolved = None  # read once; #524 never clears it
            notices.append(
                f"A submission ({unresolved.submission.request}) never settled: the "
                f"target answered the poll with a failure ({unresolved.response})."
            )
        if (rejected := self.rejected) is not None:
            self.rejected = None  # read once, like ``unresolved``
            notices.append(
                f"Your message got an error response (status {rejected.status}): "
                f"{rejected.excerpt}"
            )
        sent_nothing, self.unquoted = self.unquoted, False  # read once
        if sent_nothing:
            notices.append("Nothing was sent: your action quoted no message.")
        if state.answered and (state.report is None or state.report.reply is None):
            notices.append(
                "The target answered the submission, but no reply was recorded: the "
                "report cited none that its response holds."
            )
        if self.open_submission is not None:
            notices.append(
                f"A submission ({self.open_submission.request}) is still open."
            )
        if state.transport_failed:
            notices.append("A call to the target failed at the transport.")
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
            submission_unresolved=unsettled,
            sent_nothing=sent_nothing,
        )

    async def end_chat(self, promised: list[Promise]) -> None:
        """Collect what the target made available, then give up on the rest.

        Not a turn: ``begin_action`` is not called, so files are recorded under the last
        turn's number, and with no quoted words code refuses any submission. The agent's
        report is discarded.

        :raises TurnRecoverableError: When the runner agent's LLM cannot be reached.
        """
        self.spans = Spans.of("")
        try:
            await self._attempt(promised, closing=True)
        finally:
            held = {
                a.name
                for a in self.ledger.artifacts()
                if a.source == "target" and a.state == "received"
            }
            for p in promised:
                if p.name not in held:
                    self.ledger.record_failure(
                        p.name,
                        "unavailable",
                        f"promised in turn {p.turn}, never delivered",
                        at_simulated_turn=self._turn,
                    )

    async def teardown(self) -> None:
        if self._owns_llm and self._llm is not None:
            await self._llm.close()  # the HTTP transport is the factory's


def sent_chars(messages: list[Any]) -> int:
    """The characters of ``messages`` as the model receives them: what a round costs."""
    return len(json.dumps(messages, ensure_ascii=False))


def trimmed(messages: list[Any]) -> list[Any]:
    """A copy of ``messages`` with the bodies of earlier rounds' results shortened.

    The agent points at log entries, never at message text, so a body it has already
    read is replaced by the entry that holds it. The latest round, errors, statuses and
    entry IDs stay whole; ``messages`` itself is not changed.
    """
    last = max(
        (i for i, m in enumerate(messages) if m["role"] == "assistant"), default=0
    )
    sent = list(messages)
    for i, message in enumerate(messages[:last]):
        if message["role"] != "tool":
            continue
        result = json.loads(message["content"])
        if isinstance(result.get("body"), str) and "response_entry" in result:
            size = len(result["body"])
            result["body"] = (
                f"(logged as {result['response_entry']}, {size:,} characters)"
            )
        elif (
            isinstance(result.get("definition"), (dict, str)) and "operation" in result
        ):
            size = len(json.dumps(result["definition"], ensure_ascii=False))
            result["definition"] = (
                f"(definition of {result['operation']}, {size:,} characters; "
                "call operation again to re-read)"
            )
        else:
            continue
        sent[i] = {**message, "content": json.dumps(result, ensure_ascii=False)}
    return sent


def _media_type(name: str) -> str:
    """The type an uploaded file part is sent with, guessed from its extension."""
    suffix = Path(name).suffix.lower()
    return (
        _MEDIA_TYPES.get(suffix)
        or mimetypes.guess_type(name)[0]
        or "application/octet-stream"
    )


def _skipped(name: str | None, why: str) -> dict[str, Any]:
    return {"name": name, "outcome": "skipped", "why": why}


def _preview(response: httpx.Response) -> str:
    return response.content.decode("utf-8", errors="replace")


def _retry_after(response: httpx.Response) -> float:
    try:
        return max(0.0, float(response.headers.get("retry-after", "5")))
    except ValueError:  # an HTTP date
        return 5.0


class HttpRunnerFactory:
    """Builds :class:`HttpRunner`s for the app the specification's target binding names."""

    def __init__(
        self,
        binding: LoadedBinding,
        transport: httpx.AsyncBaseTransport | None = None,
        llm: AsyncOpenAI | None = None,
    ) -> None:
        self._binding = binding
        self._transport = transport
        """Replaced by a fake in tests; otherwise ``start`` opens the real one."""
        self._llm = llm
        """Replaced by a fake in tests; otherwise each runner builds its own client."""

    @property
    def binding(self) -> LoadedBinding:
        return self._binding

    @classmethod
    def from_specification(
        cls, specification: Specification, inputs_dir: Path
    ) -> HttpRunnerFactory:
        """Load ``specification.target_binding`` from the experiment's ``inputs_dir``.

        :raises TargetBindingError: When the specification names no binding, or the
            binding cannot be loaded.
        """
        if specification.target_binding is None:
            raise TargetBindingError(
                "HttpRunnerFactory needs the specification's target_binding, "
                "which is not set"
            )
        return cls(load_target_binding(inputs_dir, specification.target_binding))

    @property
    def retry_defaults(self) -> tuple[int, float]:
        defaults = TrialRetryConfig()
        return defaults.trial_max_retries, defaults.trial_retry_delay_seconds

    async def start(self) -> None:
        """Open the HTTP transport every trial's client shares."""
        if self._transport is None:
            self._transport = httpx.AsyncHTTPTransport(
                verify=self._binding.binding.tls_verify
            )

    async def create(
        self, run_dir: Path, fixtures_dir: Path, experiment_root: Path
    ) -> HttpRunner:
        """A runner whose requests are logged to this trial's own transport log."""
        assert self._transport is not None, "start() must run before create()"
        log = TransportLog.for_trial(run_dir)
        logged = LoggingTransport(
            _Shared(self._transport),
            log,
            secret_headers=[h.header for h in self._binding.binding.secret_headers],
        )
        client = httpx.AsyncClient(transport=logged, timeout=_TIMEOUT)
        return HttpRunner(
            self._binding,
            client,
            log,
            experiment_root,
            llm_log=LLMCallLog.for_trial(run_dir),
            llm=self._llm,
        )

    async def close(self) -> None:
        if self._transport is not None:
            await self._transport.aclose()
            self._transport = None


class _Shared(httpx.AsyncBaseTransport):
    """Lends the factory's transport to one trial's client, which must not close it."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self._inner.handle_async_request(request)
