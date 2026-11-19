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

import json
import math
import re
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

LOAD_TEST_DIR = Path("evaluations") / "load-test"
EXPERIMENTS_DIR = Path("evaluations") / "experiments"
P95_LIMIT_SECONDS = 1.0
"""The status route must answer 95 % of its requests faster than this. Each open page polls it
every two seconds, so this is what users feel."""
_ALIVE = frozenset({"queued", "running", "stopping"})

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
    """Status requests that got no answer."""
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
        reasons.append(f"{outcome.status_errors} status requests got no answer")
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
