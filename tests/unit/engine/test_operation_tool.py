"""The operation index and the ``operation`` tool of the generic HTTP runner (#482)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from metis.core.trials import TrialConfig
from metis.engine.simulation.artifacts import ArtifactLedger
from metis.engine.simulation.binding import load_target_binding
from metis.engine.simulation.runners.http import HttpRunnerFactory
from metis.engine.simulation.runners.rules import ToolRefused
from metis.engine.simulation.runners.tools import (
    MAX_DEFINITION_CHARS,
    definition,
    operation_index,
)
from tests.unit.engine.test_agent_loop import ScriptedLLM

if TYPE_CHECKING:
    from pathlib import Path

    from metis.engine.simulation.runners.http import HttpRunner

_BINDING = (
    "schema_version: 1\nidentity: {name: App}\ntransport: http\n"
    "spec_url: https://app.example/openapi.json\n"
)


def _chain(*names: str) -> dict[str, Any]:
    """Schemas that each point at the next one, the last holding its own name."""
    schemas: dict[str, Any] = {}
    for here, there in zip(names, names[1:], strict=False):
        schemas[here] = {
            "note": f"in-{here}",
            "next": {"$ref": f"#/components/schemas/{there}"},
        }
    schemas[names[-1]] = {"note": f"in-{names[-1]}"}
    return schemas


SPEC: dict[str, Any] = {
    "info": {"title": "Orders API"},
    "servers": [{"url": "/api"}],
    "paths": {
        "/orders": {
            "post": {
                "summary": "Create an order",
                "operationId": "createOrder",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Order"}
                        }
                    }
                },
            },
            "get": {"operationId": "listOrders"},
        },
        "/orders/{id}": {
            "parameters": [{"name": "id", "in": "path"}],
            "delete": {},
        },
    },
    "components": {
        "schemas": {
            "Order": {
                "type": "object",
                "properties": {"item": {"$ref": "#/components/schemas/Item"}},
            },
            "Item": {"type": "string", "description": "ITEM-MARKER"},
        }
    },
}


async def _runner(tmp_path: Path, llm: ScriptedLLM, spec: dict[str, Any]) -> HttpRunner:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "app.yaml").write_text(_BINDING, encoding="utf-8")

    def target(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/openapi.json":
            return httpx.Response(200, json=spec)
        return httpx.Response(200, json={})

    factory = HttpRunnerFactory(
        load_target_binding(inputs, "app.yaml"),
        transport=httpx.MockTransport(target),
        llm=llm,  # type: ignore[arg-type]
    )
    await factory.start()
    trial = tmp_path / "trial"
    runner = await factory.create(trial, tmp_path, tmp_path)
    runner.use_ledger(ArtifactLedger(tmp_path, trial))
    await runner.setup(TrialConfig(persona="p", scenario="s"))
    return runner


def test_the_index_has_one_line_per_operation() -> None:
    assert operation_index(SPEC).splitlines() == [
        "Orders API",
        "POST /orders - Create an order",
        "GET /orders - listOrders",
        "DELETE /orders/{id}",
    ]


@pytest.mark.asyncio
async def test_the_first_message_holds_the_index_and_no_schemas(tmp_path: Path) -> None:
    llm = ScriptedLLM([("report", {"outcome": "unknown", "why": "x"})])
    runner = await _runner(tmp_path, llm, SPEC)

    await runner.act("Say ⟦hi⟧", [])

    message = llm.first_message()
    assert "POST /orders - Create an order" in message
    assert "not the whole specification" in message
    assert "ITEM-MARKER" not in message and "requestBody" not in message


@pytest.mark.asyncio
async def test_a_specification_without_paths_is_sent_whole_and_operation_refuses(
    tmp_path: Path,
) -> None:
    spec = {"title": "Odd API", "endpoints": {"chat": "POST /talk"}}
    llm = ScriptedLLM(
        [("operation", {"method": "POST", "path": "/talk"})],
        [("report", {"outcome": "unknown", "why": "x"})],
    )
    runner = await _runner(tmp_path, llm, spec)

    await runner.act("Say ⟦hi⟧", [])

    assert "POST /talk" in llm.first_message()  # the text, as before
    assert "not the whole specification" not in llm.first_message()
    result = json.loads(llm.requests[1]["messages"][-1]["content"])
    assert "lists no operations" in result["error"]


@pytest.mark.parametrize(
    "document",
    [
        {"info": {"title": "T"}, "paths": {}},
        {"info": {"title": "T"}, "paths": ["/a", "/b"]},
        {"info": {"title": "T"}, "paths": "none"},
        {"info": {"title": "T"}, "paths": {"/a": {"$ref": "#/components/pathItems/A"}}},
        {"info": {"title": "T"}, "paths": {"/a": {"summary": "no methods"}}},
    ],
)
def test_a_document_with_no_listable_operation_has_an_empty_index(
    document: dict[str, Any],
) -> None:
    assert operation_index(document) == ""
    with pytest.raises(ToolRefused, match="lists no operations"):
        definition(document, "GET", "/a")


@pytest.mark.asyncio
async def test_a_specification_with_nothing_to_index_is_sent_whole(
    tmp_path: Path,
) -> None:
    spec = {"info": {"title": "Odd API"}, "paths": ["/talk"], "marker": "WHOLE-TEXT"}
    llm = ScriptedLLM([("report", {"outcome": "unknown", "why": "x"})])
    runner = await _runner(tmp_path, llm, spec)

    await runner.act("Say ⟦hi⟧", [])

    assert "WHOLE-TEXT" in llm.first_message()
    assert "not the whole specification" not in llm.first_message()


def test_a_definition_follows_a_ref_into_components() -> None:
    found = definition(SPEC, "post", "/orders")

    assert found["operation"] == "POST /orders"
    item = found["definition"]["requestBody"]["content"]["application/json"]["schema"][
        "properties"
    ]["item"]
    assert item["description"] == "ITEM-MARKER"


def test_a_definition_includes_the_parameters_its_path_shares() -> None:
    found = definition(SPEC, "DELETE", "/orders/{id}")

    assert found["definition"]["parameters"] == [{"name": "id", "in": "path"}]


def test_refs_are_followed_three_hops_and_no_further() -> None:
    spec = {
        "paths": {"/x": {"get": {"schema": {"$ref": "#/components/schemas/A"}}}},
        "components": {"schemas": _chain("A", "B", "C", "D")},
    }

    text = json.dumps(definition(spec, "GET", "/x")["definition"])

    assert "in-A" in text and "in-B" in text and "in-C" in text
    assert "in-D" not in text
    assert "#/components/schemas/D" in text  # left as the link


def test_a_ref_that_points_at_itself_ends() -> None:
    spec = {
        "paths": {"/x": {"get": {"schema": {"$ref": "#/components/schemas/Loop"}}}},
        "components": {
            "schemas": {"Loop": {"next": {"$ref": "#/components/schemas/Loop"}}}
        },
    }

    text = json.dumps(definition(spec, "GET", "/x")["definition"])

    assert "#/components/schemas/Loop" in text


def test_a_definition_over_the_cap_is_cut_and_says_so() -> None:
    spec = {"paths": {"/x": {"get": {"description": "w" * 10_000}}}}

    found = definition(spec, "GET", "/x")

    assert len(found["definition"]) == MAX_DEFINITION_CHARS == 6000
    assert "cut" in found and "6,000" in found["cut"]


def test_an_unknown_path_is_refused_with_the_close_ones() -> None:
    with pytest.raises(ToolRefused, match="no operation GET /order") as refused:
        definition(SPEC, "GET", "/order")

    assert "/orders" in str(refused.value)


def test_a_known_path_with_the_wrong_method_lists_the_methods_it_has() -> None:
    with pytest.raises(ToolRefused) as refused:
        definition(SPEC, "PUT", "/orders")

    assert "GET" in str(refused.value) and "POST" in str(refused.value)


@pytest.mark.asyncio
async def test_the_tool_returns_a_definition_and_sends_and_logs_nothing(
    tmp_path: Path,
) -> None:
    llm = ScriptedLLM(
        [("operation", {"method": "POST", "path": "/orders"})],
        [("report", {"outcome": "unknown", "why": "x"})],
    )
    runner = await _runner(tmp_path, llm, SPEC)

    await runner.act("Say ⟦hi⟧", [])

    result = json.loads(llm.requests[1]["messages"][-1]["content"])
    assert result["operation"] == "POST /orders"
    assert "ITEM-MARKER" in json.dumps(result["definition"])
    assert runner.results == []  # no request, so nothing to cite


@pytest.mark.asyncio
async def test_an_unknown_operation_comes_back_as_a_refusal(tmp_path: Path) -> None:
    llm = ScriptedLLM(
        [("operation", {"method": "GET", "path": "/nope"})],
        [("report", {"outcome": "unknown", "why": "x"})],
    )
    runner = await _runner(tmp_path, llm, SPEC)

    await runner.act("Say ⟦hi⟧", [])

    result = json.loads(llm.requests[1]["messages"][-1]["content"])
    assert result["error"].startswith(
        "refused, nothing was sent: no operation GET /nope"
    )
