"""Centralized logging for the METIS suite.

Provides structured logging via structlog with adaptive output:
- Rich console rendering when running in a TTY
- JSON lines when piped or in CI
"""

from __future__ import annotations

import inspect
import logging
import os
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from rich.console import Console
from rich.text import Text

if TYPE_CHECKING:
    from structlog.types import EventDict, Processor

_stderr_console = Console(stderr=True)


def iso_timestamp() -> str:
    """Return the current UTC time as an ISO-8601 string with a ``Z`` suffix.

    Matches the format of ``structlog.processors.TimeStamper(fmt="iso")`` so
    that log lines written outside the structlog pipeline stay consistent with
    structlog-rendered logs. structlog omits the fractional part when the
    microsecond is exactly 0; this helper always emits six digits.
    """
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structured logger.

    If name is omitted, infers from the calling module.
    """
    if name is None:
        frame = inspect.currentframe()
        caller = frame.f_back if frame else None
        name = caller.f_globals.get("__name__", __name__) if caller else __name__
    return structlog.get_logger(logger_name=name)


_NAME_TO_LEVEL = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


def _make_level_filter(min_level: int) -> Processor:
    """Return a processor that drops events below *min_level*."""

    def _filter(_logger: Any, _name: str, event_dict: EventDict) -> EventDict:
        level_name = event_dict.get("level", "debug")
        level_num = _NAME_TO_LEVEL.get(level_name, logging.DEBUG)
        if level_num < min_level:
            raise structlog.DropEvent
        return event_dict

    return _filter


def configure_logging(
    *,
    level: str | None = None,
    json: bool | None = None,
    pretty: bool | None = None,
    show_caller: bool = True,
) -> None:
    """Configure logging for the entire process. Call once at startup."""
    resolved_level = _resolve_level(level)
    use_json = _resolve_format(json=json, pretty=pretty)

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        _make_level_filter(resolved_level),
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    # foreign_pre_chain must NOT include _make_level_filter because
    # DropEvent crashes inside ProcessorFormatter. Stdlib's root logger
    # level gate (set below) handles filtering for third-party loggers.
    foreign_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if show_caller:
        callsite_adder = structlog.processors.CallsiteParameterAdder(
            [
                structlog.processors.CallsiteParameter.MODULE,
                structlog.processors.CallsiteParameter.LINENO,
            ]
        )
        shared_processors.append(callsite_adder)
        foreign_processors.append(callsite_adder)

    if use_json:
        renderer: Processor = structlog.processors.JSONRenderer()
    else:
        renderer = _rich_console_renderer

    structlog.configure(
        processors=[
            *shared_processors,
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    # Also configure stdlib logging so third-party logs route through
    root = logging.getLogger()
    root.setLevel(resolved_level)
    root.handlers.clear()

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=foreign_processors,
    )
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    root.addHandler(handler)


_LEVEL_STYLES = {
    "debug": "dim",
    "info": "green",
    "warning": "yellow",
    "error": "bold red",
    "critical": "bold white on red",
}


def _rich_console_renderer(_logger: Any, _name: str, event_dict: EventDict) -> str:
    """Render a log event to stderr using Rich."""
    level = event_dict.pop("level", "info")
    event = event_dict.pop("event", "")
    timestamp = event_dict.pop("timestamp", "")
    logger_name = event_dict.pop("logger_name", "")

    output = Text()
    output.append(f"{timestamp} ", style="dim")
    output.append(f"[{level.upper():<8}]", style=_LEVEL_STYLES.get(level, ""))
    output.append(f" {logger_name}  ", style="dim cyan")
    output.append(f"{event}", style="bold")

    event_dict.pop("_record", None)
    event_dict.pop("_from_stdlib", None)
    # Rendered by format_exc_info; render on its own line(s) rather than
    # clumping the multi-line traceback into the inline key=value pairs.
    exception = event_dict.pop("exception", None)
    if event_dict:
        pairs = " ".join(f"{k}={v}" for k, v in event_dict.items())
        output.append(f"  {pairs}", style="dim")
    if exception:
        output.append(f"\n{exception}", style="dim")

    _stderr_console.print(output, highlight=False)
    return ""


def _resolve_level(level: str | None) -> int:
    """Resolve log level: explicit arg > env var > default WARNING."""
    if level is not None:
        return getattr(logging, level.upper(), logging.WARNING)

    env_level = os.environ.get("METIS_LOG_LEVEL", "").upper()
    if env_level and hasattr(logging, env_level):
        return getattr(logging, env_level)

    return logging.WARNING


def _resolve_format(*, json: bool | None, pretty: bool | None) -> bool:
    """Resolve output format. Returns True for JSON, False for pretty.

    Priority: explicit json=True > explicit pretty=True > TTY detection.
    """
    if json is True:
        return True
    if pretty is True:
        return False
    return not sys.stderr.isatty()
