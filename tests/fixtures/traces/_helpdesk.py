"""The rows of the synthetic helpdesk session, as Langfuse Observations API v2 returns them.

The session is invented. A coordinator agent answers questions about support tickets and
hands some of the work to two sub-agents. It is built to give the trace processor and the
graders every shape they read:

====  ==========================================  ==========================================
Turn  What happens                                Shape it covers
====  ==========================================  ==========================================
1     One tool call; its result is a Python       A tool result that is a string, not JSON
      dict printed as text
2     A search tool returns a JSON array          A list result
3     The user corrects the assistant; a          A sub-agent, a tool call inside it, and a
      sub-agent runs a query                      correction for a later turn to support
4     The assistant asks a question back          A turn with no tool call
5     A long message ending in a form response;   A tool call two levels down, and a user
      a second sub-agent builds a report          message that must survive in full
====  ==========================================  ==========================================
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

SESSION_ID = "sess-helpdesk-0001"

_COORDINATOR = "Coordinator.arun"
_ANALYST = "Data_Analyst.arun"
_WRITER = "Report_Writer.arun"

_TOOLS = {
    _COORDINATOR: ("delegate_to_agent", "search_knowledge_base", "ask_user_question"),
    _ANALYST: ("query_table", "summarise_table"),
    _WRITER: ("list_templates", "build_report"),
}

_BUILD_REPORT_DESCRIPTION = (
    "Create a brand-new report from a template and a table of figures."
)

_SYSTEM = {
    _COORDINATOR: "You help support managers with ticket questions. Delegate data pulls.",
    _ANALYST: "You query the ticket tables and report the figures you find.",
    _WRITER: "You turn figures into a finished report using a template.",
}

_START = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)

_FORM_RESPONSE_PREAMBLE = (
    "Thanks for asking. I will use the report for the monthly review with the support "
    "managers, who read it on their phones between meetings, so it has to be short and "
    "easy to scan.\n\n"
    "Last time the review ran long because the figures were buried in paragraphs. "
    "Please keep any commentary to a sentence or two, put the numbers first, and keep "
    "the category names exactly as they appear in the ticket system.\n\n"
    "Form response: "
)


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


class _Turn:
    """Builds the observations of one trace, one second after the previous call."""

    def __init__(self, number: int) -> None:
        self.number = number
        self.rows: list[dict[str, Any]] = []
        self._clock = _START + timedelta(minutes=10 * number)

    def add(
        self,
        kind: str,
        name: str,
        *,
        parent: str | None,
        seconds: float,
        input: object,
        output: object,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        start = self._clock
        end = start + timedelta(seconds=seconds)
        self._clock = start + timedelta(seconds=0.5)
        observation_id = f"obs-{self.number}-{len(self.rows) + 1:02d}"
        self.rows.append(
            {
                "id": observation_id,
                "traceId": f"{self.number:032x}",
                "sessionId": SESSION_ID,
                "parentObservationId": parent,
                "isRootObservation": parent is None,
                "type": kind,
                "name": name,
                "level": "DEFAULT",
                "statusMessage": "",
                "startTime": _stamp(start),
                "endTime": _stamp(end),
                "input": input if isinstance(input, str) else json.dumps(input),
                "output": output if isinstance(output, str) else json.dumps(output),
                "metadata": metadata or {},
            }
        )
        return observation_id

    def close(self, observation_id: str) -> None:
        """Move the clock to the end of ``observation_id``, so its parent ends after it."""
        row = next(r for r in self.rows if r["id"] == observation_id)
        end = datetime.fromisoformat(row["endTime"].replace("Z", "+00:00"))
        self._clock = max(self._clock, end)


def _tools(agent: str) -> list[dict[str, Any]]:
    return [{"type": "function", "function": {"name": n}} for n in _TOOLS[agent]]


def _call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "tool_calls": [
            {
                "id": f"call-{name}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    }


def _model_call(
    turn: _Turn,
    agent: str,
    parent: str,
    history: list[dict[str, Any]],
    reply: dict[str, Any],
) -> None:
    messages = [{"role": "system", "content": _SYSTEM[agent]}, *history]
    turn.add(
        "GENERATION",
        "Claude.ainvoke_stream",
        parent=parent,
        seconds=2.0,
        input={"messages": messages, "tools": _tools(agent)},
        output={"messages": [reply]},
        metadata={"attributes.llm.model_name": "synthetic-model"},
    )


def _agent(turn: _Turn, name: str, parent: str, user: str, reply: str) -> str:
    return turn.add(
        "AGENT",
        name,
        parent=parent,
        seconds=30.0,
        input=user,
        output=reply,
        metadata={"attributes.agno.tools": list(_TOOLS[name])},
    )


def _answer(text: str) -> dict[str, Any]:
    return {"role": "assistant", "content": text}


def _tool_result(name: str, result: str) -> dict[str, Any]:
    return {"role": "tool", "name": name, "content": result}


def _root(turn: _Turn, user: str, reply: str) -> tuple[str, str]:
    root = turn.add(
        "SPAN",
        "helpdesk-chat",
        parent=None,
        seconds=60.0,
        input=user,
        output=reply,
    )
    return root, _agent(turn, _COORDINATOR, root, user, reply)


def _turn_one() -> list[dict[str, Any]]:
    user = "Can you pull last month's support ticket numbers?"
    summary = (
        "In December, 412 tickets were opened and 389 were closed, leaving 23 open."
    )
    result = "{'_type': 'agent_result', 'agent': 'data_analyst', 'opened': 412, 'closed': 389}"
    arguments = {
        "agent_key": "data_analyst",
        "task": "Count December tickets by status.",
    }
    turn = _Turn(1)
    _, coordinator = _root(turn, user, summary)
    history = [{"role": "user", "content": user}]
    _model_call(
        turn, _COORDINATOR, coordinator, history, _call("delegate_to_agent", arguments)
    )
    turn.add(
        "TOOL",
        "delegate_to_agent",
        parent=coordinator,
        seconds=5.0,
        input=arguments,
        output=result,
        metadata={"attributes.tool.name": "delegate_to_agent"},
    )
    _model_call(
        turn,
        _COORDINATOR,
        coordinator,
        [
            *history,
            _call("delegate_to_agent", arguments),
            _tool_result("delegate_to_agent", result),
        ],
        _answer(summary),
    )
    return turn.rows


def _turn_two() -> list[dict[str, Any]]:
    user = "Which categories got the most tickets?"
    reply = (
        "Billing had the most tickets (140), then Login (97) and Shipping (81). The other "
        "94 were spread across smaller categories."
    )
    arguments = {"query": "ticket categories December"}
    hits = [
        {
            "title": "Ticket categories",
            "snippet": "Billing 140, Login 97, Shipping 81, Other 94",
        }
    ]
    turn = _Turn(2)
    _, coordinator = _root(turn, user, reply)
    history = [{"role": "user", "content": user}]
    _model_call(
        turn,
        _COORDINATOR,
        coordinator,
        history,
        _call("search_knowledge_base", arguments),
    )
    turn.add(
        "TOOL",
        "search_knowledge_base",
        parent=coordinator,
        seconds=1.0,
        input=arguments,
        output=hits,
        metadata={"attributes.tool.name": "search_knowledge_base"},
    )
    _model_call(
        turn,
        _COORDINATOR,
        coordinator,
        [
            *history,
            _call("search_knowledge_base", arguments),
            _tool_result("search_knowledge_base", json.dumps(hits)),
        ],
        _answer(reply),
    )
    return turn.rows


def _turn_three() -> list[dict[str, Any]]:
    user = "That's not what I wanted. I meant tickets closed per category, not opened."
    reply = (
        "Sorry for the mix-up. Closed tickets by category: Billing 131, Login 90, "
        "Shipping 74, Other 94."
    )
    task = "List closed tickets per category for December."
    delegate = {"agent_key": "data_analyst", "task": task}
    query = {"table": "tickets", "filter": "status=closed", "group_by": "category"}
    table = {
        "rows": [
            {"category": "Billing", "closed": 131},
            {"category": "Login", "closed": 90},
            {"category": "Shipping", "closed": 74},
            {"category": "Other", "closed": 94},
        ]
    }
    turn = _Turn(3)
    _, coordinator = _root(turn, user, reply)
    history = [{"role": "user", "content": user}]
    _model_call(
        turn, _COORDINATOR, coordinator, history, _call("delegate_to_agent", delegate)
    )
    handoff = turn.add(
        "TOOL",
        "delegate_to_agent",
        parent=coordinator,
        seconds=20.0,
        input=delegate,
        output=json.dumps(table),
        metadata={"attributes.tool.name": "delegate_to_agent"},
    )
    analyst = _agent(turn, _ANALYST, handoff, task, json.dumps(table))
    task_history = [{"role": "user", "content": task}]
    _model_call(turn, _ANALYST, analyst, task_history, _call("query_table", query))
    turn.add(
        "TOOL",
        "query_table",
        parent=analyst,
        seconds=2.0,
        input=query,
        output=table,
        metadata={"attributes.tool.name": "query_table"},
    )
    _model_call(
        turn,
        _ANALYST,
        analyst,
        [
            *task_history,
            _call("query_table", query),
            _tool_result("query_table", json.dumps(table)),
        ],
        _answer(json.dumps(table)),
    )
    turn.close(analyst)
    _model_call(
        turn,
        _COORDINATOR,
        coordinator,
        [
            *history,
            _call("delegate_to_agent", delegate),
            _tool_result("delegate_to_agent", json.dumps(table)),
        ],
        _answer(reply),
    )
    return turn.rows


def _turn_four() -> list[dict[str, Any]]:
    user = "Can you make this into a report?"
    reply = "Happy to. Who is the report for, and would you like a table or a chart?"
    turn = _Turn(4)
    _, coordinator = _root(turn, user, reply)
    _model_call(
        turn,
        _COORDINATOR,
        coordinator,
        [{"role": "user", "content": user}],
        _answer(reply),
    )
    return turn.rows


def _turn_five() -> list[dict[str, Any]]:
    user = _FORM_RESPONSE_PREAMBLE + '{"audience":"support managers","format":"table"}'
    reply = "The December support summary is ready as a table for the support managers."
    task = "Build the December support summary as a table for support managers."
    delegate = {"agent_key": "report_writer", "task": task}
    templates = ["table", "chart", "narrative"]
    build = {"title": "December support summary", "template": "table"}
    built = {"status": "created", "file": "december-support-summary.md"}
    turn = _Turn(5)
    _, coordinator = _root(turn, user, reply)
    history = [{"role": "user", "content": user}]
    _model_call(
        turn, _COORDINATOR, coordinator, history, _call("delegate_to_agent", delegate)
    )
    handoff = turn.add(
        "TOOL",
        "delegate_to_agent",
        parent=coordinator,
        seconds=25.0,
        input=delegate,
        output=json.dumps(built),
        metadata={"attributes.tool.name": "delegate_to_agent"},
    )
    writer = _agent(turn, _WRITER, handoff, task, json.dumps(built))
    task_history = [{"role": "user", "content": task}]
    _model_call(turn, _WRITER, writer, task_history, _call("list_templates", {}))
    turn.add(
        "TOOL",
        "list_templates",
        parent=writer,
        seconds=1.0,
        input={},
        output=templates,
        metadata={"attributes.tool.name": "list_templates"},
    )
    listed = [
        *task_history,
        _call("list_templates", {}),
        _tool_result("list_templates", json.dumps(templates)),
    ]
    _model_call(turn, _WRITER, writer, listed, _call("build_report", build))
    turn.add(
        "TOOL",
        "build_report",
        parent=writer,
        seconds=8.0,
        input=build,
        output=built,
        metadata={
            "attributes.tool.name": "build_report",
            "attributes.tool.description": _BUILD_REPORT_DESCRIPTION,
        },
    )
    _model_call(
        turn,
        _WRITER,
        writer,
        [
            *listed,
            _call("build_report", build),
            _tool_result("build_report", json.dumps(built)),
        ],
        _answer(json.dumps(built)),
    )
    turn.close(writer)
    _model_call(
        turn,
        _COORDINATOR,
        coordinator,
        [
            *history,
            _call("delegate_to_agent", delegate),
            _tool_result("delegate_to_agent", json.dumps(built)),
        ],
        _answer(reply),
    )
    return turn.rows


def rows() -> list[dict[str, Any]]:
    """Every observation of the session, as the Observations API v2 returns them."""
    return [
        row
        for build in (_turn_one, _turn_two, _turn_three, _turn_four, _turn_five)
        for row in build()
    ]
