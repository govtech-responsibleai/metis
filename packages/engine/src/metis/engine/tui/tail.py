"""Ring buffer for the TUI log tail panel."""

from __future__ import annotations

import itertools
import logging
from collections import deque
from typing import NamedTuple

from rich.text import Text

_seq_counter = itertools.count()


class TailEntry(NamedTuple):
    seq: int
    content: Text | str


class TailBuffer:
    """Fixed-capacity ring buffer that filters log lines by level."""

    def __init__(self, max_lines: int = 15, min_level: int = logging.WARNING) -> None:
        self._max_lines = max_lines
        self._min_level = min_level
        self._entries: deque[TailEntry] = deque(maxlen=max_lines)

    def append(self, line: Text | str, level: int = logging.INFO) -> None:
        if level >= self._min_level:
            self._entries.append(TailEntry(seq=next(_seq_counter), content=line))

    def set_min_level(self, level: int) -> None:
        self._min_level = level

    def get_lines(self) -> list[str]:
        """Return lines as plain strings (for non-TUI consumers and tests)."""
        return [
            e.content.plain if isinstance(e.content, Text) else e.content
            for e in self._entries
        ]

    def get_entries(self) -> list[TailEntry]:
        """Return entries for rendering."""
        return list(self._entries)

    def resize(self, max_lines: int) -> None:
        """Change buffer capacity, discarding oldest entries if shrinking."""
        self._max_lines = max_lines
        self._entries = deque(self._entries, maxlen=max_lines)

    def clear(self) -> None:
        self._entries.clear()
