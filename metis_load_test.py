"""Start N experiments at the same moment against a running METIS API, and say yes or no.

`make load-test LOAD_TEST_USERS=N` runs this module. It copies the input folder N times into the
project folder of the API, each copy with its own Specification id, so no two starts share an
experiment folder. Then N threads start behind one barrier. Every two seconds the module reads the
status of each experiment and prints one line for each. It ends when every experiment has ended,
or at the timeout.

The verdict is yes only when every start is accepted, every experiment ends `completed` with
phase `evaluating`, and the 95th percentile of the status route is under one second. Queue wait
and run time are reported for a person to judge, and they are not part of the verdict.

On Ctrl-C or a timeout, the module stops every experiment that it started and that is still
alive. The input copies and the experiment folders stay on disk.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from metis.core.console import console
from metis.core.project_layout import find_project_root

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

LOAD_TEST_DIR = Path("evaluations") / "load-test"
EXPERIMENTS_DIR = Path("evaluations") / "experiments"
P95_LIMIT_SECONDS = 1.0
"""The status route must answer 95 % of its requests faster than this. Each open page polls it
every two seconds, so this is what users feel."""
_ALIVE = frozenset({"queued", "running", "stopping"})
DEFAULT_USERS = 4
DEFAULT_URL = "http://127.0.0.1:8001"
DEFAULT_INPUT = Path("packages/engine/examples/http-agentic_eval_toyapp-1")
DEFAULT_TIMEOUT_SECONDS = 1800.0
POLL_SECONDS = 2.0
"""As often as an open experiment page polls the status route."""
REQUEST_TIMEOUT_SECONDS = 30.0
STOP_WAIT_SECONDS = 60.0
"""How long the clean-up waits for the stopped runs to end."""

# The top-level `id:` of a specification.yaml. Indented ids (of features, behaviours, and so on)
# do not match, because the line must start with `id:`.
_TOP_LEVEL_ID = re.compile(r"^id:[ \t]*(?P<value>.*?)[ \t]*(?:#.*)?$", re.MULTILINE)


@dataclass(frozen=True)
class InputCopy:
    """One copy of the input folder, for one user."""

    user: int
    path: Path
    input_dir: str
    """The copy's path relative to the project folder, as the simulate route takes it."""


def _top_level_id(text: str) -> re.Match[str]:
    matches = list(_TOP_LEVEL_ID.finditer(text))
    if len(matches) != 1:
        raise ValueError(
            f"specification.yaml must have one top-level id line, found {len(matches)}"
        )
    return matches[0]


def rewrite_specification_id(text: str, new_id: str) -> str:
    """Return `text` with its top-level `id` set to `new_id`, and every other line unchanged.

    The change is made in the text, not through a YAML load and dump, so the copy keeps the
    layout and the comments of its source.
    """
    match = _top_level_id(text)
    return f"{text[: match.start()]}id: {json.dumps(new_id)}{text[match.end() :]}"


def _read_id(text: str) -> str:
    value = _top_level_id(text).group("value")
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def make_input_copies(
    source: Path, project_dir: Path, users: int, *, stamp: str
) -> list[InputCopy]:
    """Copy `source` once for each user, under `evaluations/load-test/<stamp>/` of the project.

    Copy `i` is `<id>-load-<i>`, and its Specification id is the same text.

    :raises ValueError: `source` has no specification.yaml, or no single top-level id.
    :raises FileExistsError: the folder of `stamp` exists already.
    """
    spec_path = source / "specification.yaml"
    if not spec_path.is_file():
        raise ValueError(f"{source} has no specification.yaml")
    text = spec_path.read_text(encoding="utf-8")
    source_id = _read_id(text)

    relative_root = LOAD_TEST_DIR / stamp
    (project_dir / relative_root).mkdir(parents=True, exist_ok=False)
    copies: list[InputCopy] = []
    for user in range(1, users + 1):
        name = f"{source_id}-load-{user}"
        path = project_dir / relative_root / name
        shutil.copytree(source, path)
        (path / "specification.yaml").write_text(
            rewrite_specification_id(text, name), encoding="utf-8"
        )
        copies.append(
            InputCopy(user=user, path=path, input_dir=(relative_root / name).as_posix())
        )
    return copies


# --- percentiles, experiments, verdict, summary -----------------------------------------------


def percentile(values: Sequence[float], fraction: float) -> float | None:
    """Return the nearest-rank percentile of `values`, or None when there are none."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(1, math.ceil(fraction * len(ordered))) - 1]


def is_ended(status: str | None) -> bool:
    """A run has ended in every status but queued, running and stopping."""
    return status is not None and status not in _ALIVE


@dataclass(frozen=True)
class StartResult:
    """The answer to one start. `experiment_id` is set only for an accepted start."""

    user: int
    experiment_id: str | None
    http_status: int | None
    """None when the request got no HTTP answer."""
    code: str | None
    message: str | None
    accepted_at: float | None

    @property
    def accepted(self) -> bool:
        return self.experiment_id is not None


@dataclass
class Tracked:
    """What the polls have shown of one accepted experiment. Times are `time.monotonic()`."""

    user: int
    experiment_id: str
    accepted_at: float
    status: str | None = None
    phase: str | None = None
    queue_ahead: int | None = None
    total: int | None = None
    left_queue_at: float | None = None
    ended_at: float | None = None
    seen_queued: bool = False

    def observe(self, body: Mapping[str, object], now: float) -> None:
        """Take one answer of the status route, read at `now`."""
        status = body.get("status")
        phase = body.get("phase")
        queue_ahead = body.get("queue_ahead")
        total = body.get("total")
        self.status = status if isinstance(status, str) else None
        self.phase = phase if isinstance(phase, str) else None
        self.queue_ahead = queue_ahead if isinstance(queue_ahead, int) else None
        self.total = total if isinstance(total, int) else None
        if self.status == "queued":
            self.seen_queued = True
        elif self.status is not None and self.left_queue_at is None:
            # A run that no poll saw queued took a free slot at its start, so it waited for none.
            self.left_queue_at = now if self.seen_queued else self.accepted_at
        if self.ended_at is None and is_ended(self.status):
            self.ended_at = now

    @property
    def ended(self) -> bool:
        return self.ended_at is not None

    @property
    def queue_wait(self) -> float | None:
        """From the accepted start to the first poll that showed it out of the queue."""
        if self.left_queue_at is None:
            return None
        return self.left_queue_at - self.accepted_at

    @property
    def run_time(self) -> float | None:
        """From leaving the queue to the first poll that showed it ended."""
        if self.left_queue_at is None or self.ended_at is None:
            return None
        return self.ended_at - self.left_queue_at


@dataclass(frozen=True)
class Outcome:
    """Everything that a load test saw, for the verdict and the summary."""

    users: int
    url: str
    starts: list[StartResult]
    experiments: list[Tracked]
    latencies: list[float]
    """The seconds of each status request that got an answer."""
    status_errors: int
    """Status requests that failed: no answer, or an HTTP error."""
    timed_out: bool
    interrupted: bool
    elapsed_seconds: float
    copies_dir: Path
    project_dir: Path


def verdict_reasons(
    outcome: Outcome, *, p95_limit: float = P95_LIMIT_SECONDS
) -> list[str]:
    """Return why the API did not carry the load comfortably. An empty list means yes."""
    reasons: list[str] = []
    refused = [start for start in outcome.starts if not start.accepted]
    if refused:
        codes = ", ".join(sorted({start.code or "unknown" for start in refused}))
        reasons.append(f"{len(refused)} of {outcome.users} starts failed ({codes})")
    unfinished = [
        tracked
        for tracked in outcome.experiments
        if not (tracked.status == "completed" and tracked.phase == "evaluating")
    ]
    if unfinished:
        reasons.append(
            f"{len(unfinished)} of {len(outcome.experiments)} experiments did not end "
            "completed with phase evaluating"
        )
    p95 = percentile(outcome.latencies, 0.95)
    if p95 is None:
        if outcome.experiments:
            reasons.append("status route p95 unknown: no status request got an answer")
    elif p95 >= p95_limit:
        reasons.append(f"status route p95 {p95:.2f} s is not under {p95_limit:g} s")
    if outcome.status_errors:
        reasons.append(f"{outcome.status_errors} status requests failed")
    if outcome.timed_out:
        reasons.append("the timeout passed before every experiment ended")
    if outcome.interrupted:
        reasons.append("stopped with Ctrl-C")
    return reasons


def _seconds(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


def _spread(values: Sequence[float]) -> dict[str, float | None]:
    return {
        "p50": _seconds(percentile(values, 0.50)),
        "p95": _seconds(percentile(values, 0.95)),
        "max": _seconds(max(values, default=None)),
    }


def summarise(outcome: Outcome) -> dict[str, object]:
    """Return the JSON summary of a load test."""
    reasons = verdict_reasons(outcome)
    tracked_by_user = {tracked.user: tracked for tracked in outcome.experiments}
    per_user: list[dict[str, object]] = []
    for start in outcome.starts:
        tracked = tracked_by_user.get(start.user)
        per_user.append(
            {
                "user": start.user,
                "experiment_id": start.experiment_id,
                "status": tracked.status if tracked else None,
                "phase": tracked.phase if tracked else None,
                "queue_wait_seconds": _seconds(tracked.queue_wait) if tracked else None,
                "run_seconds": _seconds(tracked.run_time) if tracked else None,
            }
        )
    waits = [t.queue_wait for t in outcome.experiments if t.queue_wait is not None]
    runs = [t.run_time for t in outcome.experiments if t.run_time is not None]
    return {
        "verdict": "no" if reasons else "yes",
        "reasons": reasons,
        "users": outcome.users,
        "url": outcome.url,
        "elapsed_seconds": round(outcome.elapsed_seconds, 3),
        "timed_out": outcome.timed_out,
        "interrupted": outcome.interrupted,
        "starts": {
            "accepted": sum(start.accepted for start in outcome.starts),
            "failed": [
                {
                    "user": start.user,
                    "http_status": start.http_status,
                    "code": start.code,
                    "message": start.message,
                }
                for start in outcome.starts
                if not start.accepted
            ],
        },
        "final_statuses": dict(
            sorted(Counter(t.status or "unknown" for t in outcome.experiments).items())
        ),
        "status_latency_seconds": {
            "requests": len(outcome.latencies),
            "errors": outcome.status_errors,
            **_spread(outcome.latencies),
        },
        "queue_wait_seconds": _spread(waits),
        "run_seconds": _spread(runs),
        "per_user": per_user,
        "input_copies": str(outcome.copies_dir),
        "experiments": str(outcome.project_dir / EXPERIMENTS_DIR),
    }


def summary_hint(outcome: Outcome) -> str | None:
    """Return a hint when the API could not use the input copies, else None.

    The API takes `input_dir` relative to its own project folder. A refused input most often
    means that the API runs from another folder than this load test.
    """
    if not any(start.code == "invalid_inputs" for start in outcome.starts):
        return None
    return (
        f"The API refused the input copies in {outcome.project_dir}. If the API runs from "
        "another folder, set LOAD_TEST_PROJECT_DIR to its project folder."
    )


# --- settings and live lines ------------------------------------------------------------------


@dataclass(frozen=True)
class Config:
    """The settings of one load test."""

    users: int
    url: str
    input_dir: Path
    timeout: float
    """Seconds for the whole test."""
    project_dir: Path
    """The project folder of the API, where the input copies go."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="metis_load_test.py",
        description="Start N experiments at the same moment against a running METIS API.",
    )
    parser.add_argument("--users", type=int, default=DEFAULT_USERS)
    parser.add_argument("--url", default=DEFAULT_URL, help="The address of the API.")
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="The input folder to copy once for each user.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Seconds for the whole test. A timeout gives no.",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=None,
        help=(
            "The project folder of the API. Default: the nearest folder at or above the "
            "working directory that has a pyproject.toml, as metis-api finds it."
        ),
    )
    return parser


def parse_config(
    argv: Sequence[str] | None = None, *, cwd: Path | None = None
) -> Config:
    """Read the settings from `argv`. A value that is not valid exits with code 2."""
    parser = _parser()
    arguments = parser.parse_args(argv)
    if arguments.users < 1:
        parser.error("--users must be 1 or more")
    if arguments.timeout <= 0:
        parser.error("--timeout must be more than 0")
    url = arguments.url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        parser.error("--url must start with http:// or https://")
    project_dir: Path = (
        arguments.project_dir if arguments.project_dir else find_project_root(cwd)
    ).resolve()
    if not project_dir.is_dir():
        parser.error(f"the project folder {project_dir} does not exist")
    return Config(
        users=arguments.users,
        url=url,
        input_dir=arguments.input,
        timeout=arguments.timeout,
        project_dir=project_dir,
    )


def _clock(seconds: float) -> str:
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes}:{rest:02d}"


def _dash(value: object) -> str:
    return "-" if value is None else str(value)


def format_line(elapsed: float, tracked: Tracked) -> str:
    """One live line: status, phase, queue_ahead and total, as the jq loop of #222 shows."""
    return (
        f"   {_clock(elapsed)}  user {tracked.user:<3} {_dash(tracked.status):<11} "
        f"{_dash(tracked.phase):<10}  ahead {_dash(tracked.queue_ahead)}  "
        f"total {_dash(tracked.total)}"
    )


def format_header(
    elapsed: float, experiments: Sequence[Tracked], latencies: Sequence[float]
) -> str:
    """The line before each poll round: the counts and the status p95 so far."""
    counts = Counter(tracked.status for tracked in experiments)
    p95 = percentile(latencies, 0.95)
    return (
        f"-- {_clock(elapsed)}  running {counts['running'] + counts['stopping']}  "
        f"queued {counts['queued']}  ended {sum(t.ended for t in experiments)}  "
        f"status p95 {'-' if p95 is None else f'{p95:.2f}'} s"
    )


# --- the run against the API ------------------------------------------------------------------


class LoadTestError(RuntimeError):
    """The load test cannot start, for example because the API does not answer."""


def _request(
    method: str, url: str, payload: dict[str, object] | None = None
) -> tuple[int, dict[str, Any]]:
    """Send one JSON request and return the HTTP status and the body. An HTTP error is an answer.

    :raises OSError: the request got no HTTP answer.
    """
    request = urllib.request.Request(
        url,
        data=None if payload is None else json.dumps(payload).encode(),
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(
            request, timeout=REQUEST_TIMEOUT_SECONDS
        ) as response:  # noqa: S310 — the URL is a setting
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
    try:
        body = json.loads(raw) if raw else {}
    except ValueError:
        body = {}
    return status, body if isinstance(body, dict) else {}


def _start(url: str, copy: InputCopy, barrier: threading.Barrier) -> StartResult:
    """Wait for every other user at `barrier`, then start one simulate. It never raises."""
    try:
        barrier.wait()
        status, body = _request(
            "POST", f"{url}/api/v1/engine/simulate", {"input_dir": copy.input_dir}
        )
    except Exception as error:  # noqa: BLE001 — every failure of a start is a result
        return StartResult(copy.user, None, None, "request_failed", str(error), None)
    experiment_id = body.get("experiment_id")
    if status == 202 and isinstance(experiment_id, str):
        return StartResult(
            copy.user, experiment_id, status, None, None, time.monotonic()
        )
    code, message = body.get("code"), body.get("message")
    return StartResult(
        copy.user,
        None,
        status,
        code if isinstance(code, str) else "unexpected_answer",
        message if isinstance(message, str) else None,
        None,
    )


def _poll(url: str, tracked: Tracked) -> float | None:
    """Read the status of one experiment. Return the seconds it took, or None if it failed."""
    began = time.perf_counter()
    try:
        status, body = _request("GET", f"{url}/api/v1/engine/{tracked.experiment_id}")
    except OSError:
        return None
    seconds = time.perf_counter() - began
    if status != 200:
        return None
    tracked.observe(body, time.monotonic())
    return seconds


def _follow(
    url: str,
    experiments: list[Tracked],
    pool: ThreadPoolExecutor,
    *,
    began: float,
    deadline: float,
    latencies: list[float],
) -> tuple[int, bool]:
    """Poll every live experiment every two seconds until all have ended or `deadline` passes.

    Each round prints a header and one line for each experiment that was alive at its start,
    so an experiment that ends gets its last line once. Return the failed requests and
    whether the deadline passed.
    """
    errors = 0
    while True:
        alive = [tracked for tracked in experiments if not tracked.ended]
        if not alive:
            return errors, False
        if time.monotonic() >= deadline:
            return errors, True
        round_began = time.monotonic()
        for seconds in pool.map(lambda tracked: _poll(url, tracked), alive):
            if seconds is None:
                errors += 1
            else:
                latencies.append(seconds)
        elapsed = time.monotonic() - began
        console.out(format_header(elapsed, experiments, latencies), highlight=False)
        for tracked in alive:
            console.out(format_line(elapsed, tracked), highlight=False)
        time.sleep(max(0.0, round_began + POLL_SECONDS - time.monotonic()))


def _stop_alive(url: str, experiments: list[Tracked], pool: ThreadPoolExecutor) -> None:
    """Stop every experiment that has not ended, and wait until they end.

    A stop removes a queued run from the queue. 409 no_run means that the run ended already.
    """
    alive = [tracked for tracked in experiments if not tracked.ended]
    if not alive:
        return
    console.out(
        f"Stopping {len(alive)} experiments that are still alive.", highlight=False
    )
    for tracked in alive:
        try:
            _request("POST", f"{url}/api/v1/engine/{tracked.experiment_id}/stop")
        except OSError as error:
            console.out(
                f"Could not stop {tracked.experiment_id}: {error}", highlight=False
            )
    deadline = time.monotonic() + STOP_WAIT_SECONDS
    while alive and time.monotonic() < deadline:
        time.sleep(POLL_SECONDS)
        list(pool.map(lambda tracked: _poll(url, tracked), alive))
        alive = [tracked for tracked in alive if not tracked.ended]
    for tracked in alive:
        console.out(
            f"Still alive after {STOP_WAIT_SECONDS:g} s: {tracked.experiment_id}. "
            f"Stop it with POST {url}/api/v1/engine/{tracked.experiment_id}/stop.",
            highlight=False,
        )


def _ignore_interrupts() -> Any:
    """Ignore Ctrl-C and return the previous handler, so the clean-up is not cut short.

    `make` and `uv run` pass Ctrl-C on a second time.
    """
    if threading.current_thread() is not threading.main_thread():
        return None
    return signal.signal(signal.SIGINT, signal.SIG_IGN)


def run(config: Config) -> Outcome:
    """Start `config.users` experiments at the same moment and follow them to the end.

    :raises LoadTestError: the API does not answer, or the input folder cannot be copied.
    """
    try:
        _request("GET", f"{config.url}/health")
    except OSError as error:
        raise LoadTestError(
            f"The API does not answer at {config.url} ({error}). Start it with make run-api."
        ) from None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        copies = make_input_copies(
            config.input_dir.resolve(), config.project_dir, config.users, stamp=stamp
        )
    except (OSError, ValueError) as error:
        raise LoadTestError(f"Cannot copy the input folder: {error}") from None
    copies_dir = config.project_dir / LOAD_TEST_DIR / stamp
    console.out(f"Input copies: {copies_dir}", highlight=False)
    console.out(
        f"Starting {config.users} experiments at {config.url}.", highlight=False
    )

    latencies: list[float] = []
    experiments: list[Tracked] = []
    errors, timed_out, interrupted = 0, False, False
    began = time.monotonic()
    pool = ThreadPoolExecutor(max_workers=config.users)
    barrier = threading.Barrier(config.users)
    futures = [pool.submit(_start, config.url, copy, barrier) for copy in copies]
    try:
        starts = [future.result() for future in futures]
        experiments = _tracked(starts)
        errors, timed_out = _follow(
            config.url,
            experiments,
            pool,
            began=began,
            deadline=began + config.timeout,
            latencies=latencies,
        )
    except KeyboardInterrupt:
        interrupted = True
    previous = _ignore_interrupts()
    try:
        # Ctrl-C can come while starts are in flight. Wait for each of them, so a start that
        # the API accepts after the Ctrl-C is stopped too.
        starts = [future.result() for future in futures]
        if not experiments:
            experiments = _tracked(starts)
        elapsed = time.monotonic() - began
        if interrupted or timed_out:
            _stop_alive(config.url, experiments, pool)
    finally:
        pool.shutdown(wait=True)
        if previous is not None:
            signal.signal(signal.SIGINT, previous)
    return Outcome(
        users=config.users,
        url=config.url,
        starts=starts,
        experiments=experiments,
        latencies=latencies,
        status_errors=errors,
        timed_out=timed_out,
        interrupted=interrupted,
        elapsed_seconds=elapsed,
        copies_dir=copies_dir,
        project_dir=config.project_dir,
    )


def _tracked(starts: list[StartResult]) -> list[Tracked]:
    tracked: list[Tracked] = []
    for start in starts:
        if start.experiment_id is not None and start.accepted_at is not None:
            console.out(f"user {start.user}: {start.experiment_id}", highlight=False)
            tracked.append(Tracked(start.user, start.experiment_id, start.accepted_at))
        else:
            console.out(
                f"user {start.user}: start failed, {start.http_status} {start.code}: "
                f"{start.message}",
                highlight=False,
            )
    return tracked


def main(argv: Sequence[str] | None = None) -> int:
    """Run the load test. Return 0 when the verdict is yes, else 1."""
    config = parse_config(argv)
    try:
        outcome = run(config)
    except LoadTestError as error:
        console.out(f"Error: {error}", highlight=False)
        return 1
    summary = summarise(outcome)
    reasons = verdict_reasons(outcome)
    console.out("", highlight=False)
    if reasons:
        console.out(f"Verdict: no. {'; '.join(reasons)}.", highlight=False)
    else:
        console.out(
            f"Verdict: yes. The API carried {config.users} users comfortably.",
            highlight=False,
        )
    hint = summary_hint(outcome)
    if hint:
        console.out(hint, highlight=False)
    console.out(f"Input copies: {summary['input_copies']}", highlight=False)
    console.out(f"Experiments: {summary['experiments']}", highlight=False)
    console.out(json.dumps(summary, indent=2, sort_keys=True), highlight=False)
    return 1 if reasons else 0


if __name__ == "__main__":
    sys.exit(main())
