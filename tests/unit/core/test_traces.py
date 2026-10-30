"""Observation, Trace and GradingInput: what a grader reads.

Ported from tests/unit/engine/test_extractor_root_selection.py (which goes away in this task)
plus the guarantees the grader contract adds: frozen inputs, tuples, sorted observations, and
a never-empty trace.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from metis.core import Artifact
from metis.core.traces import GradingInput, Observation, Trace


def _row(**overrides: object) -> dict[str, object]:
    """A raw Observations API v2 row, camelCase as the API sends it."""
    row: dict[str, object] = {
        "id": "obs-1",
        "traceId": "trace-1",
        "sessionId": "sess-1",
        "name": "root-span",
        "type": "SPAN",
        "input": "in",
        "output": "out",
        "metadata": None,
        "startTime": None,
        "endTime": None,
        "parentObservationId": None,
    }
    row.update(overrides)
    return row


def _obs(
    obs_id: str,
    *,
    parent: str | None = None,
    is_root: bool | None = None,
    start: datetime | None = None,
    output: object = None,
) -> Observation:
    return Observation(
        id=obs_id,
        trace_id="t1",
        parent_observation_id=parent,
        is_root_observation=is_root,
        start_time=start,
        output=output,
    )


def _trace(*observations: Observation) -> Trace:
    return Trace(id="t1", session_id="sess-1", observations=observations)


def _t(second: int) -> datetime:
    return datetime(2026, 1, 1, 0, 0, second, tzinfo=UTC)


class TestObservationValidation:
    def test_parses_camel_case_api_row(self) -> None:
        obs = Observation.model_validate(
            _row(
                startTime="2026-01-01T00:00:00.000Z",
                isRootObservation=True,
                metadata={"k": "v"},
            )
        )
        assert obs.trace_id == "trace-1"
        assert obs.session_id == "sess-1"
        assert obs.start_time == datetime(2026, 1, 1, tzinfo=UTC)
        assert obs.is_root_observation is True
        assert obs.metadata == {"k": "v"}

    def test_only_the_two_ids_are_required(self) -> None:
        obs = Observation.model_validate({"id": "o", "traceId": "t"})
        assert obs.session_id is None
        assert obs.type is None
        assert obs.is_root_observation is None

    def test_unknown_api_fields_are_dropped(self) -> None:
        obs = Observation.model_validate(_row(usageDetails={"input": 3}))
        assert not hasattr(obs, "usage_details")

    def test_unknown_observation_type_is_accepted(self) -> None:
        """Langfuse adds observation types; a Literal would reject them all."""
        assert (
            Observation.model_validate(_row(type="SOMETHING_NEW")).type
            == "SOMETHING_NEW"
        )

    def test_plain_text_io_stays_a_string(self) -> None:
        obs = Observation.model_validate(_row(input="42", output="true"))
        assert obs.input == "42"
        assert obs.output == "true"

    def test_json_object_string_is_parsed(self) -> None:
        obs = Observation.model_validate(
            _row(output='{"messages": [{"role": "assistant", "content": "hi"}]}')
        )
        assert obs.output == {"messages": [{"role": "assistant", "content": "hi"}]}

    def test_json_array_string_is_parsed(self) -> None:
        assert Observation.model_validate(_row(input="[1, 2, 3]")).input == [1, 2, 3]

    def test_malformed_json_looking_string_is_kept(self) -> None:
        assert Observation.model_validate(_row(input="{not json")).input == "{not json"

    def test_dict_and_list_io_pass_through(self) -> None:
        obs = Observation.model_validate(_row(input={"a": 1}, output=[1, 2]))
        assert obs.input == {"a": 1}
        assert obs.output == [1, 2]

    def test_is_frozen(self) -> None:
        obs = Observation.model_validate(_row())
        with pytest.raises(ValidationError):
            obs.output = "changed"  # type: ignore[misc]


class TestObservationRaw:
    """``raw`` keeps the row exactly as the API sent it, so a saved trace loses nothing."""

    def test_raw_keeps_fields_observation_does_not_model(self) -> None:
        obs = Observation.model_validate(_row(someNewField=7))
        assert obs.raw["someNewField"] == 7

    def test_raw_keeps_unparsed_io_and_original_timestamps(self) -> None:
        obs = Observation.model_validate(
            _row(input='{"a": 1}', startTime="2026-01-01T00:00:00.000Z")
        )
        assert obs.input == {"a": 1}
        assert obs.raw["input"] == '{"a": 1}'
        assert obs.raw["startTime"] == "2026-01-01T00:00:00.000Z"

    def test_raw_is_not_dumped_or_shown(self) -> None:
        obs = Observation.model_validate(_row())
        assert "raw" not in obs.model_dump()
        assert "raw" not in repr(obs)


class TestTraceObservations:
    def test_empty_trace_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Trace(id="t1", session_id="s", observations=())

    def test_list_is_stored_as_tuple(self) -> None:
        trace = Trace(id="t1", session_id="s", observations=[_obs("o1")])  # type: ignore[arg-type]
        assert isinstance(trace.observations, tuple)

    def test_observations_are_sorted_oldest_first_with_missing_times_last(self) -> None:
        trace = _trace(
            _obs("late", start=_t(5)),
            _obs("no-time-a", parent="late"),
            _obs("early", parent="late", start=_t(1)),
            _obs("no-time-b", parent="late"),
        )
        assert [o.id for o in trace.observations] == [
            "early",
            "late",
            "no-time-a",
            "no-time-b",
        ]

    def test_from_observations_builds_a_sorted_trace(self) -> None:
        trace = Trace.from_observations(
            "t1", "s", [_obs("b", start=_t(2)), _obs("a", start=_t(1))]
        )
        assert [o.id for o in trace.observations] == ["a", "b"]
        assert trace.session_id == "s"

    def test_is_frozen(self) -> None:
        trace = _trace(_obs("o1"))
        with pytest.raises(ValidationError):
            trace.observations = ()  # type: ignore[misc]


class TestTraceRoot:
    def test_flag_wins_over_parentage(self) -> None:
        trace = _trace(
            _obs("o1", parent=None, is_root=False),
            _obs("o2", parent="o1", is_root=True),
        )
        assert trace.root.id == "o2"

    def test_falls_back_to_parentless_when_flag_absent_everywhere(self) -> None:
        trace = _trace(_obs("o1"), _obs("o2", parent="o1"))
        assert trace.root.id == "o1"

    def test_flag_false_everywhere_does_not_fall_back_to_parentage(self) -> None:
        """The flag is present (False) on every row, so it is not 'absent': zero roots."""
        trace = _trace(
            _obs("o1", is_root=False, start=_t(5)),
            _obs("o2", parent="o1", is_root=False, start=_t(1)),
        )
        assert trace.root.id == "o2"  # zero candidates -> earliest of all

    def test_zero_candidates_resolve_to_earliest(self) -> None:
        trace = _trace(
            _obs("o1", parent="gone", start=_t(5)),
            _obs("o2", parent="gone", start=_t(1)),
        )
        assert trace.root.id == "o2"

    def test_several_candidates_resolve_to_earliest(self) -> None:
        trace = _trace(
            _obs("o1", is_root=True, start=_t(5)),
            _obs("o2", is_root=True, start=_t(1)),
        )
        assert trace.root.id == "o2"

    def test_missing_start_time_counts_as_earliest_in_the_tie_break(self) -> None:
        trace = _trace(
            _obs("o1", is_root=True, start=_t(5)),
            _obs("o2", is_root=True, start=None),
        )
        assert trace.root.id == "o2"

    def test_ambiguous_root_does_not_raise(self) -> None:
        trace = _trace(_obs("o1", parent="gone"))
        assert trace.root.id == "o1"


class TestGradingInput:
    def test_holds_traces_including_ones_without_output(self) -> None:
        crashed = Trace(id="t2", session_id="s", observations=[_obs("x", output=None)])  # type: ignore[arg-type]
        answered = _trace(_obs("o1", output="hello"))
        grading_input = GradingInput(traces=[answered, crashed])  # type: ignore[arg-type]
        assert grading_input.traces == (answered, crashed)
        assert grading_input.traces[1].root.output is None

    def test_artifacts_default_to_empty_tuple(self) -> None:
        assert GradingInput(traces=()).artifacts == ()

    def test_artifacts_are_stored_as_tuple(self) -> None:
        artifact = Artifact(name="deck.pptx", state="received", path="/tmp/deck.pptx")
        grading_input = GradingInput(traces=(), artifacts=[artifact])  # type: ignore[arg-type]
        assert grading_input.artifacts == (artifact,)

    def test_is_frozen(self) -> None:
        grading_input = GradingInput(traces=())
        with pytest.raises(ValidationError):
            grading_input.traces = ()  # type: ignore[misc]


class TestLevelAndRootTieBreak:
    def test_level_and_status_message_are_read(self) -> None:
        obs = Observation.model_validate(
            _row(level="ERROR", statusMessage="tool timed out")
        )
        assert obs.level == "ERROR"
        assert obs.status_message == "tool timed out"

    def test_a_flagged_root_with_a_parent_loses_to_a_parentless_one(self) -> None:
        """A sub-agent's top span flagged as root (as some frameworks do) is not the trace's
        root, even when it starts first."""
        sub = _obs("sub", parent="top", is_root=True, start=_t(0))
        top = _obs("top", parent=None, is_root=True, start=_t(1))
        assert _trace(sub, top).root.id == "top"
