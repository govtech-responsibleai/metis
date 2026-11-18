"""Routes structlog events to per-trial log files and the TUI tail buffer.

Each simulation has its own ``LogRouter``, held in a context variable for the time of the
run. While at least one run is alive, one processor (``_route``) replaces the renderer of
the process as the last processor of structlog's chain. It sends each event to the router of
the run in its context, so two simulations on two threads never write to each other's files.
An event with no run in its context goes to the renderer of the process, as before. The
router renders each event to:
1. Per-trial log files (plain text or JSON — always at DEBUG)
2. The TUI tail buffer (styled Rich Text, same format as core's renderer)
3. The renderer of the process when the TUI is off; else nothing, because Rich Live owns
   the terminal

When the last run ends, the structlog configuration is the one from before the first run.
"""

from __future__ import annotations

import contextvars
import json as json_mod
import logging
import os
import threading
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
        # What setup_engine_logging changed, so teardown_engine_logging can put it back.
        self.previous_handler_levels: dict[logging.Handler, int] = {}
        self.context_token: contextvars.Token[LogRouter | None] | None = None
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


_CURRENT_ROUTER: contextvars.ContextVar[LogRouter | None] = contextvars.ContextVar(
    "metis_engine_log_router", default=None
)
"""The router of the run in this context. The asyncio tasks of a run inherit it."""

_INSTALL_LOCK = threading.Lock()
_install_count = 0
_previous_config: dict[str, Any] = {}
_process_renderer: Any = None
"""The last processor that ``_route`` replaced, for an event with no run in its context."""


def _route(logger: Any, method_name: str, event_dict: EventDict) -> Any:
    """The last structlog processor while a run is alive: the router of the current run."""
    router = _CURRENT_ROUTER.get()
    if router is not None:
        return router.process(logger, method_name, event_dict)
    if _process_renderer is not None:
        return _process_renderer(logger, method_name, event_dict)
    return event_dict


def _install_route() -> Any:
    """Install ``_route`` for the first run of the process. Return the renderer it replaced."""
    global _install_count, _previous_config, _process_renderer
    with _INSTALL_LOCK:
        if _install_count == 0:
            config = structlog.get_config()
            processors = list(config.get("processors", []))
            _previous_config = dict(config)
            _process_renderer = processors[-1] if processors else None
            if processors:
                processors[-1] = _route
            else:
                processors.append(_route)
            structlog.configure(
                processors=processors,
                wrapper_class=config.get("wrapper_class"),
                context_class=config.get("context_class"),
                logger_factory=config.get("logger_factory"),
                cache_logger_on_first_use=False,
            )
        _install_count += 1
        return _process_renderer


def _remove_route() -> None:
    """Put back the configuration from before the first run, when the last run ends.

    ``_process_renderer`` stays: a thread with no run can still call ``_route`` from the
    processors that it read before this, and its event must reach the renderer. The next
    first run replaces it.
    """
    global _install_count, _previous_config
    with _INSTALL_LOCK:
        _install_count -= 1
        if _install_count == 0:
            structlog.configure(**_previous_config)
            _previous_config = {}


def setup_engine_logging(
    log_dir: Path,
    log_format: Literal["text", "json"] = "text",
    tail_buffers: dict[str, TailBuffer] | None = None,
    use_tui: bool = True,
    append: bool = False,
) -> LogRouter:
    """Create a LogRouter and make it the router of the run in the current context.

    The first run of the process installs one processor in place of the renderer of the
    process (core's _rich_console_renderer). Later runs change no configuration. When
    use_tui=False, the renderer of the process is the fallback of the router, so events
    still appear on stderr.
    Must be called AFTER configure_logging().

    ``append`` keeps an existing per-trial log rather than truncating it; pass
    the resume flag so a resumed run does not erase the earlier process's log.

    Call ``teardown_engine_logging`` in the same context.
    """
    process_renderer = _install_route()
    router = LogRouter(
        log_dir=log_dir,
        log_format=log_format,
        tail_buffers=tail_buffers,
        fallback_renderer=None if use_tui else process_renderer,
        append=append,
    )
    router.context_token = _CURRENT_ROUTER.set(router)

    # In TUI mode, suppress the stdlib root handler's stderr output.
    # Third-party libraries (Playwright, httpx) use stdlib logging which
    # writes to stderr via the StreamHandler installed by configure_logging().
    # These writes corrupt the alternate screen that Rich Live owns.
    # Only the CLI uses the TUI, and it runs one simulation in its process.
    if use_tui:
        root = logging.getLogger()
        for handler in root.handlers:
            if isinstance(handler, logging.StreamHandler):
                router.previous_handler_levels[handler] = handler.level
                handler.setLevel(logging.CRITICAL + 1)

    return router


def teardown_engine_logging(router: LogRouter) -> None:
    """Close all file handles and put back the logging from before ``setup_engine_logging``.

    The context has no router again. The last run of the process puts back the structlog
    configuration, and each run puts back the level of each stderr handler that TUI mode
    silenced, so a caller whose process outlives the run keeps its own logging. A second
    teardown of the same router changes nothing, so it cannot remove the route of another run.
    """
    router.close_all()
    if router.context_token is None:
        return
    _CURRENT_ROUTER.reset(router.context_token)
    router.context_token = None
    _remove_route()
    for handler, level in router.previous_handler_levels.items():
        handler.setLevel(level)
