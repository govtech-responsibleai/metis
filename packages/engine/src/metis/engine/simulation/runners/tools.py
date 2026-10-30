"""The runner agent's tools: their JSON schemas and the dispatcher that runs them.

Every refusal, whether a rule (``ToolRefused``), a pointer that leads nowhere
(``PointerError``) or arguments that are not usable, goes back to the agent as
``{"error": "refused, nothing was sent: ..."}`` so it can try something else. Nothing
here raises for the agent's mistakes.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

from metis.core.logging import get_logger

from ..evidence import Pointer, PointerError, resolve
from ..types import Reading
from .rules import ToolRefused

logger = get_logger()

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from .http import HttpRunner

    Handler = Callable[[Any, "ActionState", dict[str, Any]], Awaitable[dict[str, Any]]]

OUTCOMES = ("done", "not_done", "partial", "unknown")
SUBMISSION_STATES = ("answered", "pending")
MAX_DEFINITION_CHARS = 6000
"""Most characters of one operation's definition the agent is shown."""
REF_DEPTH = 3
"""How many ``$ref`` links in a row ``operation`` follows."""
_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


@dataclass
class Report:
    """What the agent's ``report`` said, with the facts already copied by code."""

    reply: str | None
    promised: list[str]
    reading: Reading


@dataclass
class ActionState:
    """What the tools learn during one ``act``."""

    first_result: int
    """``len(runner.results)`` when the action began: its entries come after this."""
    turn: int | str = 0
    """What the log calls this action: its turn number, or ``closing`` or ``sign_in``."""
    transport_failed: bool = False
    answered: bool = False
    """The agent closed an open submission as answered during this action."""
    report: Report | None = None
    refusals: list[str] = field(default_factory=list)


def pointer_schema(properties: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "entry": {"type": "string", "description": "a logged result's entry ID"},
            "at": {"type": "string", "description": "JSON path, e.g. $.files[0].name"},
            "pattern": {
                "type": "string",
                "description": "regex with one group, applied to the value",
            },
            **(properties or {}),
        },
        "required": ["entry"],
    }


def tool_schema(
    name: str, description: str, properties: dict[str, Any], *required: str
) -> Any:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(required),
            },
        },
    }


TOOLS: list[Any] = [
    tool_schema(
        "operation",
        "Read one operation's definition from the specification: parameters, body and "
        "responses. Sends nothing to the target.",
        {"method": {"type": "string"}, "path": {"type": "string"}},
        "method",
        "path",
    ),
    tool_schema(
        "http_request",
        "Send one request to the target. Write {{n}} where the user's n-th words go.",
        {
            "method": {"type": "string"},
            "path": {"type": "string", "description": "as the specification writes it"},
            "query": {"type": "object"},
            "json": {"description": "the JSON body"},
            "multipart": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": "part name to text, or @filename for a file you hold",
            },
            "headers": {"type": "object"},
            "file_id_from": {
                "type": "string",
                "description": "JSON path of the target's file ID in a one-file upload's reply",
            },
        },
        "method",
        "path",
    ),
    tool_schema(
        "poll_until",
        "GET a path until the value at `at` settles. Give not_in (still waiting) or in "
        "(done), not both.",
        {
            "path": {"type": "string"},
            "at": {"type": "string", "description": "JSON path of the value"},
            "not_in": {"type": "array", "items": {}},
            "in": {"type": "array", "items": {}},
        },
        "path",
        "at",
    ),
    tool_schema(
        "fetch_files",
        "Download the files in one logged listing. Code copies each ID and name.",
        {
            "listing": pointer_schema(),
            "id_key": {"type": "string"},
            "name_key": {"type": "string"},
            "download_path": {"type": "string", "description": "has exactly one {id}"},
            "where": {"type": "object", "description": "keep items with these values"},
        },
        "listing",
        "id_key",
        "name_key",
        "download_path",
    ),
    tool_schema(
        "session_id_from",
        "Record the target's session ID from the reply to a submission.",
        pointer_schema()["properties"],
        "entry",
    ),
    tool_schema(
        "note",
        "Keep what you learned about this target for later turns.",
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
            "submission": {
                "type": "string",
                "enum": list(SUBMISSION_STATES),
                "description": (
                    "Required while a submission is open: `answered` if the target's "
                    "reply is already in its response, `pending` if it comes later."
                ),
            },
            "reply_from": pointer_schema(),
            "promised": {"type": "array", "items": pointer_schema()},
        },
        "outcome",
        "why",
    ),
]


def operation_index(document: dict[str, Any]) -> str:
    """The target's title and one ``METHOD path - summary`` line per operation.

    Empty when the document lists no operation (no usable ``paths``), which is how
    callers tell that it cannot be indexed.
    """
    paths = document.get("paths")
    lines: list[str] = []
    for path, item in (paths if isinstance(paths, dict) else {}).items():
        for method, op in (item if isinstance(item, dict) else {}).items():
            if method in _METHODS and isinstance(op, dict):
                label = op.get("summary") or op.get("operationId")
                lines.append(
                    f"{method.upper()} {path}" + (f" - {label}" if label else "")
                )
    if not lines:
        return ""
    info = document.get("info")
    title = info.get("title") if isinstance(info, dict) else None
    return "\n".join(([str(title)] if title else []) + lines)


def _follow(node: Any, document: dict[str, Any], depth: int) -> Any:
    """Copy ``node``, replacing each local ``$ref`` by what it points at, ``depth`` deep."""
    if isinstance(node, list):
        return [_follow(n, document, depth) for n in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/") and depth > 0:
        target: Any = document
        for part in ref[2:].split("/"):
            target = (
                target.get(part.replace("~1", "/").replace("~0", "~"))
                if isinstance(target, dict)
                else None
            )
        if target is not None:
            return _follow(target, document, depth - 1)
    return {k: _follow(v, document, depth) for k, v in node.items()}


def definition(document: dict[str, Any], method: str, path: str) -> dict[str, Any]:
    """One operation as the specification writes it, with its ``$ref`` links followed.

    :raises ToolRefused: When the specification has no such operation.
    """
    if not operation_index(document):
        raise ToolRefused(
            "this specification lists no operations, so there is nothing to look up; "
            "read the specification text in the first message"
        )
    method = method.lower()
    item = (document.get("paths") or {}).get(path)
    op = item.get(method) if isinstance(item, dict) else None
    if not isinstance(op, dict):
        known = [m.upper() for m in _METHODS if isinstance(item, dict) and m in item]
        if known:
            raise ToolRefused(
                f"no operation {method.upper()} {path}; that path has {', '.join(known)}"
            )
        close = difflib.get_close_matches(path, list(document.get("paths") or {}), n=5)
        raise ToolRefused(
            f"no operation {method.upper()} {path}; close paths: "
            + (", ".join(close) or "none")
        )
    shared = item.get("parameters")
    body = {**op, "parameters": [*shared, *op.get("parameters", [])]} if shared else op
    found: dict[str, Any] = {
        "operation": f"{method.upper()} {path}",
        "definition": _follow(body, document, REF_DEPTH),
    }
    text = json.dumps(found["definition"], ensure_ascii=False)
    if len(text) > MAX_DEFINITION_CHARS:
        found["definition"] = text[:MAX_DEFINITION_CHARS]
        found["cut"] = f"cut at {MAX_DEFINITION_CHARS:,} of {len(text):,} characters"
    return found


def _need(args: dict[str, Any], key: str) -> Any:
    if args.get(key) is None:
        raise ToolRefused(f"the argument {key!r} is required")
    return args[key]


def _point(raw: Any) -> Pointer:
    if not isinstance(raw, dict):
        raise ToolRefused("a pointer is an object with `entry`, and `at` or `pattern`")
    return Pointer(
        str(_need(raw, "entry")), raw.get("at"), raw.get("pattern"), raw.get("ref")
    )


async def run_tool(
    runner: Any,
    state: ActionState,
    name: str,
    raw_args: str,
    handlers: dict[str, Handler] | None = None,
) -> dict[str, Any]:
    """Run one tool call. A mistake of the agent's comes back as an error result.

    :param handlers: The runner's tools by name; the HTTP runner's when omitted.
    """
    try:
        handler = (handlers or _HANDLERS).get(name)
        if handler is None:
            raise ToolRefused(f"there is no tool {name!r}")
        try:
            args = json.loads(raw_args or "{}")
        except ValueError:
            raise ToolRefused("the arguments are not valid JSON") from None
        if not isinstance(args, dict):
            raise ToolRefused("the arguments must be a JSON object")
        result = await handler(runner, state, args)
        logger.debug(
            "runner_agent_tool_call",
            turn=state.turn,
            tool=name,
            result="ok",
            detail=_summary(args, result),
        )
        return result
    except (ToolRefused, PointerError) as exc:
        message = f"refused, nothing was sent: {exc}"
        state.refusals.append(f"{name}: {exc}")
        logger.info(
            "runner_agent_tool_call",
            turn=state.turn,
            tool=name,
            result="refused",
            detail=str(exc),
        )
        return {"error": message}
    except httpx.TransportError as exc:
        state.transport_failed = True
        logger.info(
            "runner_agent_tool_call",
            turn=state.turn,
            tool=name,
            result="transport_failed",
            detail=type(exc).__name__,
        )
        return {"error": f"the call failed at the transport: {type(exc).__name__}"}


def _summary(args: dict[str, Any], result: dict[str, Any]) -> str:
    """What a finished tool call did, in a few words for the log."""
    if "status" in result:
        return f"{args.get('method', '')} {args.get('path', '')} -> {result['status']}".strip()
    return " ".join(f"{k}={str(v)[:60]}" for k, v in args.items() if k != "json")[:200]


async def _operation(
    runner: HttpRunner, state: ActionState, args: dict[str, Any]
) -> dict[str, Any]:
    return definition(
        runner.document, str(_need(args, "method")), str(_need(args, "path"))
    )


async def _http_request(
    runner: HttpRunner, state: ActionState, args: dict[str, Any]
) -> dict[str, Any]:
    return await runner.http_request(
        str(_need(args, "method")),
        str(_need(args, "path")),
        query=args.get("query"),
        json=args.get("json"),
        multipart=args.get("multipart"),
        headers=args.get("headers"),
        file_id_from=args.get("file_id_from"),
    )


async def _poll_until(
    runner: HttpRunner, state: ActionState, args: dict[str, Any]
) -> dict[str, Any]:
    return await runner.poll_until(
        str(_need(args, "path")),
        str(_need(args, "at")),
        not_in=args.get("not_in"),
        in_=args.get("in"),
    )


async def _fetch_files(
    runner: HttpRunner, state: ActionState, args: dict[str, Any]
) -> dict[str, Any]:
    return await runner.fetch_files(
        _point(_need(args, "listing")),
        str(_need(args, "id_key")),
        str(_need(args, "name_key")),
        str(_need(args, "download_path")),
        args.get("where"),
    )


async def _session_id_from(
    runner: HttpRunner, state: ActionState, args: dict[str, Any]
) -> dict[str, Any]:
    runner.record_session_id(_point(args))
    return {"ok": True, "session_id": runner.session_id}


async def _note(
    runner: HttpRunner, state: ActionState, args: dict[str, Any]
) -> dict[str, Any]:
    runner.notes.append(str(_need(args, "text")))
    return {"ok": True}


async def _report(
    runner: HttpRunner, state: ActionState, args: dict[str, Any]
) -> dict[str, Any]:
    """Accept the report only if its pointers resolve to this action's entries."""
    outcome = _need(args, "outcome")
    if outcome not in OUTCOMES:
        raise ToolRefused(f"outcome must be one of {', '.join(OUTCOMES)}")
    why = str(_need(args, "why"))
    allowed = runner.results[state.first_result :]
    reply = None
    if args.get("reply_from") is not None:
        value, _ = resolve(_point(args["reply_from"]), runner.log, allowed)
        reply = value if isinstance(value, str) else json.dumps(value)
    promised: list[str] = []
    for raw in args.get("promised") or []:
        value, entry = resolve(_point(raw), runner.log, allowed)
        if not isinstance(value, str) or not value.strip() or "\n" in value.strip():
            raise ToolRefused(
                f"promised: {entry.id} does not name one file; the value must be a "
                "single line (use `at` or `pattern` to cut the name out)"
            )
        promised.append(value.strip())
    state.report = Report(
        reply,
        promised,
        Reading(
            outcome=outcome, why=why, next_options=str(args.get("next_options") or "")
        ),
    )
    return {"ok": True}


async def _http_report(
    runner: HttpRunner, state: ActionState, args: dict[str, Any]
) -> dict[str, Any]:
    """``report``, after the agent says whether the open submission is answered.

    The agent reads the response and decides; code only refuses a decision the status
    contradicts. A wrong ``reply_from`` then costs the reply, never the submission.
    """
    opened = runner.open_submission
    if opened is not None:
        decision = args.get("submission")
        if decision not in SUBMISSION_STATES:
            raise ToolRefused(
                "a submission is open: set `submission` to `answered` (its reply is in "
                "the response you read) or `pending` (the reply comes later)"
            )
        if decision == "answered":
            runner.settle_answered()
            state.answered = True
    return await _report(runner, state, args)


SHARED_HANDLERS: dict[str, Handler] = {
    "session_id_from": _session_id_from,
    "note": _note,
    "report": _report,
}
"""The tools every runner has. They touch only ``results``, ``log``, ``notes`` and
``record_session_id``, which each runner supplies."""

_HANDLERS: dict[str, Handler] = {
    "operation": _operation,
    "http_request": _http_request,
    "poll_until": _poll_until,
    "fetch_files": _fetch_files,
    **SHARED_HANDLERS,
    "report": _http_report,
}
