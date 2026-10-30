"""Rich Live + Layout composition for the TUI control plane."""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

from rich.console import Console, ConsoleOptions, RenderResult
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from .dashboard import render_dashboard

if TYPE_CHECKING:
    from types import TracebackType

    from .state import SimulationState
    from .tail import TailBuffer


class _LiveTailRenderable:
    """Renderable for a single worker's tail buffer.

    Renders exactly the allocated row count with entries top-anchored: new
    entries appear at the next available row below existing content, empty
    padding fills the bottom. Entries never shift position until the buffer
    is full and scrolling begins (oldest drops off the top, everything moves
    up by exactly 1 row). Each entry is truncated to 1 visual row.
    """

    def __init__(self, tail_buffer: TailBuffer) -> None:
        self._buf = tail_buffer

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        total_rows = max(1, (options.height or 10) - 1)
        width = options.max_width or 80
        entries = self._buf.get_entries()[-total_rows:]

        content_lines: list[Text] = []
        if not entries:
            content_lines.append(Text("(waiting for output)", style="dim"))
        else:
            for entry in entries:
                text = (
                    entry.content.copy()
                    if isinstance(entry.content, Text)
                    else Text(entry.content)
                )
                text.truncate(width - 1, overflow="ellipsis")
                content_lines.append(text)

        pad_count = total_rows - len(content_lines)

        output = Text()
        for i, line in enumerate(content_lines):
            if i > 0:
                output.append("\n")
            output.append_text(line)
        for _ in range(pad_count):
            output.append("\n")
        yield output


_active: bool = False


def is_tui_active() -> bool:
    return _active


def _create_live(layout: Layout, console: Console) -> Live:
    return Live(layout, console=console, refresh_per_second=1, screen=True)


class _LiveDashboardRenderable:
    """Renderable that re-renders the dashboard from current state on every frame."""

    def __init__(self, state: SimulationState) -> None:
        self._state = state

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        yield render_dashboard(self._state)


_REFRESH_DEBOUNCE_SECONDS = 0.2


def _compute_tail_max_lines(
    terminal_rows: int, tail_ratio: int, total_ratio: int
) -> int:
    """Derive tail buffer capacity from terminal height and layout ratios."""
    tail_rows = (terminal_rows * tail_ratio) // total_ratio
    return max(5, tail_rows - 2)


class TUIContext:
    """Context manager that owns the Rich Live display."""

    def __init__(
        self, state: SimulationState, tail_buffers: dict[str, TailBuffer]
    ) -> None:
        self._state = state
        self._tail_buffers = tail_buffers
        self._console = Console(stderr=True)
        self._last_refresh: float = 0.0

        try:
            terminal_rows = os.get_terminal_size().lines
        except OSError:
            terminal_rows = 24

        tail_max = _compute_tail_max_lines(terminal_rows, tail_ratio=3, total_ratio=5)
        for buf in tail_buffers.values():
            buf.resize(tail_max)

        self._layout = Layout()

        # Build tail section: one panel per worker, stacked vertically
        sorted_keys = sorted(tail_buffers.keys())
        tail_panels = [Layout(name=f"tail-{k}") for k in sorted_keys]

        if len(tail_panels) == 1:
            tail_section = Layout(name="tail", ratio=3)
            tail_section.update(
                Panel(
                    _LiveTailRenderable(tail_buffers[sorted_keys[0]]),
                    title="Log Tail",
                    border_style="dim",
                )
            )
        else:
            tail_section = Layout(name="tail", ratio=3)
            tail_section.split_column(*tail_panels)
            for key, panel_layout in zip(sorted_keys, tail_panels, strict=True):
                panel_layout.update(
                    Panel(
                        _LiveTailRenderable(tail_buffers[key]),
                        title=key,
                        border_style="dim",
                    )
                )

        self._layout.split_column(
            Layout(name="dashboard", ratio=2),
            tail_section,
        )
        self._layout["dashboard"].update(
            Panel(
                _LiveDashboardRenderable(state),
                title="Dashboard",
                border_style="blue",
            )
        )

        self._live: Live | None = None

    def __enter__(self) -> TUIContext:
        global _active
        _active = True
        self._live = _create_live(self._layout, self._console)
        self._live.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        global _active
        _active = False
        if self._live:
            self._live.__exit__(exc_type, exc_val, exc_tb)
            self._live = None

    def refresh(self) -> None:
        """Refresh the Live display, debounced to avoid burst redraws."""
        if not self._live:
            return
        now = time.monotonic()
        if (now - self._last_refresh) < _REFRESH_DEBOUNCE_SECONDS:
            return
        self._last_refresh = now
        self._live.refresh()
