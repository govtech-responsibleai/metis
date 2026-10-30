"""Routes structlog events to per-trial log files and the TUI tail buffer.

When the TUI is active, the LogRouter replaces core's _rich_console_renderer
as the final processor in structlog's chain. It renders each event to:
1. Per-trial log files (plain text or JSON — always at DEBUG)
2. The TUI tail buffer (styled Rich Text, same format as core's renderer)
3. Returns "" so structlog's PrintLogger writes nothing to stderr
   (Rich Live owns the terminal)
"""

from __future__ import annotations

import json as json_mod
import logging
import os
import time
from typing import IO, TYPE_CHECKING, Any, Literal

import structlog
from rich.text import Text

from metis.core.logging import get_logger, iso_timestamp

if TYPE_CHECKING:
    from pathlib import Path

    from structlog.types import EventDict

    from metis.engine.tui.tail import TailBuffer

_logger = get_logger(__name__)

_LEVEL_MAP = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}

_NOT_IN_FILE_LINE = frozenset(
    {
        "event",
        "level",
        "timestamp",
        "exception",
        "scenario_id",
        "task_id",
        "persona_id",
        "trial_index",
        "worker",
        "module",
        "lineno",
        "logger_name",
        "_record",
        "_from_stdlib",
    }
)
"""Keys a text line leaves out: the line has them already, or the file's name says them."""

_LEVEL_STYLES = {
    "debug": "dim",
    "info": "green",
    "warning": "yellow",
    "error": "bold red",
    "critical": "bold white on red",
}


def _trial_log_filename(
    scenario_id: str, persona_id: str, trial_index: int, num_trials: int
) -> str:
    """Build a per-trial log filename. ``trial_index`` is 1-based (first trial is 1)."""
    pad = max(2, len(str(num_trials)))
    return f"simulate-{scenario_id}_{persona_id}-{trial_index:0{pad}}.log"


class LogRouter:
    """Final structlog processor that replaces the default renderer.

    Routes every event to per-trial files and the tail buffer. When TUI is
    active, returns "" to suppress stderr (Rich Live owns the terminal).
    When no TUI, falls through to the original renderer for stderr output.
    """

    def __init__(
        self,
        log_dir: Path,
        log_format: Literal["text", "json"] = "text",
        tail_buffers: dict[str, TailBuffer] | None = None,
        fallback_renderer: Any = None,
        append: bool = False,
    ) -> None:
        self._log_dir = log_dir
        self._log_format = log_format
        self._tail_buffers = tail_buffers or {}
        self._fallback_renderer = fallback_renderer
        self._handles: dict[str, IO[str]] = {}
        self._start_time = time.monotonic()
        self._append = append
        log_dir.mkdir(parents=True, exist_ok=True)

    def _trial_key(self, scenario_id: str, persona_id: str, trial_index: int) -> str:
        return f"{scenario_id}:{persona_id}:{trial_index}"

    def open_trial(
        self,
        scenario_id: str,
        persona_id: str,
        trial_index: int,
        num_trials: int,
        *,
        run_dir: Path | None = None,
    ) -> None:
        key = self._trial_key(scenario_id, persona_id, trial_index)
        filename = _trial_log_filename(scenario_id, persona_id, trial_index, num_trials)
        path = self._log_dir / filename
        # Truncate for a fresh experiment; append when resuming, where this
        # file already holds the interrupted process's account of the run and
        # is the only record of the attempt whose artifacts were moved aside
        # (issue #346). Matches OrchestrationLogger's handling of simulate.log.
        mode = "a" if self._append else "w"
        self._handles[key] = open(path, mode, encoding="utf-8")  # noqa: SIM115
        if self._append and path.stat().st_size > 0:
            stamp = iso_timestamp()
            self._handles[key].write(f"\n--- [RESUMED {stamp}] ---\n\n")
        if run_dir is not None:
            try:
                relative_target = os.path.relpath(path, run_dir)
                symlink = run_dir / "simulate.log"
                if symlink.exists() or symlink.is_symlink():
                    symlink.unlink()
                symlink.symlink_to(relative_target)
            except Exception:
                _logger.debug(
                    "failed to create simulate.log symlink",
                    run_dir=str(run_dir),
                    log_path=str(path),
                )

    def close_trial(self, scenario_id: str, persona_id: str, trial_index: int) -> None:
        key = self._trial_key(scenario_id, persona_id, trial_index)
        handle = self._handles.pop(key, None)
        if handle:
            handle.flush()
            handle.close()

    def close_all(self) -> None:
        for handle in self._handles.values():
            handle.flush()
            handle.close()
        self._handles.clear()

    def process(self, logger: Any, method_name: str, event_dict: EventDict) -> str:
        """Structlog renderer: routes to files + tail, optionally to stderr."""
        scenario_id = event_dict.get("task_id") or event_dict.get("scenario_id")
        persona_id = event_dict.get("persona_id")
        trial_index = event_dict.get("trial_index")

        # Route to per-trial file (always at DEBUG — all events)
        if scenario_id and persona_id and trial_index is not None:
            key = self._trial_key(scenario_id, persona_id, trial_index)
            handle = self._handles.get(key)
            if handle:
                handle.write(self._format_file_line(event_dict) + "\n")

        # Route to per-worker tail buffer (or broadcast if no worker key)
        if self._tail_buffers:
            level_name = event_dict.get("level", "debug")
            level_num = _LEVEL_MAP.get(level_name, logging.DEBUG)
            styled = self._render_styled(event_dict)
            worker = event_dict.get("worker")
            if worker and worker in self._tail_buffers:
                self._tail_buffers[worker].append(styled, level=level_num)
            else:
                for buf in self._tail_buffers.values():
                    buf.append(styled, level=level_num)

        # When no TUI, fall through to the original renderer for stderr output
        if self._fallback_renderer is not None:
            return self._fallback_renderer(logger, method_name, event_dict)

        # TUI mode: suppress stderr output entirely (Live owns the terminal)
        raise structlog.DropEvent()

    def _elapsed_str(self) -> str:
        """Format elapsed time since router creation as HH:MM:SS."""
        elapsed = time.monotonic() - self._start_time
        h = int(elapsed) // 3600
        m = (int(elapsed) % 3600) // 60
        s = int(elapsed) % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    def _wall_clock_str(self, timestamp: str) -> str:
        """ISO-8601 UTC wall clock trimmed to whole seconds with a Z suffix.

        Reuses the structlog ``timestamp`` (TimeStamper(fmt="iso")) so it is
        byte-consistent with the per-trial log files. Drops fractional seconds
        for the live view but keeps ``Z`` so it is unambiguously UTC.
        """
        if not timestamp:
            return ""
        # Strip the trailing 'Z' suffix, drop the fractional part, re-append 'Z'.
        base = timestamp.removesuffix("Z").split(".", 1)[0]
        return f"{base}Z"

    def _render_styled(self, event_dict: EventDict) -> Text:
        """Build a styled Rich Text for the TUI tail panel."""
        event = event_dict.get("event", "")
        scenario_id = event_dict.get("task_id") or event_dict.get("scenario_id")
        persona_id = event_dict.get("persona_id")

        output = Text()
        wall = self._wall_clock_str(event_dict.get("timestamp", ""))
        if wall:
            output.append(f"{wall} ", style="dim")
        output.append(f"(+{self._elapsed_str()}) ", style="dim")
        if scenario_id and persona_id:
            output.append(f"[{scenario_id}:{persona_id}] ", style="dim cyan")
        output.append(event)
        if fields := self._fields(event_dict):
            output.append(f"  {' '.join(fields.split())}", style="dim")
        return output

    def _fields(self, event_dict: EventDict) -> str:
        """The event's own ``key=value`` pairs, without what the line already shows."""
        return " ".join(
            f"{k}={v}" for k, v in event_dict.items() if k not in _NOT_IN_FILE_LINE
        )

    def _format_file_line(self, event_dict: EventDict) -> str:
        """Format a line for per-trial log files (plain text or JSON)."""
        if self._log_format == "json":
            return json_mod.dumps(
                {k: v for k, v in event_dict.items() if k != "_record"},
                default=str,
            )
        timestamp = event_dict.get("timestamp", "")
        level = event_dict.get("level", "info").upper()
        event = event_dict.get("event", "")
        line = f"[{timestamp}] [{level:<8}] {event}"
        if fields := self._fields(event_dict):
            line += f"  {fields}"
        exception = event_dict.get("exception")
        return f"{line}\n{exception}" if exception else line


def setup_engine_logging(
    log_dir: Path,
    log_format: Literal["text", "json"] = "text",
    tail_buffers: dict[str, TailBuffer] | None = None,
    use_tui: bool = True,
    append: bool = False,
) -> LogRouter:
    """Create a LogRouter and install it as structlog's renderer.

    Replaces the last processor (core's _rich_console_renderer) with the
    router, which handles both file output and TUI tail rendering.
    When use_tui=False, core's renderer is kept as fallback so events
    still appear on stderr.
    Must be called AFTER configure_logging().

    ``append`` keeps an existing per-trial log rather than truncating it; pass
    the resume flag so a resumed run does not erase the earlier process's log.
    """
    config = structlog.get_config()
    current_processors = list(config.get("processors", []))

    # Capture the current renderer to use as fallback when no TUI
    fallback = None
    if not use_tui and current_processors:
        fallback = current_processors[-1]

    router = LogRouter(
        log_dir=log_dir,
        log_format=log_format,
        tail_buffers=tail_buffers,
        fallback_renderer=fallback,
        append=append,
    )

    # Replace the last processor (the renderer) with our router
    if current_processors:
        current_processors[-1] = router.process
    else:
        current_processors.append(router.process)

    structlog.configure(
        processors=current_processors,
        wrapper_class=config.get("wrapper_class"),
        context_class=config.get("context_class"),
        logger_factory=config.get("logger_factory"),
        cache_logger_on_first_use=False,
    )

    # In TUI mode, suppress the stdlib root handler's stderr output.
    # Third-party libraries (Playwright, httpx) use stdlib logging which
    # writes to stderr via the StreamHandler installed by configure_logging().
    # These writes corrupt the alternate screen that Rich Live owns.
    if use_tui:
        root = logging.getLogger()
        for handler in root.handlers:
            if isinstance(handler, logging.StreamHandler):
                handler.setLevel(logging.CRITICAL + 1)

    return router


def teardown_engine_logging(router: LogRouter) -> None:
    """Close all file handles and restore the default structlog renderer."""
    from metis.core.logging import configure_logging

    router.close_all()

    # Re-run core's configure_logging to restore the original renderer
    configure_logging(level="WARNING")
