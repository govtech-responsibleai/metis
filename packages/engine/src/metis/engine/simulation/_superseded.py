"""Where an earlier attempt's log file goes when a trial is retried."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def superseded_path(path: Path, *, now: datetime | None = None) -> Path:
    """The unused name ``<stem>-superseded-<UTC timestamp><suffix>`` beside ``path``.

    A second move within the same second gets ``-2``, then ``-3``, so no earlier file
    is overwritten.

    :param now: Timestamp for the name. Defaults to the current UTC time; injected by
        tests for a deterministic name.
    """
    stamp = (now or datetime.now(tz=UTC)).strftime("%Y%m%dT%H%M%SZ")
    stem = f"{path.stem}-superseded-{stamp}"
    dest = path.with_name(stem + path.suffix)
    suffix = 2
    while dest.exists():
        dest = path.with_name(f"{stem}-{suffix}{path.suffix}")
        suffix += 1
    return dest
