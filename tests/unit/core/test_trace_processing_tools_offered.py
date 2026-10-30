"""tools_offered: the tools the target had in a session, read from what the traces record."""

from __future__ import annotations

from metis.core.trace_processing import OfferedTool, tools_offered
from metis.core.traces import Observation, Trace
from tests.fixtures.traces import load_session

SCHEMA = {"type": "object", "properties": {"q": {"type": "string"}}}


def _trace(*observations: Observation) -> Trace:
    return Trace(id="t", session_id="s", observations=observations)


def _agent(id: str = "a", name: str = "Planner", **fields: object) -> Observation:
    return Observation(id=id, trace_id="t", type="AGENT", name=name, **fields)  # type: ignore[arg-type]


def _generation(tools: list[object], parent: str | None = "a") -> Observation:
    return Observation(
        id="g",
        trace_id="t",
        type="GENERATION",
        parent_observation_id=parent,
        input={"messages": [], "tools": tools},
    )


def test_openai_style_tools_are_read_from_a_generation() -> None:
    tool = {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Searches.",
            "parameters": SCHEMA,
        },
    }
    traces = (_trace(_agent(), _generation([tool])),)
    assert tools_offered(traces) == (
        OfferedTool(
            name="search", description="Searches.", parameters=SCHEMA, agent="Planner"
        ),
    )


def test_anthropic_style_tools_are_read_from_a_generation() -> None:
    tool = {"name": "search", "description": "Searches.", "input_schema": SCHEMA}
    traces = (_trace(_generation([tool], parent=None)),)
    assert tools_offered(traces) == (
        OfferedTool(name="search", description="Searches.", parameters=SCHEMA),
    )


def test_agent_metadata_names_the_agents_tools() -> None:
    agent = _agent(metadata={"attributes.agno.tools": ["search", "fetch"]})
    assert tools_offered((_trace(agent),)) == (
        OfferedTool(name="search", agent="Planner"),
        OfferedTool(name="fetch", agent="Planner"),
    )


def test_a_called_tool_gives_its_name_and_description() -> None:
    call = Observation(
        id="c",
        trace_id="t",
        type="TOOL",
        name="search",
        parent_observation_id="a",
        metadata={
            "attributes.tool.name": "search",
            "attributes.tool.description": "Searches the index.",
        },
    )
    assert tools_offered((_trace(_agent(), call),)) == (
        OfferedTool(name="search", description="Searches the index.", agent="Planner"),
    )


def test_one_tool_per_agent_and_name_with_the_best_details() -> None:
    agent = _agent(metadata={"attributes.agno.tools": ["search"]})
    declared = _generation([{"type": "function", "function": {"name": "search"}}])
    call = Observation(
        id="c",
        trace_id="t",
        type="TOOL",
        name="search",
        parent_observation_id="a",
        metadata={"attributes.tool.description": "Searches the index."},
    )
    other = _agent(
        id="b", name="Writer", metadata={"attributes.agno.tools": ["search"]}
    )
    traces = (_trace(agent, declared, call, other), _trace(agent, declared))
    assert tools_offered(traces) == (
        OfferedTool(name="search", description="Searches the index.", agent="Planner"),
        OfferedTool(name="search", agent="Writer"),
    )


def test_entries_in_another_shape_are_skipped() -> None:
    traces = (_trace(_generation(["search", {"type": "function"}, {"name": ""}])),)
    assert tools_offered(traces) == ()


def test_the_helpdesk_session_offers_each_agents_tools() -> None:
    tools = tools_offered(load_session().traces)
    by_agent: dict[str | None, list[str]] = {}
    for tool in tools:
        by_agent.setdefault(tool.agent, []).append(tool.name)
    assert {agent: len(names) for agent, names in by_agent.items()} == {
        "Coordinator.arun": 3,
        "Data_Analyst.arun": 2,
        "Report_Writer.arun": 2,
    }
    assert "build_report" in by_agent["Report_Writer.arun"]
    [build_report] = [t for t in tools if t.name == "build_report"]
    assert build_report.description is not None
    assert build_report.description.startswith("Create a brand-new report")
