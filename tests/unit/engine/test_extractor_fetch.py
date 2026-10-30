"""fetch_session: one Langfuse session as the GradingInput its grader runs share.

Every test mocks ``observations_v_2.get_many``, so nothing touches the network. The mock answers
by filter column, so a fetch that wrongly reused the session-filtered list as a trace's
observations (issue #435) gets different, smaller data and fails.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from metis.core import Artifact
from metis.engine.extractor.langfuse import (
    UnsupportedTraceError,
    _fetch_trace,
    _page_through_observations,
    fetch_session,
)

LONG = "x" * 250


def _obs(
    obs_id: str,
    trace_id: str,
    *,
    session_id: str | None = "s1",
    parent: str | None = None,
    output: object = "an answer",
    start: str | None = "2026-01-01T00:00:00Z",
    metadata: object = None,
) -> dict[str, Any]:
    """A raw camelCase Observations API v2 row."""
    return {
        "id": obs_id,
        "traceId": trace_id,
        "sessionId": session_id,
        "name": "chat-turn" if parent is None else "child",
        "type": "AGENT",
        "input": "a question",
        "output": output,
        "metadata": metadata,
        "startTime": start,
        "endTime": None,
        "parentObservationId": parent,
    }


def _page(data: list[dict[str, Any]], cursor: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(data=data, meta=SimpleNamespace(cursor=cursor))


def _filter(kwargs: dict[str, Any]) -> tuple[str, str]:
    (condition,) = json.loads(kwargs["filter"])
    return condition["column"], condition["value"]


class FakeLangfuse:
    """Answers get_many from canned rows keyed by (column, value), one page per call."""

    def __init__(
        self,
        *,
        session: list[dict[str, Any]],
        traces: dict[str, list[dict[str, Any]]],
        expanded: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        self.session = session
        self.traces = traces
        self.expanded = expanded or {}
        self.calls: list[dict[str, Any]] = []
        self.api = SimpleNamespace(
            observations_v_2=SimpleNamespace(get_many=self._get_many)
        )

    def _get_many(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        column, value = _filter(kwargs)
        if column == "sessionId":
            return _page(self.session)
        if column == "traceId":
            if kwargs.get("expand_metadata") and value in self.expanded:
                return _page(self.expanded[value])
            return _page(self.traces.get(value, []))
        raise AssertionError(f"unexpected filter column {column}")

    def trace_calls(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if _filter(c)[0] == "traceId"]


def _fetch(lf: FakeLangfuse, tmp_path: Path, **kwargs: Any):
    return fetch_session("s1", lf, experiment_root=tmp_path, **kwargs)  # type: ignore[arg-type]


class TestPaging:
    def test_follows_every_cursor_page(self) -> None:
        lf = MagicMock()
        lf.api.observations_v_2.get_many.side_effect = [
            _page([_obs("o1", "t1")], cursor="next"),
            _page([_obs("o2", "t1", parent="o1")]),
        ]
        observations = _page_through_observations(lf, "traceId", "t1")
        assert [o.id for o in observations] == ["o1", "o2"]
        assert lf.api.observations_v_2.get_many.call_count == 2
        second = lf.api.observations_v_2.get_many.call_args_list[1].kwargs
        assert second["cursor"] == "next"

    def test_request_shape(self) -> None:
        lf = MagicMock()
        lf.api.observations_v_2.get_many.return_value = _page([])
        _page_through_observations(lf, "sessionId", "s1")
        kwargs = lf.api.observations_v_2.get_many.call_args.kwargs
        assert kwargs["fields"] == "core,basic,io,metadata"
        assert kwargs["limit"] == 1000
        assert _filter(kwargs) == ("sessionId", "s1")
        assert kwargs["expand_metadata"] is None

    def test_never_sends_parse_io_as_json(self) -> None:
        """The v2 endpoint rejects it with HTTP 400; the key must not be sent at all."""
        lf = MagicMock()
        lf.api.observations_v_2.get_many.return_value = _page([])
        _page_through_observations(lf, "traceId", "t1")
        assert (
            "parse_io_as_json" not in lf.api.observations_v_2.get_many.call_args.kwargs
        )


class TestTwoStepFetch:
    def test_trace_observations_come_from_the_trace_filter(
        self, tmp_path: Path
    ) -> None:
        """The session filter drops agent-run spans and session-less rows."""
        root = _obs("root", "t1")
        agent = _obs("agent", "t1", session_id="agno-uuid", parent="root")
        no_session = _obs("gen", "t1", session_id=None, parent="agent")
        lf = FakeLangfuse(session=[root], traces={"t1": [root, agent, no_session]})

        grading_input = _fetch(lf, tmp_path)

        (trace,) = grading_input.traces
        assert {o.id for o in trace.observations} == {"root", "agent", "gen"}
        assert trace.root.id == "root"

    def test_one_trace_call_per_trace(self, tmp_path: Path) -> None:
        lf = FakeLangfuse(
            session=[_obs("r1", "t1"), _obs("c1", "t1", parent="r1"), _obs("r2", "t2")],
            traces={"t1": [_obs("r1", "t1")], "t2": [_obs("r2", "t2")]},
        )
        _fetch(lf, tmp_path)
        assert sorted(_filter(c)[1] for c in lf.trace_calls()) == ["t1", "t2"]

    def test_traces_are_ordered_by_root_start_time(self, tmp_path: Path) -> None:
        late = _obs("r2", "t2", start="2026-01-01T00:05:00Z")
        early = _obs("r1", "t1", start="2026-01-01T00:01:00Z")
        lf = FakeLangfuse(session=[late, early], traces={"t1": [early], "t2": [late]})
        assert [t.id for t in _fetch(lf, tmp_path).traces] == ["t1", "t2"]

    def test_trace_without_output_is_kept(self, tmp_path: Path) -> None:
        """A crashed exchange is part of what the target did; graders decide what to skip."""
        crashed = _obs("r1", "t1", output=None)
        lf = FakeLangfuse(session=[crashed], traces={"t1": [crashed]})
        (trace,) = _fetch(lf, tmp_path).traces
        assert trace.root.output is None

    def test_every_trace_is_kept_however_many(self, tmp_path: Path) -> None:
        """No cap on traces per session: the old fetch's limit=50 is gone."""
        rows = [
            _obs(f"r{i}", f"t{i}", start=f"2026-01-01T00:{i:02d}:00Z")
            for i in range(60)
        ]
        lf = FakeLangfuse(session=rows, traces={r["traceId"]: [r] for r in rows})
        assert len(_fetch(lf, tmp_path).traces) == 60

    def test_trace_empty_by_trace_id_is_skipped_not_fatal(self, tmp_path: Path) -> None:
        """Found by the session filter, empty by traceId: an ingestion race."""
        good = _obs("r1", "t1")
        lf = FakeLangfuse(session=[good, _obs("r2", "t2")], traces={"t1": [good]})
        assert [t.id for t in _fetch(lf, tmp_path).traces] == ["t1"]

    def test_empty_session_gives_empty_input(self, tmp_path: Path) -> None:
        lf = FakeLangfuse(session=[], traces={})
        grading_input = _fetch(lf, tmp_path)
        assert grading_input.traces == ()
        assert grading_input.artifacts == ()

    def test_polls_until_traces_appear(self, tmp_path: Path, monkeypatch: Any) -> None:
        root = _obs("r1", "t1")
        lf = FakeLangfuse(session=[], traces={"t1": [root]})
        sleeps: list[float] = []

        def _sleep(seconds: float) -> None:
            sleeps.append(seconds)
            lf.session = [root]  # ingestion catches up while we wait

        monkeypatch.setattr("metis.engine.extractor.langfuse.time.sleep", _sleep)
        grading_input = _fetch(lf, tmp_path, retry_timeout=60)
        assert [t.id for t in grading_input.traces] == ["t1"]
        assert sleeps == [10]


class TestMetadataExpansion:
    def test_short_metadata_is_fetched_once(self) -> None:
        root = _obs("r1", "t1", metadata={"mode": "direct"})
        lf = FakeLangfuse(session=[root], traces={"t1": [root]})
        _fetch_trace(lf, "t1")  # type: ignore[arg-type]
        assert len(lf.trace_calls()) == 1

    def test_possibly_truncated_metadata_is_refetched_with_every_key_expanded(
        self,
    ) -> None:
        cut = _obs("r1", "t1", metadata={"mode": "direct", "summary": "x" * 200})
        child = _obs("c1", "t1", parent="r1", metadata={"plan": "short"})
        full = _obs("r1", "t1", metadata={"mode": "direct", "summary": LONG})
        lf = FakeLangfuse(
            session=[cut],
            traces={"t1": [cut, child]},
            expanded={"t1": [full, child]},
        )

        observations = _fetch_trace(lf, "t1")  # type: ignore[arg-type]

        calls = lf.trace_calls()
        assert len(calls) == 2
        assert calls[1]["expand_metadata"] == "mode,plan,summary"
        root = next(o for o in observations if o.id == "r1")
        assert root.metadata == {"mode": "direct", "summary": LONG}

    def test_non_string_metadata_never_triggers_a_refetch(self) -> None:
        root = _obs("r1", "t1", metadata={"routed_to_agents": ["a"] * 100, "n": 5})
        lf = FakeLangfuse(session=[root], traces={"t1": [root]})
        _fetch_trace(lf, "t1")  # type: ignore[arg-type]
        assert len(lf.trace_calls()) == 1


class TestArtifacts:
    def test_paths_are_resolved_against_the_experiment_root(
        self, tmp_path: Path
    ) -> None:
        root = _obs("r1", "t1")
        lf = FakeLangfuse(session=[root], traces={"t1": [root]})
        artifacts = [
            Artifact(
                name="deck.pptx",
                path="runs/a/deck.pptx",
                at_simulated_turn=2,
                state="received",
            ),
            Artifact(name="gone.csv", state="unavailable"),
        ]

        grading_input = _fetch(lf, tmp_path, artifacts=artifacts)

        deck, gone = grading_input.artifacts
        assert deck.path == str(tmp_path / "runs/a/deck.pptx")
        assert deck.at_simulated_turn == 2
        assert gone.path is None

    def test_every_artifact_is_attached_regardless_of_turn(
        self, tmp_path: Path
    ) -> None:
        """Artifacts cannot be tied to traces reliably (#428 known gap), so none are filtered."""
        root = _obs("r1", "t1")
        lf = FakeLangfuse(session=[root], traces={"t1": [root]})
        artifacts = [
            Artifact(name=f"f{i}", path=f"f{i}", at_simulated_turn=i, state="received")
            for i in range(5)
        ]
        assert len(_fetch(lf, tmp_path, artifacts=artifacts).artifacts) == 5

    def test_input_artifacts_are_not_mutated(self, tmp_path: Path) -> None:
        root = _obs("r1", "t1")
        lf = FakeLangfuse(session=[root], traces={"t1": [root]})
        original = Artifact(name="a", path="rel/a", state="received")
        _fetch(lf, tmp_path, artifacts=[original])
        assert original.path == "rel/a"


class TestTracesFromBeforeTheV4Upgrade:
    """Such traces come back with every observation doubled and a ``t-<traceId>``
    root, and the stored set changes with page size, so they are rejected, not repaired."""

    def test_synthetic_root_fails_the_session(self, tmp_path: Path) -> None:
        root = _obs("r1", "t1")
        synthetic = _obs("t-t1", "t1")
        lf = FakeLangfuse(session=[root], traces={"t1": [root, synthetic]})

        with pytest.raises(UnsupportedTraceError) as excinfo:
            _fetch(lf, tmp_path)

        assert str(excinfo.value) == (
            "Session `s1` can't be graded: trace `t1` was recorded before this "
            "Langfuse server's v4 upgrade (synthetic root `t-t1`). "
            "Re-run the trial to grade it."
        )

    def test_repeated_observation_id_fails_the_session(self, tmp_path: Path) -> None:
        root = _obs("r1", "t1")
        child = _obs("c1", "t1", parent="r1")
        lf = FakeLangfuse(
            session=[root], traces={"t1": [root, child, child, root, child]}
        )

        with pytest.raises(UnsupportedTraceError) as excinfo:
            _fetch(lf, tmp_path)

        assert str(excinfo.value) == (
            "Session `s1` can't be graded: trace `t1` was recorded before this "
            "Langfuse server's v4 upgrade (3 duplicated observations). "
            "Re-run the trial to grade it."
        )

    def test_message_names_both_signs_when_both_are_present(
        self, tmp_path: Path
    ) -> None:
        root = _obs("r1", "t1")
        synthetic = _obs("t-t1", "t1")
        lf = FakeLangfuse(session=[root], traces={"t1": [root, synthetic, root]})

        with pytest.raises(UnsupportedTraceError) as excinfo:
            _fetch(lf, tmp_path)

        assert "(synthetic root `t-t1`, 1 duplicated observation)" in str(excinfo.value)

    def test_one_affected_trace_fails_the_whole_session(self, tmp_path: Path) -> None:
        clean = _obs("r1", "t1", start="2026-01-01T00:01:00Z")
        doubled = _obs("r2", "t2", start="2026-01-01T00:02:00Z")
        lf = FakeLangfuse(
            session=[clean, doubled],
            traces={"t1": [clean], "t2": [doubled, doubled]},
        )

        with pytest.raises(UnsupportedTraceError, match="trace `t2`"):
            _fetch(lf, tmp_path)

    def test_clean_trace_is_unaffected(self, tmp_path: Path) -> None:
        """One copy per id and no ``t-<traceId>`` id. Another trace's ``t-`` id is not one."""
        root = _obs("r1", "t1")
        child = _obs("c1", "t1", parent="r1")
        lookalike = _obs("t-t2", "t1", parent="r1")
        lf = FakeLangfuse(session=[root], traces={"t1": [root, child, lookalike]})

        (trace,) = _fetch(lf, tmp_path).traces

        assert {o.id for o in trace.observations} == {"r1", "c1", "t-t2"}
