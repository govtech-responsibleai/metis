"""The generic HTTP runner's poll_until tool (#524)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import pytest

from metis.core.trials import TrialConfig
from metis.engine.simulation.binding import load_target_binding
from metis.engine.simulation.runners import http as http_module
from metis.engine.simulation.runners.http import HttpRunner, HttpRunnerFactory
from metis.engine.simulation.runners.rules import ToolRefused

if TYPE_CHECKING:
    from pathlib import Path

SPEC_URL = "https://app.example/openapi.json"
_BINDING = f"schema_version: 1\nidentity: {{name: App}}\ntransport: http\nspec_url: {SPEC_URL}\n"
STATUS = "/api/v1/status"


class Target:
    """A fake app whose ``/status`` answers from a script, one reply per poll."""

    def __init__(self) -> None:
        self.script: list[httpx.Response] = []
        self.polls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/openapi.json":
            return httpx.Response(200, json={"servers": [{"url": "/api/v1"}]})
        if request.url.path == STATUS:
            self.polls += 1
            return self.script.pop(0)
        return httpx.Response(201, json={"sessionId": "s-1"})


class Clock:
    """A clock that only moves when the runner sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def _state(*states: str) -> list[httpx.Response]:
    return [httpx.Response(200, json={"job": {"state": s}}) for s in states]


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(http_module, "_now", fake)
    monkeypatch.setattr(http_module, "_sleep", fake.sleep)
    return fake


async def _ready(
    tmp_path: Path, *, extra: str = "", wait_ms: int = 300000
) -> tuple[HttpRunner, Target]:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "app.yaml").write_text(_BINDING + extra, encoding="utf-8")
    target = Target()
    factory = HttpRunnerFactory(
        load_target_binding(inputs, "app.yaml"), transport=httpx.MockTransport(target)
    )
    await factory.start()
    runner = await factory.create(tmp_path / "trial", tmp_path, tmp_path)
    await runner.setup(TrialConfig(persona="p", scenario="s", response_wait_ms=wait_ms))
    return runner, target


async def _open(runner: HttpRunner) -> None:
    runner.begin_action("Say ⟦hi⟧")
    await runner.http_request("POST", "/chat", json={"text": "{{1}}"})
    assert runner.open_submission is not None


async def _poll(runner: HttpRunner, **condition: Any) -> dict[str, Any]:
    return await runner.poll_until(
        STATUS.removeprefix("/api/v1"), "$.job.state", **condition
    )


@pytest.mark.asyncio
async def test_the_condition_holding_on_the_third_poll_settles_the_submission(
    tmp_path: Path, clock: Clock
) -> None:
    runner, target = await _ready(tmp_path)
    target.script = _state("queued", "running", "done")
    await _open(runner)

    result = await _poll(runner, not_in=["queued", "running"])

    assert result["condition"] == "holds"
    assert (result["value"], result["polls"], result["status"]) == ("done", 3, 200)
    assert clock.slept == [5.0, 5.0]
    assert runner.open_submission is None
    assert runner.unresolved is None
    assert result["response_entry"] in runner.results


@pytest.mark.asyncio
async def test_in_means_done_when_the_value_is_listed(
    tmp_path: Path, clock: Clock
) -> None:
    runner, target = await _ready(tmp_path)
    target.script = _state("running", "done")

    result = await _poll(runner, in_=["done", "failed"])

    assert (result["condition"], result["polls"]) == ("holds", 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", [{}, {"in_": ["a"], "not_in": ["b"]}])
async def test_exactly_one_of_in_and_not_in_is_required(
    tmp_path: Path, clock: Clock, condition: dict[str, Any]
) -> None:
    runner, target = await _ready(tmp_path)

    with pytest.raises(ToolRefused, match="exactly one of not_in"):
        await _poll(runner, **condition)

    assert target.polls == 0


@pytest.mark.asyncio
async def test_a_429_is_waited_out_and_the_poll_carries_on(
    tmp_path: Path, clock: Clock
) -> None:
    runner, target = await _ready(tmp_path)
    target.script = [
        httpx.Response(429, headers={"retry-after": "2"}),
        *_state("done"),
    ]

    result = await _poll(runner, in_=["done"])

    assert (result["condition"], result["polls"]) == ("holds", 1)
    assert clock.slept == [2.0]


@pytest.mark.asyncio
async def test_a_4xx_while_a_submission_is_open_makes_it_unresolved(
    tmp_path: Path, clock: Clock
) -> None:
    runner, target = await _ready(tmp_path)
    target.script = [httpx.Response(404, json={"error": "gone"})]
    await _open(runner)
    submission = runner.open_submission

    result = await _poll(runner, in_=["done"])

    assert result["status"] == 404
    assert runner.open_submission is None
    assert runner.unresolved is not None
    assert runner.unresolved.submission == submission
    assert runner.unresolved.response == result["response_entry"]


@pytest.mark.asyncio
async def test_a_405_is_the_runners_wrong_method_and_leaves_the_submission_open(
    tmp_path: Path, clock: Clock
) -> None:
    """Polling a POST-only path says nothing about the target's answer."""
    runner, target = await _ready(tmp_path)
    target.script = [httpx.Response(405, json={"detail": "Method Not Allowed"})]
    await _open(runner)
    submission = runner.open_submission

    result = await _poll(runner, in_=["done"])

    assert result["status"] == 405
    assert runner.open_submission == submission
    assert runner.unresolved is None


@pytest.mark.asyncio
async def test_a_5xx_or_a_4xx_with_nothing_open_stops_without_unresolved(
    tmp_path: Path, clock: Clock
) -> None:
    runner, target = await _ready(tmp_path)
    target.script = [httpx.Response(404), httpx.Response(503)]

    assert (await _poll(runner, in_=["done"]))["status"] == 404
    await _open(runner)
    assert (await _poll(runner, in_=["done"]))["status"] == 503

    assert runner.unresolved is None
    assert runner.open_submission is not None


@pytest.mark.asyncio
async def test_the_wait_limit_passing_leaves_the_submission_open(
    tmp_path: Path, clock: Clock
) -> None:
    runner, target = await _ready(tmp_path, wait_ms=12000)
    target.script = _state(*["running"] * 10)
    await _open(runner)

    result = await _poll(runner, not_in=["running"])

    assert "still open" in result["condition"]
    assert result["polls"] == 3  # at 0s, 5s and 10s; the next would pass 12s
    assert runner.open_submission is not None
    assert runner.unresolved is None


@pytest.mark.asyncio
async def test_the_wait_never_goes_beyond_the_trial_deadline(
    tmp_path: Path, clock: Clock
) -> None:
    runner, target = await _ready(tmp_path)
    runner._deadline = 7.0
    target.script = _state(*["running"] * 10)

    result = await _poll(runner, not_in=["running"])

    assert result["polls"] == 2


@pytest.mark.asyncio
async def test_a_missing_path_stops_with_the_pointer_error(
    tmp_path: Path, clock: Clock
) -> None:
    runner, target = await _ready(tmp_path)
    target.script = [httpx.Response(200, json={"other": 1})]

    result = await _poll(runner, in_=["done"])

    assert "is not in the body" in result["error"]
    assert target.polls == 1


@pytest.mark.asyncio
async def test_a_forbidden_path_is_refused_as_http_request_refuses_it(
    tmp_path: Path, clock: Clock
) -> None:
    runner, target = await _ready(tmp_path, extra='forbidden_calls: ["GET /status"]\n')
    refusal = "GET /status is forbidden by the target binding"

    with pytest.raises(ToolRefused, match=refusal):
        await _poll(runner, in_=["done"])
    with pytest.raises(ToolRefused, match=refusal):
        await runner.http_request("GET", "/status")

    assert target.polls == 0


@pytest.mark.asyncio
async def test_resume_poll_repeats_the_last_poll_only_while_a_submission_is_open(
    tmp_path: Path, clock: Clock
) -> None:
    runner, target = await _ready(tmp_path)
    assert await runner.resume_poll() is None  # nothing was ever polled

    target.script = _state("running", "running", "done")
    await _open(runner)
    first = await _poll(runner, not_in=["running"])
    assert first["polls"] == 3
    assert runner.open_submission is None
    assert await runner.resume_poll() is None  # settled, so nothing to repeat
    assert target.polls == 3

    await _open(runner)
    target.script = _state("done")
    resumed = await runner.resume_poll()

    assert resumed is not None
    assert (resumed["condition"], resumed["polls"]) == ("holds", 1)
    assert runner.open_submission is None
