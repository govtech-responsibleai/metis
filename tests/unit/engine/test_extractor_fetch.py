"""fetch_session: one Langfuse session as the GradingInput its grader runs share.

Every test fakes ``async_api.observations_v_2.get_many``, so nothing touches the network. The mock answers
by filter column, so a fetch that wrongly reused the session-filtered list as a trace's
observations (issue #435) gets different, smaller data and fails.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from metis.core import Artifact
from metis.engine.extractor.langfuse import (
    NO_TRACES,
    TRACES_CHANGING,
    OpenObservation,
    TracesNotReadyError,
    TraceWaitSettings,
    UnsupportedTraceError,
    _fetch_trace,
    _page_through_observations,
    fetch_session,
    wait_for_settled_traces,
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
    end: str | None = "2026-01-01T00:00:01Z",
    updated: str = "2026-01-01T00:00:02Z",
    obs_type: str = "AGENT",
    metadata: object = None,
) -> dict[str, Any]:
    """A raw camelCase Observations API v2 row, closed unless ``end`` is ``None``."""
    return {
        "id": obs_id,
        "traceId": trace_id,
        "sessionId": session_id,
        "name": "chat-turn" if parent is None else "child",
        "type": obs_type,
        "input": "a question",
        "output": output,
        "metadata": metadata,
        "startTime": start,
        "endTime": end,
        "updatedAt": updated,
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
        self.async_api = SimpleNamespace(
            observations_v_2=SimpleNamespace(get_many=self._get_many)
        )

    async def _get_many(self, **kwargs: Any) -> SimpleNamespace:
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


STORED = datetime(2026, 1, 1, 0, 0, 2, tzinfo=UTC)
"""The default ``updatedAt`` of ``_obs``."""


class FakeClock:
    """A clock that moves only when the code sleeps. ``on_sleep`` lets Langfuse change.

    ``utc_start`` is the wall-clock time at ``now == 0``. The default is a day after
    ``STORED``, so default rows are old and settle on the first check.
    """

    def __init__(
        self, on_sleep: Any = None, *, utc_start: datetime = STORED + timedelta(days=1)
    ) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []
        self.on_sleep = on_sleep
        self.utc_start = utc_start

    def clock(self) -> float:
        return self.now

    def utc_now(self) -> datetime:
        return self.utc_start + timedelta(seconds=self.now)

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
        if self.on_sleep:
            self.on_sleep(len(self.sleeps))


def _stamp(clock: FakeClock) -> str:
    """The ``updatedAt`` of a row that Langfuse stores at the clock's current time."""
    return clock.utc_now().isoformat().replace("+00:00", "Z")


async def _fetch(
    lf: FakeLangfuse,
    tmp_path: Path,
    *,
    clock: FakeClock | None = None,
    settings: TraceWaitSettings = TraceWaitSettings(timeout_seconds=90),
    **kwargs: Any,
):
    clock = clock or FakeClock()
    return await fetch_session(
        "s1",
        lf,  # type: ignore[arg-type]
        experiment_root=tmp_path,
        settings=settings,
        clock=clock.clock,
        sleep=clock.sleep,
        utc_now=clock.utc_now,
        **kwargs,
    )


def _async_mock_client() -> MagicMock:
    """A client whose ``async_api.observations_v_2.get_many`` is an ``AsyncMock``."""
    lf = MagicMock()
    lf.async_api.observations_v_2.get_many = AsyncMock()
    return lf


class TestPaging:
    @pytest.mark.asyncio
    async def test_follows_every_cursor_page(self) -> None:
        lf = _async_mock_client()
        lf.async_api.observations_v_2.get_many.side_effect = [
            _page([_obs("o1", "t1")], cursor="next"),
            _page([_obs("o2", "t1", parent="o1")]),
        ]
        observations = await _page_through_observations(lf, "traceId", "t1")
        assert [o.id for o in observations] == ["o1", "o2"]
        assert lf.async_api.observations_v_2.get_many.call_count == 2
        second = lf.async_api.observations_v_2.get_many.call_args_list[1].kwargs
        assert second["cursor"] == "next"

    @pytest.mark.asyncio
    async def test_request_shape(self) -> None:
        lf = _async_mock_client()
        lf.async_api.observations_v_2.get_many.return_value = _page([])
        await _page_through_observations(lf, "sessionId", "s1")
        kwargs = lf.async_api.observations_v_2.get_many.call_args.kwargs
        assert kwargs["fields"] == "core,basic,time,io,metadata"
        assert kwargs["limit"] == 1000
        assert _filter(kwargs) == ("sessionId", "s1")
        assert kwargs["expand_metadata"] is None

    @pytest.mark.asyncio
    async def test_never_sends_parse_io_as_json(self) -> None:
        """The v2 endpoint rejects it with HTTP 400; the key must not be sent at all."""
        lf = _async_mock_client()
        lf.async_api.observations_v_2.get_many.return_value = _page([])
        await _page_through_observations(lf, "traceId", "t1")
        assert (
            "parse_io_as_json"
            not in lf.async_api.observations_v_2.get_many.call_args.kwargs
        )


class TestNoRequestOptions:
    """Passing ``request_options`` makes the SDK send a JSON body ``{}`` with every GET, and
    a proxy in front of Langfuse rejects a GET with a body with HTTP 400 (issue #122)."""

    @pytest.mark.asyncio
    async def test_get_many_is_never_called_with_request_options(
        self, tmp_path: Path
    ) -> None:
        cut = _obs("r1", "t1", metadata={"summary": "x" * 200})
        full = _obs("r1", "t1", metadata={"summary": LONG})
        lf = FakeLangfuse(session=[cut], traces={"t1": [cut]}, expanded={"t1": [full]})

        await _fetch(lf, tmp_path)

        assert len(lf.calls) == 3  # session, trace, expanded refetch
        assert all("request_options" not in call for call in lf.calls)

    @pytest.mark.asyncio
    async def test_the_request_is_a_get_with_no_body(self) -> None:
        import httpx

        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json=_ok_body([]))

        await _page_through_observations(_real_client(handler), "traceId", "t1")

        (request,) = requests
        assert request.method == "GET"
        assert request.content == b""


class TestStatusRetriesWithAFakeClient:
    """``_get_page`` retries a retriable status itself; the SDK is never asked to."""

    @staticmethod
    def _failing_then_ok(lf: FakeLangfuse, status: int, failures: int) -> None:
        from langfuse.api.core.api_error import ApiError

        answer = lf._get_many
        remaining = [failures]

        async def _get_many(**kwargs: Any) -> SimpleNamespace:
            if remaining[0]:
                remaining[0] -= 1
                lf.calls.append(kwargs)
                raise ApiError(status_code=status, body={"message": "unavailable"})
            return await answer(**kwargs)

        lf.async_api.observations_v_2.get_many = _get_many

    @pytest.mark.asyncio
    async def test_a_503_is_retried_and_the_fetch_succeeds(
        self, tmp_path: Path, instant_retries: list[float]
    ) -> None:
        root = _obs("r1", "t1")
        lf = FakeLangfuse(session=[root], traces={"t1": [root]})
        self._failing_then_ok(lf, 503, failures=2)

        (trace,) = (await _fetch(lf, tmp_path)).traces

        assert trace.id == "t1"
        assert len(instant_retries) == 2

    @pytest.mark.asyncio
    async def test_a_401_is_raised_at_once(
        self, tmp_path: Path, instant_retries: list[float]
    ) -> None:
        from langfuse.api.core.api_error import ApiError

        root = _obs("r1", "t1")
        lf = FakeLangfuse(session=[root], traces={"t1": [root]})
        self._failing_then_ok(lf, 401, failures=1)

        with pytest.raises(ApiError) as excinfo:
            await _fetch(lf, tmp_path)

        assert excinfo.value.status_code == 401
        assert len(lf.calls) == 1
        assert instant_retries == []


class TestTwoStepFetch:
    @pytest.mark.asyncio
    async def test_trace_observations_come_from_the_trace_filter(
        self, tmp_path: Path
    ) -> None:
        """The session filter drops agent-run spans and session-less rows."""
        root = _obs("root", "t1")
        agent = _obs("agent", "t1", session_id="agno-uuid", parent="root")
        no_session = _obs("gen", "t1", session_id=None, parent="agent")
        lf = FakeLangfuse(session=[root], traces={"t1": [root, agent, no_session]})

        grading_input = await _fetch(lf, tmp_path)

        (trace,) = grading_input.traces
        assert {o.id for o in trace.observations} == {"root", "agent", "gen"}
        assert trace.root.id == "root"

    @pytest.mark.asyncio
    async def test_one_trace_call_per_trace(self, tmp_path: Path) -> None:
        lf = FakeLangfuse(
            session=[_obs("r1", "t1"), _obs("c1", "t1", parent="r1"), _obs("r2", "t2")],
            traces={"t1": [_obs("r1", "t1")], "t2": [_obs("r2", "t2")]},
        )
        await _fetch(lf, tmp_path)
        assert sorted(_filter(c)[1] for c in lf.trace_calls()) == ["t1", "t2"]

    @pytest.mark.asyncio
    async def test_traces_are_ordered_by_root_start_time(self, tmp_path: Path) -> None:
        late = _obs("r2", "t2", start="2026-01-01T00:05:00Z")
        early = _obs("r1", "t1", start="2026-01-01T00:01:00Z")
        lf = FakeLangfuse(session=[late, early], traces={"t1": [early], "t2": [late]})
        assert [t.id for t in (await _fetch(lf, tmp_path)).traces] == ["t1", "t2"]

    @pytest.mark.asyncio
    async def test_trace_without_output_is_kept(self, tmp_path: Path) -> None:
        """A crashed exchange is part of what the target did; graders decide what to skip."""
        crashed = _obs("r1", "t1", output=None)
        lf = FakeLangfuse(session=[crashed], traces={"t1": [crashed]})
        (trace,) = (await _fetch(lf, tmp_path)).traces
        assert trace.root.output is None

    @pytest.mark.asyncio
    async def test_every_trace_is_kept_however_many(self, tmp_path: Path) -> None:
        """No cap on traces per session: the old fetch's limit=50 is gone."""
        rows = [
            _obs(f"r{i}", f"t{i}", start=f"2026-01-01T00:{i:02d}:00Z")
            for i in range(60)
        ]
        lf = FakeLangfuse(session=rows, traces={r["traceId"]: [r] for r in rows})
        assert len((await _fetch(lf, tmp_path)).traces) == 60


class TestWaitForSettledTraces:
    """A trial is graded only when Langfuse has stored nothing new for the quiet window."""

    @pytest.mark.asyncio
    async def test_fresh_traces_wait_30_seconds_by_default(
        self, tmp_path: Path
    ) -> None:
        root = _obs("r1", "t1")
        lf = FakeLangfuse(session=[root], traces={"t1": [root]})
        clock = FakeClock(utc_start=STORED)

        await _fetch(
            lf, tmp_path, clock=clock, settings=TraceWaitSettings(timeout_seconds=90)
        )

        assert clock.sleeps == [30]

    @pytest.mark.asyncio
    async def test_old_traces_are_graded_at_once(self, tmp_path: Path) -> None:
        root = _obs("r1", "t1")
        lf = FakeLangfuse(session=[root], traces={"t1": [root]})
        clock = FakeClock()

        (trace,) = (await _fetch(lf, tmp_path, clock=clock)).traces

        assert trace.id == "t1"
        assert clock.sleeps == []

    @pytest.mark.asyncio
    async def test_new_data_during_the_wait_restarts_it(self, tmp_path: Path) -> None:
        """A trace that Langfuse stores during the wait is graded with the rest."""
        first = _obs("r1", "t1", start="2026-01-01T00:01:00Z")
        lf = FakeLangfuse(session=[first], traces={"t1": [first]})
        clock = FakeClock(utc_start=STORED)

        def ingest(sleeps: int) -> None:
            if sleeps == 1:
                late = _obs(
                    "r2", "t2", start="2026-01-01T00:02:00Z", updated=_stamp(clock)
                )
                lf.session = [first, late]
                lf.traces["t2"] = [late]

        clock.on_sleep = ingest
        grading_input = await _fetch(
            lf,
            tmp_path,
            clock=clock,
            settings=TraceWaitSettings(timeout_seconds=90, quiet_seconds=10),
        )

        assert [t.id for t in grading_input.traces] == ["t1", "t2"]
        assert clock.sleeps == [10, 10]

    @pytest.mark.asyncio
    async def test_traces_that_keep_changing_fail_the_trial(
        self, tmp_path: Path
    ) -> None:
        lf = FakeLangfuse(session=[_obs("r1", "t1")], traces={"t1": [_obs("r1", "t1")]})
        clock = FakeClock(utc_start=STORED)

        def keep_changing(_sleeps: int) -> None:
            lf.traces["t1"] = [_obs("r1", "t1", updated=_stamp(clock))]

        clock.on_sleep = keep_changing
        with pytest.raises(TracesNotReadyError) as excinfo:
            await _fetch(lf, tmp_path, clock=clock)

        assert (
            str(excinfo.value) == TRACES_CHANGING == "traces still changing in Langfuse"
        )
        assert clock.now == 90

    @pytest.mark.asyncio
    async def test_no_traces_fails_the_trial(self, tmp_path: Path) -> None:
        lf = FakeLangfuse(session=[], traces={})

        with pytest.raises(TracesNotReadyError) as excinfo:
            await _fetch(lf, tmp_path)

        assert str(excinfo.value) == NO_TRACES == "no traces in Langfuse"

    @pytest.mark.asyncio
    async def test_an_empty_trace_is_never_graded(self, tmp_path: Path) -> None:
        """Found by the session filter but empty by trace id: Langfuse is still ingesting."""
        good = _obs("r1", "t1")
        lf = FakeLangfuse(session=[good, _obs("r2", "t2")], traces={"t1": [good]})

        with pytest.raises(TracesNotReadyError, match=TRACES_CHANGING):
            await _fetch(lf, tmp_path, settings=TraceWaitSettings(timeout_seconds=30))

    @pytest.mark.asyncio
    async def test_an_observation_that_never_ended_is_graded_and_listed(self) -> None:
        """A crashed target never ends its span. Waiting cannot change what is stored."""
        root = _obs("r1", "t1")
        hung = _obs("c1", "t1", parent="r1", end=None)
        lf = FakeLangfuse(session=[root], traces={"t1": [root, hung]})
        clock = FakeClock()

        wait = await wait_for_settled_traces(
            lf,  # type: ignore[arg-type]
            "s1",
            settings=TraceWaitSettings(timeout_seconds=90),
            clock=clock.clock,
            sleep=clock.sleep,
            utc_now=clock.utc_now,
        )

        assert wait.status == "settled"
        assert wait.open_observations == (OpenObservation("t1", "c1", "child"),)


@pytest.mark.parametrize(
    ("environ", "quiet"), [({}, 30.0), ({"LANGFUSE_METIS_QUIET_SECONDS": "60"}, 60.0)]
)
def test_the_quiet_window_comes_from_the_environment(
    environ: dict[str, str], quiet: float
) -> None:
    settings = TraceWaitSettings.from_env(90, environ)

    assert settings == TraceWaitSettings(timeout_seconds=90, quiet_seconds=quiet)


class TestMetadataExpansion:
    @pytest.mark.asyncio
    async def test_short_metadata_is_fetched_once(self) -> None:
        root = _obs("r1", "t1", metadata={"mode": "direct"})
        lf = FakeLangfuse(session=[root], traces={"t1": [root]})
        await _fetch_trace(lf, "t1")  # type: ignore[arg-type]
        assert len(lf.trace_calls()) == 1

    @pytest.mark.asyncio
    async def test_possibly_truncated_metadata_is_refetched_with_every_key_expanded(
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

        observations = await _fetch_trace(lf, "t1")  # type: ignore[arg-type]

        calls = lf.trace_calls()
        assert len(calls) == 2
        assert calls[1]["expand_metadata"] == "mode,plan,summary"
        root = next(o for o in observations if o.id == "r1")
        assert root.metadata == {"mode": "direct", "summary": LONG}

    @pytest.mark.asyncio
    async def test_non_string_metadata_never_triggers_a_refetch(self) -> None:
        root = _obs("r1", "t1", metadata={"routed_to_agents": ["a"] * 100, "n": 5})
        lf = FakeLangfuse(session=[root], traces={"t1": [root]})
        await _fetch_trace(lf, "t1")  # type: ignore[arg-type]
        assert len(lf.trace_calls()) == 1


class TestArtifacts:
    @pytest.mark.asyncio
    async def test_paths_are_resolved_against_the_experiment_root(
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

        grading_input = await _fetch(lf, tmp_path, artifacts=artifacts)

        deck, gone = grading_input.artifacts
        assert deck.path == str(tmp_path / "runs/a/deck.pptx")
        assert deck.at_simulated_turn == 2
        assert gone.path is None

    @pytest.mark.asyncio
    async def test_every_artifact_is_attached_regardless_of_turn(
        self, tmp_path: Path
    ) -> None:
        """Artifacts cannot be tied to traces reliably (#428 known gap), so none are filtered."""
        root = _obs("r1", "t1")
        lf = FakeLangfuse(session=[root], traces={"t1": [root]})
        artifacts = [
            Artifact(name=f"f{i}", path=f"f{i}", at_simulated_turn=i, state="received")
            for i in range(5)
        ]
        assert len((await _fetch(lf, tmp_path, artifacts=artifacts)).artifacts) == 5

    @pytest.mark.asyncio
    async def test_input_artifacts_are_not_mutated(self, tmp_path: Path) -> None:
        root = _obs("r1", "t1")
        lf = FakeLangfuse(session=[root], traces={"t1": [root]})
        original = Artifact(name="a", path="rel/a", state="received")
        await _fetch(lf, tmp_path, artifacts=[original])
        assert original.path == "rel/a"


class TestTracesFromBeforeTheV4Upgrade:
    """Such traces come back with every observation doubled and a ``t-<traceId>``
    root, and the stored set changes with page size, so they are rejected, not repaired."""

    @pytest.mark.asyncio
    async def test_synthetic_root_fails_the_session(self, tmp_path: Path) -> None:
        root = _obs("r1", "t1")
        synthetic = _obs("t-t1", "t1")
        lf = FakeLangfuse(session=[root], traces={"t1": [root, synthetic]})

        with pytest.raises(UnsupportedTraceError) as excinfo:
            await _fetch(lf, tmp_path)

        assert str(excinfo.value) == (
            "Session `s1` can't be graded: trace `t1` was recorded before this "
            "Langfuse server's v4 upgrade (synthetic root `t-t1`). "
            "Re-run the trial to grade it."
        )

    @pytest.mark.asyncio
    async def test_repeated_observation_id_fails_the_session(
        self, tmp_path: Path
    ) -> None:
        root = _obs("r1", "t1")
        child = _obs("c1", "t1", parent="r1")
        lf = FakeLangfuse(
            session=[root], traces={"t1": [root, child, child, root, child]}
        )

        with pytest.raises(UnsupportedTraceError) as excinfo:
            await _fetch(lf, tmp_path)

        assert str(excinfo.value) == (
            "Session `s1` can't be graded: trace `t1` was recorded before this "
            "Langfuse server's v4 upgrade (3 duplicated observations). "
            "Re-run the trial to grade it."
        )

    @pytest.mark.asyncio
    async def test_message_names_both_signs_when_both_are_present(
        self, tmp_path: Path
    ) -> None:
        root = _obs("r1", "t1")
        synthetic = _obs("t-t1", "t1")
        lf = FakeLangfuse(session=[root], traces={"t1": [root, synthetic, root]})

        with pytest.raises(UnsupportedTraceError) as excinfo:
            await _fetch(lf, tmp_path)

        assert "(synthetic root `t-t1`, 1 duplicated observation)" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_one_affected_trace_fails_the_whole_session(
        self, tmp_path: Path
    ) -> None:
        clean = _obs("r1", "t1", start="2026-01-01T00:01:00Z")
        doubled = _obs("r2", "t2", start="2026-01-01T00:02:00Z")
        lf = FakeLangfuse(
            session=[clean, doubled],
            traces={"t1": [clean], "t2": [doubled, doubled]},
        )

        with pytest.raises(UnsupportedTraceError, match="trace `t2`"):
            await _fetch(lf, tmp_path)

    @pytest.mark.asyncio
    async def test_clean_trace_is_unaffected(self, tmp_path: Path) -> None:
        """One copy per id and no ``t-<traceId>`` id. Another trace's ``t-`` id is not one."""
        root = _obs("r1", "t1")
        child = _obs("c1", "t1", parent="r1")
        lookalike = _obs("t-t2", "t1", parent="r1")
        lf = FakeLangfuse(session=[root], traces={"t1": [root, child, lookalike]})

        (trace,) = (await _fetch(lf, tmp_path)).traces

        assert {o.id for o in trace.observations} == {"r1", "c1", "t-t2"}


# --- retries: the real SDK client over a fake transport -------------------------------------


def _real_client(handler: Any) -> Any:
    """A real ``AsyncFernLangfuse`` whose HTTP layer is ``handler``, so the SDK's own retry
    code runs. Returns an object shaped like the ``Langfuse`` client the extractor takes."""
    import httpx
    from langfuse.api.client import AsyncFernLangfuse

    api = AsyncFernLangfuse(
        base_url="http://langfuse.test",
        username="pk",
        password="sk",
        httpx_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return SimpleNamespace(async_api=api)


def _ok_body(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"data": rows, "meta": {"cursor": None}}


@pytest.fixture
def instant_retries(monkeypatch: Any) -> list[float]:
    """Record every retry wait without sleeping."""
    waits: list[float] = []

    async def _sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr("asyncio.sleep", _sleep)
    return waits


class TestRetries:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [429, 408, 500, 503])
    async def test_a_retriable_status_is_retried_and_the_page_arrives(
        self, status: int, instant_retries: list[float]
    ) -> None:
        import httpx

        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            if len(calls) < 3:
                return httpx.Response(status, json={"message": "slow down"})
            return httpx.Response(200, json=_ok_body([_obs("o1", "t1")]))

        observations = await _page_through_observations(
            _real_client(handler), "traceId", "t1"
        )

        assert [o.id for o in observations] == ["o1"]
        assert len(calls) == 3
        assert len(instant_retries) == 2  # waited before each retry

    @pytest.mark.asyncio
    async def test_a_status_that_keeps_failing_is_raised_after_the_retries(
        self, instant_retries: list[float]
    ) -> None:
        import httpx
        from langfuse.api.core.api_error import ApiError

        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(429, json={"message": "slow down"})

        with pytest.raises(ApiError) as excinfo:
            await _page_through_observations(_real_client(handler), "traceId", "t1")

        assert excinfo.value.status_code == 429
        assert len(calls) == 1 + 3  # the first try and three retries, then it gives up

    @pytest.mark.asyncio
    async def test_a_status_that_is_not_retriable_fails_at_once(
        self, instant_retries: list[float]
    ) -> None:
        import httpx
        from langfuse.api.core.api_error import ApiError

        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(401, json={"message": "bad key"})

        with pytest.raises(ApiError):
            await _page_through_observations(_real_client(handler), "traceId", "t1")

        assert len(calls) == 1
        assert instant_retries == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("error", ["timeout", "connect"])
    async def test_a_timeout_or_connection_error_is_retried(
        self, error: str, instant_retries: list[float]
    ) -> None:
        import httpx

        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            if len(calls) < 3:
                if error == "timeout":
                    raise httpx.ReadTimeout("read timed out", request=request)
                raise httpx.ConnectError("refused", request=request)
            return httpx.Response(200, json=_ok_body([_obs("o1", "t1")]))

        observations = await _page_through_observations(
            _real_client(handler), "traceId", "t1"
        )

        assert [o.id for o in observations] == ["o1"]
        assert len(calls) == 3
        assert len(instant_retries) == 2

    @pytest.mark.asyncio
    async def test_a_timeout_that_keeps_happening_is_raised_after_the_retries(
        self, instant_retries: list[float]
    ) -> None:
        import httpx

        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            raise httpx.ReadTimeout("read timed out", request=request)

        with pytest.raises(httpx.ReadTimeout):
            await _page_through_observations(_real_client(handler), "traceId", "t1")

        assert len(calls) == 1 + 3

    @pytest.mark.asyncio
    async def test_each_page_is_retried_on_its_own(
        self, instant_retries: list[float]
    ) -> None:
        """A failure on page two must not refetch page one."""
        import httpx

        pages: list[str | None] = []

        def handler(request: httpx.Request) -> httpx.Response:
            cursor = request.url.params.get("cursor")
            pages.append(cursor)
            if cursor is None:
                body = {"data": [_obs("o1", "t1")], "meta": {"cursor": "next"}}
                return httpx.Response(200, json=body)
            if pages.count("next") == 1:
                return httpx.Response(429, json={"message": "slow down"})
            return httpx.Response(200, json=_ok_body([_obs("o2", "t1", parent="o1")]))

        observations = await _page_through_observations(
            _real_client(handler), "traceId", "t1"
        )

        assert [o.id for o in observations] == ["o1", "o2"]
        assert pages == [None, "next", "next"]  # page one fetched once
