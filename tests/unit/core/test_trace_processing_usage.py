"""usage_of: the tokens and cost of recorded turns, read from the rows Langfuse returned."""

from __future__ import annotations

from typing import Any

import pytest

from metis.core.trace_processing import (
    Problem,
    Tokens,
    Turn,
    Usage,
    turns,
    usage_of,
)
from metis.core.traces import Observation, Trace

LUNA = "gpt-5.6-luna"
INPUT_PRICE = 2e-7
OUTPUT_PRICE = 1.2e-6


def _row(id: str, *, parent: str | None = "root", **fields: Any) -> dict[str, Any]:
    """A raw camelCase Observations API v2 row."""
    return {
        "id": id,
        "traceId": "t",
        "type": "GENERATION",
        "parentObservationId": parent,
        **fields,
    }


def _generation(
    id: str,
    input: int,
    output: int,
    *,
    model: str | None = LUNA,
    parent: str | None = "root",
    priced: bool = True,
    **extra: int,
) -> dict[str, Any]:
    cost = input * INPUT_PRICE + output * OUTPUT_PRICE
    return _row(
        id,
        parent=parent,
        model=model,
        usageDetails={
            "input": input,
            "output": output,
            "total": input + output,
            **extra,
        },
        costDetails={"total": cost} if priced else {},
        totalCost=cost if priced else None,
    )


def _turns(*rows: dict[str, Any]) -> tuple[Turn, ...]:
    root = _row(
        "root",
        parent=None,
        type="AGENT",
        input="hi",
        output="hello",
        usageDetails={},
        totalCost=None,
    )
    observations = tuple(Observation.model_validate(r) for r in (root, *rows))
    return turns((Trace(id="t", session_id="s", observations=observations),))


def _cost(input: int, output: int) -> float:
    return input * INPUT_PRICE + output * OUTPUT_PRICE


def test_four_generations_of_one_model_are_summed() -> None:
    usage = usage_of(
        _turns(
            _generation("g1", 504, 71),
            _generation("g2", 324, 27),
            _generation("g3", 61, 24),
            _generation("g4", 79, 42),
        )
    )
    assert isinstance(usage, Usage)
    assert usage.tokens == Tokens(input=968, output=164, total=1132)
    assert usage.cost == pytest.approx(0.0003904)
    (luna,) = usage.by_model
    assert luna.model == LUNA
    assert luna.calls == 4
    assert luna.tokens == usage.tokens
    assert luna.cost == pytest.approx(0.0003904)


def test_two_models_are_listed_in_the_order_first_seen() -> None:
    usage = usage_of(
        _turns(
            _generation("g1", 100, 10, model="small"),
            _generation("g2", 200, 20, model=LUNA),
            _generation("g3", 300, 30, model="small"),
        )
    )
    assert isinstance(usage, Usage)
    assert [m.model for m in usage.by_model] == ["small", LUNA]
    small, luna = usage.by_model
    assert small.calls == 2
    assert small.tokens == Tokens(input=400, output=40, total=440)
    assert luna.tokens == Tokens(input=200, output=20, total=220)
    assert usage.tokens == Tokens(input=600, output=60, total=660)
    assert small.cost is not None and luna.cost is not None
    assert small.cost + luna.cost == pytest.approx(usage.cost)


def test_a_parent_with_its_own_usage_is_not_counted_on_top_of_its_children() -> None:
    rolled_up = _row(
        "span",
        type="SPAN",
        usageDetails={"input": 300, "output": 30, "total": 330},
        totalCost=_cost(300, 30),
    )
    usage = usage_of(
        _turns(
            rolled_up,
            _generation("g1", 100, 10, parent="span"),
            _generation("g2", 200, 20, parent="span"),
        )
    )
    assert isinstance(usage, Usage)
    assert usage.tokens == Tokens(input=300, output=30, total=330)
    assert usage.by_model[0].calls == 2


def test_an_unpriced_call_makes_its_models_cost_and_the_total_unknown() -> None:
    usage = usage_of(
        _turns(
            _generation("g1", 100, 10, model="unpriced", priced=False),
            _generation("g2", 200, 20, model=LUNA),
        )
    )
    assert isinstance(usage, Usage)
    assert usage.cost is None
    unpriced, luna = usage.by_model
    assert unpriced.cost is None
    assert unpriced.tokens == Tokens(input=100, output=10, total=110)
    assert luna.cost == pytest.approx(_cost(200, 20))
    assert usage.tokens == Tokens(input=300, output=30, total=330)


def test_a_call_with_no_total_counts_input_plus_output() -> None:
    row = _row(
        "g1",
        model=LUNA,
        usageDetails={"input": 50, "output": 7},
        totalCost=_cost(50, 7),
    )
    usage = usage_of(_turns(row))
    assert isinstance(usage, Usage)
    assert usage.tokens == Tokens(input=50, output=7, total=57)


def test_a_call_with_no_model_is_grouped_under_none() -> None:
    usage = usage_of(
        _turns(
            _generation("g1", 10, 1, model=None), _generation("g2", 20, 2, model=None)
        )
    )
    assert isinstance(usage, Usage)
    (unnamed,) = usage.by_model
    assert (unnamed.model, unnamed.calls) == (None, 2)
    assert unnamed.tokens == Tokens(input=30, output=3, total=33)
    assert unnamed.cost == pytest.approx(_cost(30, 3))


def test_provider_specific_keys_are_summed_in_other() -> None:
    usage = usage_of(
        _turns(
            _generation("g1", 100, 10, input_cached_tokens=40),
            _generation(
                "g2", 100, 10, input_cached_tokens=20, output_reasoning_tokens=5
            ),
        )
    )
    assert isinstance(usage, Usage)
    assert usage.tokens.other == {
        "input_cached_tokens": 60,
        "output_reasoning_tokens": 5,
    }


def test_turns_with_no_usage_give_a_missing_problem() -> None:
    assert usage_of(_turns(_row("g1", model=LUNA))) == Problem(
        kind="missing", detail="no observation records token usage"
    )


def test_no_turns_give_a_missing_problem() -> None:
    assert usage_of(()) == Problem(
        kind="missing", detail="no observation records token usage"
    )
