"""The trace processor: the one place graders go to read a session, select what to judge, and
render it for the judge.

A grader judges a session in pieces: each recorded turn, a run of recorded turns, the whole
session, or one file. A recorded turn is one trace, as defined in ``GLOSSARY.md``.
It calls the select function for its scope, which returns each piece under the label of its
result, then renders each piece with a render function and sends that to its judge. Nothing
outside this module reads an observation's ``input``, ``output`` or ``metadata``; those hold
whatever the application sent.

============================================  ===================================================
What a grader needs                           Use
============================================  ===================================================
**1. Read the session**
The recorded turns: messages, calls, reply    ``turns(input.traces)``
The files the target produced                 ``find_artifacts(input, name)``
The files the user gave the target            ``find_fixtures(input)``
The tools each agent had                      ``tools_offered(input.traces)``
**2. Select what to judge**
Each recorded turn on its own (trace scope)   ``select_by_turn(turns, last_only=...)``
A recorded turn and those before it           ``select_by_window(turns, size, last_only=...)``
The whole session (session scope)             ``select_session(turns)``
The latest revision of a file (artifact)      ``select_by_artifact(input, name)``
**3. Render it for the judge**
Turns: everything the trace records           ``render_session(turns, tool_results=...)``
Turns: only what the user reads               ``render_dialogue(turns, assistant_only=...)``
A file                                        ``render_artifact(path)``
**4. Read one payload in detail**
A message's text for a role                   ``text_of(value, role)``
Every chat message in a payload               ``messages_of(value)``
A tool call's arguments or result             ``tool_arguments(call)``, ``tool_result(call)``
============================================  ===================================================

Each select function returns a ``dict`` from label to what the judge reads. The label becomes
``GraderResult.scope``:

==========  ======================  ==========================================  ==================
Scope       Select                  One entry, label: value                     Render
==========  ======================  ==========================================  ==================
trace       ``select_by_turn``      ``"turn:3"``: that recorded turn            ``render_session``
subsession  ``select_by_window``    ``"turns:2-4"``: those recorded turns       ``render_session``
session     ``select_session``      ``"session"``: every recorded turn          ``render_session``
artifact    ``select_by_artifact``  ``"artifact:a.pdf"``: a path                ``render_artifact``
==========  ======================  ==========================================  ==================

A grader that judges one recorded turn with every recorded turn before it as context uses
``select_by_window(turns, size=None)``. A grader that needs another view of the same turns, such
as ``render_dialogue``, calls that render function itself.

**Problems.** A function returns a ``Problem`` when METIS could not read or find something. It is
never the target's fault, so a grader records it as ``errored`` with the detail, never as a low
score. What the target itself reported as an error is a ``TargetError`` on the turn, which is
evidence to grade.

**Supported payloads.** The readers in section 4 support these shapes. Anything else is an
``unsupported`` problem. Adding a shape means one row here and one reader change.

=====================================================  ============================================
Shape                                                  Read by
=====================================================  ============================================
plain string                                           ``text_of`` (for any role), ``tool_result``
``{"role", "content"}``, a list of these, or           ``messages_of``; ``text_of`` takes the last
``{"messages": [...]}`` of these (OpenAI-style;        message with the requested role. ``content``
``content`` a string or a list of text blocks)         blocks of type ``text`` are joined
``{"role", "parts": [...]}`` or a list of these        ``messages_of``; ``text_of`` joins the text
(OpenTelemetry GenAI ``gen_ai.*.messages``)            parts
a dict                                                 ``tool_arguments``, ``tool_result``
a list (for example JSON-array search hits)            ``tool_result``
=====================================================  ============================================

A reply that is a JSON object or array, and not a chat message, is the target's answer in a
structured format, so ``Turn.reply`` holds it as JSON text. A JSON reply, tool argument or tool
result is shown as the text the application recorded, from ``Observation.raw``, because
re-serialising parsed JSON changes it (``10.50`` becomes ``10.5``). Langfuse replaces media an
application uploaded (images, files) with a reference token,
``@@@langfuseMedia:type=…|id=…|source=…@@@``. METIS does not fetch the media, so a judge given
the token would grade without the image, and any text holding one is ``unsupported``. A string
that looks like a dict but is not JSON (for example a tool output in Python syntax) is a string.

Everything here is frozen and every collection a tuple, because one ``GradingInput`` is shared
by concurrent grader runs.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import re
from datetime import datetime  # noqa: TC003
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

# Pydantic field types (Turn.trace, ToolCall.observation), so runtime imports.
from metis.core.traces import Observation, Trace  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Sequence

    from metis.core.artifacts import Artifact
    from metis.core.traces import GradingInput

ProblemKind = Literal["missing", "unsupported", "no_match", "artifact_unavailable"]
Field = Literal["input", "output", "metadata"]


# ---------------------------------------------------------------------------
# Types: a turn, its tool calls and errors, and a problem
# ---------------------------------------------------------------------------


class Problem(BaseModel, frozen=True):
    """Something METIS could not read or find. Never a failure of the target."""

    kind: ProblemKind
    detail: str
    trace_id: str | None = None
    observation_id: str | None = None
    field: Field | None = None


class TargetError(BaseModel, frozen=True):
    """Something the target itself reported as wrong: evidence about the target, to be graded."""

    message: str
    trace_id: str
    observation_id: str


class ToolCall(BaseModel, frozen=True):
    """One ``TOOL`` observation, wherever it sits in its trace."""

    turn_index: int
    """The 0-based position of the recorded turn (the trace) that holds this call, so
    ``turn_index + 1`` is the ``N`` of its ``turn:N`` label. It is never a simulated turn."""
    observation: Observation
    agent: str | None
    """The name of the nearest enclosing ``AGENT`` observation, or ``None`` if there is none."""

    @property
    def name(self) -> str:
        return self.observation.name or ""

    @property
    def observation_id(self) -> str:
        return self.observation.id


class Turn(BaseModel, frozen=True):
    """One **recorded turn** (``GLOSSARY.md``): one trace, read the way Langfuse documents a
    trace's input and output.

    In this module "turn" always means this, never a simulated turn. The name is not
    ``RecordedTurn`` because ``turn:N`` labels and the ``turn`` grader setting already use the
    bare word and are saved in ``results.json`` and in specifications.
    """

    index: int
    """The 0-based position of the trace in the session; ``index + 1`` is the ``N`` of ``turn:N``."""
    trace: Trace
    user: str | Problem
    """``trace.root.input`` as user text."""
    reply: str | Problem
    """``trace.root.output`` as assistant text, or as JSON text when it is a JSON object or array
    that is not a chat message."""
    tool_calls: tuple[ToolCall, ...]
    """Every ``TOOL`` observation in the trace, at any depth, oldest first."""
    target_errors: tuple[TargetError, ...]
    events: tuple[Event, ...] = ()
    """Everything between the user's message and the reply, in time order: system prompts,
    model output, sub-agent handoffs, tool calls and errors on other observations."""

    @property
    def trace_id(self) -> str:
        return self.trace.id


class ToolCallPart(BaseModel, frozen=True):
    """A tool call the model asked for inside a message."""

    name: str
    arguments: dict[str, Any] | str | None = None


class Message(BaseModel, frozen=True):
    """One chat message, whatever format it arrived in."""

    role: str
    text: str
    tool_calls: tuple[ToolCallPart, ...] = ()


class SystemPrompt(BaseModel, frozen=True):
    """The system prompt a model was given, from a ``GENERATION`` input."""

    agent: str | None
    text: str


class ModelOutput(BaseModel, frozen=True):
    """What one model call wrote: its reasoning, a plan, or a message between tool calls."""

    agent: str | None
    text: str | Problem


class Handoff(BaseModel, frozen=True):
    """A sub-agent's ``AGENT`` observation: the task it was given, or what it returned."""

    agent: str
    caller: str | None
    direction: Literal["call", "return"]
    payload: Any


class ObservationError(BaseModel, frozen=True):
    """An error or warning Langfuse recorded on an observation that is not a tool call, such as
    a model call that the framework retried. The agent may never have seen it."""

    type: str
    name: str
    level: str
    message: str | None
    agent: str | None


Event = SystemPrompt | ModelOutput | Handoff | ToolCall | ObservationError
"""One thing the trace records in a turn, in time order."""


class OfferedTool(BaseModel, frozen=True):
    """A tool the target had in the session, whether or not it called it."""

    name: str
    description: str | None = None
    parameters: dict[str, Any] | None = None
    """The tool's JSON Schema for its arguments, when the trace recorded one."""
    agent: str | None = None
    """The name of the ``AGENT`` observation that had the tool, or ``None`` if the trace does
    not say."""


# ---------------------------------------------------------------------------
# 1. Read the session
# ---------------------------------------------------------------------------


def turns(traces: Sequence[Trace]) -> tuple[Turn, ...]:
    """Every recorded turn in the session, oldest first, including those where the target failed.

    One trace is one recorded turn. Each ``Turn`` holds the user's message, every tool call, the reply,
    and each error the target reported.
    """
    return tuple(_turn(index, trace) for index, trace in enumerate(traces))


def find_artifacts(input: GradingInput, name: str) -> tuple[Artifact, ...] | Problem:
    """Every received target file called ``name``, in the run's order.

    Names are not unique (a revised file keeps its name), so all matches are returned and the
    grader decides which to use. Which turn produced a file is not known here (see #427).
    """
    found = tuple(
        artifact
        for artifact in input.artifacts
        if artifact.name == name
        and artifact.source == "target"
        and artifact.state == "received"
        and artifact.path is not None
    )
    return found or Problem(
        kind="artifact_unavailable", detail=f"no received target file named {name!r}"
    )


def find_fixtures(input: GradingInput) -> tuple[Artifact, ...]:
    """Every file the user gave the target that METIS holds, in the run's order.

    These are the received ``fixture`` artifacts. A session where the user gave no file
    returns ``()``.
    """
    return tuple(
        artifact
        for artifact in input.artifacts
        if artifact.source == "fixture"
        and artifact.state == "received"
        and artifact.path is not None
    )


def tools_offered(traces: Sequence[Trace]) -> tuple[OfferedTool, ...]:
    """Every tool the target had in the session, one per agent and name, in the order first
    seen. ``()`` when the traces record no tool list.

    Three sources are read, and for each field the first source that holds it wins:

    1. A ``GENERATION`` input's ``tools`` list, in OpenAI style
       (``{"type": "function", "function": {"name", "description", "parameters"}}``) or
       Anthropic style (``{"name", "description", "input_schema"}``). The agent is the
       nearest enclosing ``AGENT``.
    2. An ``AGENT`` observation's ``attributes.agno.tools`` metadata, a list of names. The
       agent is that observation.
    3. A ``TOOL`` observation's ``attributes.tool.name`` and ``attributes.tool.description``
       metadata, or the observation's name when the metadata has no name. The agent is the
       nearest enclosing ``AGENT``. Only a tool that was called appears here.

    An entry in another shape is skipped.
    """
    found: dict[tuple[str | None, str], list[tuple[int, OfferedTool]]] = {}
    for trace in traces:
        by_id = {observation.id: observation for observation in trace.observations}
        for observation in trace.observations:
            for rank, tool in _tools_recorded(observation, by_id):
                found.setdefault((tool.agent, tool.name), []).append((rank, tool))
    return tuple(_merged(entries) for entries in found.values())


# ---------------------------------------------------------------------------
# 2. Select what a grader judges
# ---------------------------------------------------------------------------


_NO_TURNS = Problem(kind="no_match", detail="The session has no turns.")


def select_by_turn(
    turns: tuple[Turn, ...], *, last_only: bool = False
) -> dict[str, tuple[Turn, ...] | Problem] | Problem:
    """Trace scope: each turn on its own, or only the last turn, labelled ``turn:N``.

    The value is a one-turn tuple, so it renders like any other run of turns. A turn whose
    reply cannot be read is a ``Problem`` in place of the turn, unless the target reported an
    error on it: a missing reply is then the target failing, so the turn is judged. A session
    with no turns is a ``Problem``.
    """
    if not turns:
        return _NO_TURNS
    selected: dict[str, tuple[Turn, ...] | Problem] = {}
    for turn in turns[-1:] if last_only else turns:
        label = f"turn:{turn.index + 1}"
        if isinstance(turn.reply, Problem) and not turn.target_errors:
            selected[label] = turn.reply.model_copy(
                update={
                    "detail": f"The reply in turn {turn.index + 1} cannot be read: "
                    f"{turn.reply.detail}."
                }
            )
        else:
            selected[label] = (turn,)
    return selected


def select_by_window(
    turns: tuple[Turn, ...], size: int | None = None, *, last_only: bool = False
) -> dict[str, tuple[Turn, ...]] | Problem:
    """Subsession scope: for each turn, or only the last turn, that turn and up to
    ``size - 1`` turns just before it, labelled ``turns:A-B``.

    ``size=None`` holds every turn before it, so the judge has the whole conversation so far.
    A window near the start of the session is shorter, because fewer turns come before it.
    A session with no turns is a ``Problem``.
    """
    if not turns:
        return _NO_TURNS
    selected: dict[str, tuple[Turn, ...]] = {}
    for end in turns[-1:] if last_only else turns:
        start = 0 if size is None else max(end.index + 1 - size, 0)
        selected[f"turns:{start + 1}-{end.index + 1}"] = turns[start : end.index + 1]
    return selected


def select_session(turns: tuple[Turn, ...]) -> dict[str, tuple[Turn, ...]] | Problem:
    """Session scope: every turn, labelled ``session``. A session with no turns is a
    ``Problem``."""
    if not turns:
        return _NO_TURNS
    return {"session": turns}


def select_by_artifact(
    input: GradingInput, name: str | None
) -> dict[str, Path] | Problem:
    """Artifact scope: the latest revision of the received target file called ``name``,
    labelled ``artifact:<name>``.

    A revised file keeps its name, and the judge grades the file the user ends up with. The
    latest revision is the one with the highest ``at_simulated_turn``, where a revision with no
    ``at_simulated_turn`` counts as earlier than every turn. Revisions with the same ``at_simulated_turn`` are
    ordered by their place in ``GradingInput.artifacts``, and the last one is kept. No file
    with the name, or no name, is a ``Problem``.
    """
    if name is None:
        return Problem(kind="no_match", detail="No artifact name is set.")
    found = find_artifacts(input, name)
    if isinstance(found, Problem):
        return found.model_copy(
            update={"detail": f"No received target file named {name!r}."}
        )
    _, latest = max(enumerate(found), key=_revision_order)
    assert latest.path is not None  # find_artifacts keeps only files with a path
    return {f"artifact:{name}": Path(latest.path)}


# ---------------------------------------------------------------------------
# 3. Render what was selected for the judge
# ---------------------------------------------------------------------------


def render_session(
    turns: tuple[Turn, ...] | Problem,
    *,
    tool_results: bool = False,
    max_chars: int | None = None,
) -> str | Problem:
    """Turns as one plain-text transcript: one turn, a window, or the whole session.

    Each turn is ``## Turn N``, then ``User:``, one ``Tool name (agent): arguments`` line per
    tool call, ``Assistant:``, and a ``[target error: …]`` line when the target returned no
    reply. Anything unreadable is shown as ``[unreadable: kind: detail]`` rather than dropped,
    so the judge sees the gap.

    The tool call lines sit among the turn's other events, in time order:

    - ``System prompt (agent):``, shown the first time each of an agent's system prompts
      appears, so a long prompt is not repeated in every turn.
    - ``Model (agent):`` for what a model call wrote, such as reasoning or a message between
      tool calls. Only a call's output is shown, never its input, which repeats the history.
      A structured output that is not chat messages, such as a JSON action, is shown as the
      application recorded it. Output that repeats the reply or a sub-agent's answer is left
      out.
    - ``Handoff to agent (from caller):`` and ``agent returned (to caller):`` for a sub-agent.
    - ``[error on TYPE name (agent): message]`` or ``[warning on …]`` for an error Langfuse
      recorded on an observation that is not a tool call.

    With ``tool_results``, each tool call line is followed by ``Tool result [status]: result``.
    The status is ``error`` or ``warning`` when Langfuse recorded that level on the call, with
    the status message when there is one, else ``ok``. With ``max_chars``, an argument or
    result longer than that ends in ``…[cut off]``. ``None`` cuts nothing, and the judge's
    ``max_input_tokens`` limits the size. A ``Problem`` passes through unchanged, so a grader's
    loop needs no branch for a turn that cannot be judged.
    """
    if isinstance(turns, Problem):
        return turns
    shown_prompts: set[tuple[str | None, str]] = set()
    blocks: list[str] = []
    for turn in turns:
        lines = [f"## Turn {turn.index + 1}", f"User: {_shown(turn.user)}"]
        for call in turn.events:
            if not isinstance(call, ToolCall):
                lines.extend(_event_lines(call, shown_prompts, max_chars))
                continue
            agent = f" ({call.agent})" if call.agent else ""
            arguments = _shown_payload(tool_arguments(call.observation), max_chars)
            lines.append(f"Tool {call.name}{agent}: {arguments}")
            if tool_results:
                result = _shown_payload(tool_result(call.observation), max_chars)
                lines.append(f"Tool result [{_call_status(call)}]: {result}")
        lines.append(f"Assistant: {_shown(turn.reply)}")
        if turn.trace.root.output is None:
            lines.append("[target error: the target returned no reply]")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def render_dialogue(
    turns: tuple[Turn, ...] | Problem, *, assistant_only: bool = False
) -> str | Problem:
    """The ``User:`` and ``Assistant:`` lines of ``render_session``, without tool calls.

    For a judge of what the user reads. With ``assistant_only``, only the ``Assistant:`` lines,
    for a judge of the replies' own wording. A ``Problem`` passes through unchanged.
    """
    if isinstance(turns, Problem):
        return turns
    blocks: list[str] = []
    for turn in turns:
        lines = [f"## Turn {turn.index + 1}"]
        if not assistant_only:
            lines.append(f"User: {_shown(turn.user)}")
        lines.append(f"Assistant: {_shown(turn.reply)}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


MAX_FILE_BYTES = 50 * 1024 * 1024
"""The largest file the judge accepts."""


class FileInput(BaseModel, frozen=True):
    """A file as the judge receives it: its name and its bytes as a base64 data URL."""

    filename: str
    data_url: str


def render_artifact(path: Path | Problem) -> FileInput | Problem:
    """A file as the judge receives it. The judge reads the file itself, so METIS does not
    extract its text. A file that cannot be read, or that is larger than ``MAX_FILE_BYTES``,
    is a ``Problem``. A ``Problem`` passes through unchanged.
    """
    if isinstance(path, Problem):
        return path
    try:
        data = path.read_bytes()
    except OSError as exc:
        return Problem(
            kind="missing", detail=f"The file {path.name} cannot be read: {exc}"
        )
    if len(data) > MAX_FILE_BYTES:
        return Problem(
            kind="unsupported",
            detail=f"The file {path.name} is larger than {MAX_FILE_BYTES:,} bytes.",
        )
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(data).decode("ascii")
    return FileInput(filename=path.name, data_url=f"data:{mime};base64,{encoded}")


# ---------------------------------------------------------------------------
# 4. Read one payload in detail
# ---------------------------------------------------------------------------


def text_of(value: object, role: str) -> str | Problem:
    """The text a payload holds for ``role``: a plain string, or its last ``role`` message."""
    if value is None:
        return Problem(kind="missing", detail="no value")
    if isinstance(value, str):
        return _media_problem(value) or value
    messages = messages_of(value)
    if isinstance(messages, Problem):
        return messages
    for message in reversed(messages):
        if message.role == role:
            return _media_problem(message.text) or message.text
    return Problem(kind="missing", detail=f"no {role} message")


def messages_of(value: object) -> tuple[Message, ...] | Problem:
    """The chat messages in a payload, in order."""
    if value is None:
        return Problem(kind="missing", detail="no value")
    if isinstance(value, dict) and "messages" in value:
        value = value["messages"]
    items = value if isinstance(value, list) else [value]
    messages = tuple(_message(item) for item in items)
    if not items or any(m is None for m in messages):
        return Problem(
            kind="unsupported",
            detail=f"not a list of chat messages: {_describe(value)}",
        )
    return tuple(m for m in messages if m is not None)


def tool_arguments(observation: Observation) -> dict[str, Any] | str | Problem:
    """A tool call's arguments, which must be a JSON object: the JSON text the application
    recorded, or the dict when it recorded no text."""
    value = observation.input
    if value is None:
        problem = Problem(kind="missing", detail="the tool call has no arguments")
    elif isinstance(value, dict):
        return _recorded_text(observation, "input") or value
    else:
        problem = Problem(
            kind="unsupported", detail=f"arguments are a {_describe(value)}"
        )
    return _locate(problem, observation, "input")


def tool_result(
    observation: Observation,
) -> str | dict[str, Any] | list[Any] | Problem:
    """A tool call's result as the application recorded it: its text, or the dict or list
    when it recorded no text."""
    value = observation.output
    if value is None:
        problem = Problem(kind="missing", detail="the tool call has no result")
    elif isinstance(value, (str, dict, list)):
        shown = _recorded_text(observation, "output") or value
        media = _media_problem(shown if isinstance(shown, str) else json.dumps(shown))
        if media is None:
            return shown
        problem = media
    else:
        problem = Problem(kind="unsupported", detail=f"result is a {_describe(value)}")
    return _locate(problem, observation, "output")


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


_ERROR_LEVELS = ("ERROR", "WARNING")


_MEDIA_REFERENCE = re.compile(
    r"@@@langfuseMedia:type=([^|@]*)\|id=([^|@]*)\|source=[^@]*@@@"
)


def _turn(index: int, trace: Trace) -> Turn:
    by_id = {observation.id: observation for observation in trace.observations}
    root = trace.root
    sent = _recorded_text(root, "output")
    return Turn(
        index=index,
        trace=trace,
        user=_locate_value(text_of(root.input, role="user"), root, "input"),
        reply=_locate_value(_reply_of(root.output, recorded=sent), root, "output"),
        tool_calls=tuple(
            ToolCall(turn_index=index, observation=o, agent=_agent_of(o, by_id))
            for o in trace.observations
            if o.type == "TOOL"
        ),
        target_errors=_target_errors(trace),
        events=_events(index, trace, by_id),
    )


def _reply_of(value: object, *, recorded: str | None = None) -> str | Problem:
    # A reply in a structured format, such as a JSON object, is the target's answer, so it is
    # shown as the JSON text the application recorded (``recorded``). Only a chat message
    # payload is read for its assistant text.
    if isinstance(value, (dict, list)) and isinstance(messages_of(value), Problem):
        text = recorded or json.dumps(value, ensure_ascii=False)
        return _media_problem(text) or text
    return text_of(value, role="assistant")


def _agent_of(observation: Observation, by_id: dict[str, Observation]) -> str | None:
    seen: set[str] = set()
    parent_id = observation.parent_observation_id
    while parent_id and parent_id in by_id and parent_id not in seen:
        seen.add(parent_id)
        parent = by_id[parent_id]
        if parent.type == "AGENT":
            return parent.name
        parent_id = parent.parent_observation_id
    return None


def _target_errors(trace: Trace) -> tuple[TargetError, ...]:
    errors: list[TargetError] = []
    root = trace.root
    if root.output is None:
        errors.append(
            TargetError(
                message="the target returned no reply",
                trace_id=trace.id,
                observation_id=root.id,
            )
        )
    for observation in trace.observations:
        if observation.level in _ERROR_LEVELS:
            errors.append(
                TargetError(
                    message=observation.status_message
                    or f"{observation.level} on {observation.name}",
                    trace_id=trace.id,
                    observation_id=observation.id,
                )
            )
    return tuple(errors)


def _locate(problem: Problem, observation: Observation, field: Field) -> Problem:
    return problem.model_copy(
        update={
            "trace_id": observation.trace_id,
            "observation_id": observation.id,
            "field": field,
        }
    )


def _locate_value(
    value: str | Problem, observation: Observation, field: Field
) -> str | Problem:
    return _locate(value, observation, field) if isinstance(value, Problem) else value


def _media_problem(text: str) -> Problem | None:
    """An ``unsupported`` problem naming the first Langfuse media reference in ``text``."""
    match = _MEDIA_REFERENCE.search(text)
    if match is None:
        return None
    return Problem(
        kind="unsupported",
        detail=f"holds a Langfuse media reference ({match.group(1)}, id {match.group(2)}) "
        "that METIS does not fetch",
    )


def _describe(value: object) -> str:
    """A short name for an unexpected value, for a ``Problem``'s detail."""
    if isinstance(value, dict):
        keys = ", ".join(sorted(str(k) for k in value)[:6])
        return f"dict with keys {keys}" if keys else "empty dict"
    if isinstance(value, list):
        return f"list of {len(value)}"
    return type(value).__name__


def _content_text(content: object) -> str | None:
    """The text of an OpenAI-style ``content``: a string, or a list of text blocks.

    ``None`` when a block list holds no text block at all (only images or files, say), so the
    message is reported as unsupported rather than read as an empty reply.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [
            block["text"]
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ]
        return "\n".join(texts) if texts or not content else None
    return None


def _openai_tool_calls(raw: object) -> tuple[ToolCallPart, ...]:
    calls: list[ToolCallPart] = []
    for entry in raw if isinstance(raw, list) else []:
        function = entry.get("function") if isinstance(entry, dict) else None
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            arguments = function.get("arguments")
            calls.append(
                ToolCallPart(
                    name=function["name"],
                    arguments=arguments if isinstance(arguments, (dict, str)) else None,
                )
            )
    return tuple(calls)


def _message(raw: object) -> Message | None:
    """One message in either supported format, or ``None`` if it is neither."""
    if not isinstance(raw, dict) or not isinstance(raw.get("role"), str):
        return None
    role = raw["role"]
    if "parts" in raw:
        parts = raw["parts"]
        if not isinstance(parts, list):
            return None
        texts: list[str] = []
        calls: list[ToolCallPart] = []
        known = False
        for part in parts:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "tool_call_response":
                known = True
            if part.get("type") == "text" and isinstance(part.get("content"), str):
                known = True
                texts.append(part["content"])
            elif part.get("type") == "tool_call" and isinstance(part.get("name"), str):
                arguments = part.get("arguments")
                known = True
                calls.append(
                    ToolCallPart(
                        name=part["name"],
                        arguments=arguments
                        if isinstance(arguments, (dict, str))
                        else None,
                    )
                )
        if parts and not known:
            return None  # only unsupported parts (images, files): not an empty message
        return Message(role=role, text="\n".join(texts), tool_calls=tuple(calls))
    if "content" in raw or "tool_calls" in raw:
        text = _content_text(raw.get("content"))
        if text is None:
            return None
        return Message(
            role=role, text=text, tool_calls=_openai_tool_calls(raw.get("tool_calls"))
        )
    return None


def _shown(value: str | Problem) -> str:
    return (
        f"[unreadable: {value.kind}: {value.detail}]"
        if isinstance(value, Problem)
        else value
    )


def _shown_payload(value: object, max_chars: int | None) -> str:
    if isinstance(value, Problem):
        return _shown(value)
    text = (
        value
        if isinstance(value, str)
        else json.dumps(value, ensure_ascii=False, default=str)
    )
    if max_chars is None or len(text) <= max_chars:
        return text
    return text[:max_chars] + " …[cut off]"


def _call_status(call: ToolCall) -> str:
    if call.observation.level not in _ERROR_LEVELS:
        return "ok"
    message = call.observation.status_message
    error = _level_word(call.observation.level)
    return f"{error}: {message}" if message else error


def _events(
    index: int, trace: Trace, by_id: dict[str, Observation]
) -> tuple[Event, ...]:
    """The turn's events in time order. A sub-agent's answer is placed at its end time."""
    root = trace.root
    repeated = {_plain(root.output)} | {
        _plain(o.output) for o in trace.observations if o.type == "AGENT"
    }
    timed: list[tuple[tuple[bool, float], Event]] = []
    for observation in trace.observations:
        if observation.id == root.id:
            continue
        agent = _agent_of(observation, by_id)
        start = _when(observation.start_time)
        if observation.type == "TOOL":
            timed.append(
                (
                    start,
                    ToolCall(turn_index=index, observation=observation, agent=agent),
                )
            )
            continue
        if observation.type == "GENERATION":
            for prompt in _system_prompts(observation.input):
                timed.append((start, SystemPrompt(agent=agent, text=prompt)))
            for text in _model_texts(observation):
                if _plain(text) not in repeated:
                    timed.append((start, ModelOutput(agent=agent, text=text)))
        elif observation.type == "AGENT" and agent is not None:
            name = observation.name or "agent"
            timed.append(
                (
                    start,
                    Handoff(
                        agent=name,
                        caller=agent,
                        direction="call",
                        payload=_recorded_text(observation, "input")
                        or observation.input,
                    ),
                )
            )
            timed.append(
                (
                    _when(observation.end_time or observation.start_time),
                    Handoff(
                        agent=name,
                        caller=agent,
                        direction="return",
                        payload=_recorded_text(observation, "output")
                        or observation.output,
                    ),
                )
            )
        if observation.level in _ERROR_LEVELS:
            timed.append(
                (
                    start,
                    ObservationError(
                        type=observation.type or "observation",
                        name=observation.name or "",
                        level=observation.level or "",
                        message=observation.status_message,
                        agent=agent,
                    ),
                )
            )
    timed.sort(key=lambda entry: entry[0])
    return tuple(event for _, event in timed)


def _when(moment: datetime | None) -> tuple[bool, float]:
    if moment is not None:
        return (False, moment.timestamp())
    return (True, 0.0)


def _plain(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    text = text_of(value, role="assistant") if value is not None else ""
    return text.strip() if isinstance(text, str) else ""


def _system_prompts(value: object) -> list[str]:
    messages = messages_of(value) if value is not None else ()
    if isinstance(messages, Problem):
        return []
    return [m.text for m in messages if m.role == "system" and m.text.strip()]


def _model_texts(observation: Observation) -> list[str]:
    """What a model call wrote: its assistant messages, or a structured output that is not
    chat messages (such as a JSON action) as the application recorded it."""
    value = observation.output
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    messages = messages_of(value)
    if isinstance(messages, Problem):
        return [_shown_payload(_recorded_text(observation, "output") or value, None)]
    return [m.text for m in messages if m.role == "assistant" and m.text.strip()]


def _tools_recorded(
    observation: Observation, by_id: dict[str, Observation]
) -> list[tuple[int, OfferedTool]]:
    """The tools ``observation`` records, each with the rank of its source."""
    metadata = observation.metadata if isinstance(observation.metadata, dict) else {}
    if observation.type == "GENERATION" and isinstance(observation.input, dict):
        agent = _agent_of(observation, by_id)
        entries = observation.input.get("tools")
        return [
            (0, tool)
            for entry in (entries if isinstance(entries, list) else [])
            if (tool := _declared_tool(entry, agent)) is not None
        ]
    if observation.type == "AGENT":
        names = metadata.get("attributes.agno.tools")
        return [
            (1, OfferedTool(name=name, agent=observation.name))
            for name in (names if isinstance(names, list) else [])
            if isinstance(name, str) and name
        ]
    if observation.type == "TOOL":
        name = metadata.get("attributes.tool.name") or observation.name
        description = metadata.get("attributes.tool.description")
        if isinstance(name, str) and name:
            tool = OfferedTool(
                name=name,
                description=description if isinstance(description, str) else None,
                agent=_agent_of(observation, by_id),
            )
            return [(2, tool)]
    return []


def _declared_tool(entry: object, agent: str | None) -> OfferedTool | None:
    """One entry of a ``GENERATION`` input's ``tools`` list, in OpenAI or Anthropic style."""
    if not isinstance(entry, dict):
        return None
    function = entry.get("function")
    spec = function if isinstance(function, dict) else entry
    name = spec.get("name")
    if not isinstance(name, str) or not name:
        return None
    description = spec.get("description")
    parameters = spec.get("parameters", spec.get("input_schema"))
    return OfferedTool(
        name=name,
        description=description if isinstance(description, str) else None,
        parameters=parameters if isinstance(parameters, dict) else None,
        agent=agent,
    )


def _merged(entries: list[tuple[int, OfferedTool]]) -> OfferedTool:
    """One tool from every record of it: for each field, the best-ranked value that is set."""
    ranked = [tool for _, tool in sorted(entries, key=lambda entry: entry[0])]
    first = ranked[0]
    return first.model_copy(
        update={
            "description": next((t.description for t in ranked if t.description), None),
            "parameters": next((t.parameters for t in ranked if t.parameters), None),
        }
    )


def _revision_order(entry: tuple[int, Artifact]) -> tuple[bool, int, int]:
    position, artifact = entry
    turn = artifact.at_simulated_turn
    return (turn is not None, turn or 0, position)


def _recorded_text(
    observation: Observation, field: Literal["input", "output"]
) -> str | None:
    """The payload as the application recorded it: the original string in the Langfuse row.

    Parsing and re-serialising JSON changes it (``10.50`` becomes ``10.5``, indentation is
    lost), so a payload is shown from this text. ``None`` when the row holds no string.
    """
    recorded = observation.raw.get(field)
    return recorded if isinstance(recorded, str) else None


def _level_word(level: str | None) -> str:
    return "warning" if level == "WARNING" else "error"


def _event_lines(
    event: Event, shown_prompts: set[tuple[str | None, str]], max_chars: int | None
) -> list[str]:
    """The lines of one event that is not a tool call. A system prompt already shown in the
    transcript gives no lines."""
    match event:
        case SystemPrompt(agent=agent, text=text):
            if (agent, text) in shown_prompts:
                return []
            shown_prompts.add((agent, text))
            return [f"System prompt{_by(agent)}: {_shown_payload(text, max_chars)}"]
        case ModelOutput(agent=agent, text=text):
            return [f"Model{_by(agent)}: {_shown(text)}"]
        case Handoff(agent=agent, caller=caller, direction="call", payload=payload):
            return [
                f"Handoff to {agent}{_by(caller, 'from')}: "
                f"{_shown_payload(payload, max_chars)}"
            ]
        case Handoff(agent=agent, caller=caller, payload=payload):
            return [
                f"{agent} returned{_by(caller, 'to')}: {_shown_payload(payload, max_chars)}"
            ]
        case ObservationError(
            type=kind, name=name, level=level, message=message, agent=agent
        ):
            detail = f": {message}" if message else ""
            return [f"[{_level_word(level)} on {kind} {name}{_by(agent)}{detail}]"]
    return []


def _by(agent: str | None, word: str = "") -> str:
    if not agent:
        return ""
    return f" ({word} {agent})" if word else f" ({agent})"
