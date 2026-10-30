"""Tests for per-run log file routing."""

from __future__ import annotations

import io
import logging
import re
from pathlib import Path
from typing import Any

import structlog
from rich.console import Console

from metis.core.logging import configure_logging, get_logger
from metis.engine.logging.router import (
    LogRouter,
    setup_engine_logging,
    teardown_engine_logging,
)
from metis.engine.tui.layout import _LiveTailRenderable
from metis.engine.tui.tail import TailBuffer

# ISO-8601 UTC wall clock trimmed to whole seconds + Z, then (+HH:MM:SS) elapsed
_TAIL_PREFIX = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z \(\+\d{2}:\d{2}:\d{2}\) "
)


class TestLogRouter:
    def test_creates_log_dir(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        LogRouter(log_dir=log_dir, log_format="text")
        assert log_dir.exists()

    def test_open_trial_creates_file(self, tmp_path: Path) -> None:
        router = LogRouter(log_dir=tmp_path, log_format="text")
        router.open_trial("direct-question", "cooperative", trial_index=1, num_trials=1)
        expected = tmp_path / "simulate-direct-question_cooperative-01.log"
        assert expected.exists()

    def test_reopened_trial_replaces_old_log(self, tmp_path: Path) -> None:
        router = LogRouter(log_dir=tmp_path, log_format="text")
        router.open_trial("scn", "per", trial_index=1, num_trials=1)
        self._process(
            router,
            {
                "event": "old attempt",
                "level": "info",
                "scenario_id": "scn",
                "persona_id": "per",
                "trial_index": 1,
            },
        )
        router.close_trial("scn", "per", trial_index=1)
        router.open_trial("scn", "per", trial_index=1, num_trials=1)
        self._process(
            router,
            {
                "event": "new attempt",
                "level": "info",
                "scenario_id": "scn",
                "persona_id": "per",
                "trial_index": 1,
            },
        )
        router.close_trial("scn", "per", trial_index=1)
        content = (tmp_path / "simulate-scn_per-01.log").read_text()
        assert "old attempt" not in content
        assert "new attempt" in content

    def test_append_router_keeps_the_previous_log(self, tmp_path: Path) -> None:
        """A resumed process must not destroy the interrupted run's log."""
        first = LogRouter(log_dir=tmp_path, log_format="text")
        first.open_trial("scn", "per", trial_index=1, num_trials=1)
        self._process(
            first,
            {
                "event": "old process",
                "level": "info",
                "scenario_id": "scn",
                "persona_id": "per",
                "trial_index": 1,
            },
        )
        first.close_trial("scn", "per", trial_index=1)

        resumed = LogRouter(log_dir=tmp_path, log_format="text", append=True)
        resumed.open_trial("scn", "per", trial_index=1, num_trials=1)
        self._process(
            resumed,
            {
                "event": "resumed process",
                "level": "info",
                "scenario_id": "scn",
                "persona_id": "per",
                "trial_index": 1,
            },
        )
        resumed.close_trial("scn", "per", trial_index=1)

        content = (tmp_path / "simulate-scn_per-01.log").read_text()
        assert "old process" in content
        assert "resumed process" in content
        assert content.index("old process") < content.index("resumed process")

    def test_trial_zero_padding_multi(self, tmp_path: Path) -> None:
        router = LogRouter(log_dir=tmp_path, log_format="text")
        router.open_trial("scenario", "persona", trial_index=1, num_trials=10)
        expected = tmp_path / "simulate-scenario_persona-01.log"
        assert expected.exists()
        router.open_trial("scenario", "persona", trial_index=10, num_trials=10)
        expected2 = tmp_path / "simulate-scenario_persona-10.log"
        assert expected2.exists()

    def _process(self, router: LogRouter, event_dict: dict[str, Any]) -> None:
        """Call router.process, expecting DropEvent when no fallback renderer."""
        import pytest

        with pytest.raises(structlog.DropEvent):
            router.process(None, event_dict.get("level", "info"), event_dict.copy())

    def test_process_routes_to_active_run_file(self, tmp_path: Path) -> None:
        router = LogRouter(log_dir=tmp_path, log_format="text")
        router.open_trial("scn", "per", trial_index=1, num_trials=1)
        event_dict = {
            "event": "test message",
            "level": "info",
            "timestamp": "2026-08-05T10:00:00",
            "scenario_id": "scn",
            "persona_id": "per",
            "trial_index": 1,
        }
        self._process(router, event_dict)
        router.close_all()
        log_file = tmp_path / "simulate-scn_per-01.log"
        content = log_file.read_text()
        assert "test message" in content

    def test_process_sends_to_tail_buffer(self, tmp_path: Path) -> None:
        tail = TailBuffer(max_lines=10, min_level=logging.DEBUG)
        router = LogRouter(
            log_dir=tmp_path, log_format="text", tail_buffers={"w0": tail}
        )
        router.open_trial("scn", "per", trial_index=1, num_trials=1)
        event_dict = {
            "event": "tail test",
            "level": "warning",
            "timestamp": "2026-08-05T10:00:00",
            "scenario_id": "scn",
            "persona_id": "per",
            "trial_index": 1,
            "worker": "w0",
        }
        self._process(router, event_dict)
        lines = tail.get_lines()
        assert any("tail test" in line for line in lines)
        matching = [line for line in lines if "tail test" in line]
        assert matching, "tail line missing"
        assert _TAIL_PREFIX.match(matching[0]), (
            f"tail prefix not ISO-8601 Z + (+elapsed): {matching[0]!r}"
        )

    def test_close_trial_flushes(self, tmp_path: Path) -> None:
        router = LogRouter(log_dir=tmp_path, log_format="text")
        router.open_trial("scn", "per", trial_index=1, num_trials=1)
        event_dict = {
            "event": "flush test",
            "level": "debug",
            "timestamp": "2026-08-05T10:00:00",
            "scenario_id": "scn",
            "persona_id": "per",
            "trial_index": 1,
        }
        self._process(router, event_dict)
        router.close_trial("scn", "per", trial_index=1)
        log_file = tmp_path / "simulate-scn_per-01.log"
        content = log_file.read_text()
        assert "flush test" in content

    def test_json_format(self, tmp_path: Path) -> None:
        import json

        router = LogRouter(log_dir=tmp_path, log_format="json")
        router.open_trial("scn", "per", trial_index=1, num_trials=1)
        event_dict = {
            "event": "json test",
            "level": "info",
            "timestamp": "2026-08-05T10:00:00",
            "scenario_id": "scn",
            "persona_id": "per",
            "trial_index": 1,
        }
        self._process(router, event_dict)
        router.close_all()
        log_file = tmp_path / "simulate-scn_per-01.log"
        line = log_file.read_text().strip()
        parsed = json.loads(line)
        assert parsed["event"] == "json test"

    def test_wall_clock_str_trims_fractional_and_keeps_z(self, tmp_path: Path) -> None:
        router = LogRouter(log_dir=tmp_path, log_format="text")
        # production-typical: fractional seconds + Z -> trimmed to whole seconds + Z
        assert (
            router._wall_clock_str("2026-09-02T00:51:17.138406Z")
            == "2026-09-02T00:51:17Z"
        )
        # no fractional, no Z -> whole seconds + Z appended
        assert router._wall_clock_str("2026-08-05T10:00:00") == "2026-08-05T10:00:00Z"
        # empty/absent -> empty string, no raise
        assert router._wall_clock_str("") == ""

    def test_text_file_includes_rendered_exception(self, tmp_path: Path) -> None:
        router = LogRouter(log_dir=tmp_path, log_format="text")
        router.open_trial("scn", "per", trial_index=1, num_trials=1)
        rendered_tb = (
            "Traceback (most recent call last):\n"
            '  File "runner.py", line 42, in run\n'
            '    raise RuntimeError("kaboom")\n'
            "RuntimeError: kaboom"
        )
        event_dict = {
            "event": "worker crash",
            "level": "error",
            "timestamp": "2026-08-05T10:00:00",
            "scenario_id": "scn",
            "persona_id": "per",
            "trial_index": 1,
            "exception": rendered_tb,
        }
        self._process(router, event_dict)
        router.close_all()
        content = (tmp_path / "simulate-scn_per-01.log").read_text()
        # Single-line marker preserved, traceback appended on following lines.
        assert "[ERROR   ] worker crash" in content
        assert "Traceback (most recent call last):" in content
        assert "RuntimeError: kaboom" in content

    def test_text_file_no_exception_stays_single_line(self, tmp_path: Path) -> None:
        router = LogRouter(log_dir=tmp_path, log_format="text")
        router.open_trial("scn", "per", trial_index=1, num_trials=1)
        event_dict = {
            "event": "ordinary event",
            "level": "info",
            "timestamp": "2026-08-05T10:00:00",
            "scenario_id": "scn",
            "persona_id": "per",
            "trial_index": 1,
        }
        self._process(router, event_dict)
        router.close_all()
        content = (tmp_path / "simulate-scn_per-01.log").read_text()
        # Exactly one line (plus the trailing newline written by process()).
        assert content == "[2026-08-05T10:00:00] [INFO    ] ordinary event\n"

    def test_text_file_line_keeps_the_events_own_fields(self, tmp_path: Path) -> None:
        router = LogRouter(log_dir=tmp_path, log_format="text")
        router.open_trial("scn", "per", trial_index=1, num_trials=1)
        event_dict = {
            "event": "session_id_found",
            "level": "info",
            "timestamp": "2026-08-05T10:00:00",
            "scenario_id": "scn",
            "task_id": "scn",
            "persona_id": "per",
            "trial_index": 1,
            "worker": "w1",
            "module": "http",
            "lineno": 227,
            "session_id": "s-1",
            "entry": "e5",
        }
        self._process(router, event_dict)
        router.close_all()
        content = (tmp_path / "simulate-scn_per-01.log").read_text()
        # What the file already says (its name, level, time) is not repeated.
        assert content == (
            "[2026-08-05T10:00:00] [INFO    ] session_id_found"
            "  session_id=s-1 entry=e5\n"
        )

    def test_tail_line_shows_the_events_fields_clipped_on_one_row(
        self, tmp_path: Path
    ) -> None:
        router = LogRouter(log_dir=tmp_path, log_format="text")
        line = router._render_styled(
            {
                "event": "runner_agent_tool_call",
                "level": "info",
                "timestamp": "2026-08-05T10:00:00",
                "scenario_id": "scn",
                "persona_id": "per",
                "trial_index": 1,
                "worker": "w1",
                "tool": "http_request",
                "result": "refused",
                "detail": "quoted nothing\nto send " + "x" * 200,
            }
        )

        assert (
            "runner_agent_tool_call  tool=http_request result=refused detail="
            in line.plain
        )
        assert "worker" not in line.plain and "trial_index" not in line.plain
        assert "\n" not in line.plain
        buffer = TailBuffer(max_lines=3, min_level=logging.DEBUG)
        buffer.append(line)
        console = Console(width=100, file=io.StringIO(), force_terminal=False)
        console.print(_LiveTailRenderable(buffer), height=2)
        rows = [r for r in console.file.getvalue().splitlines() if r.strip()]  # type: ignore[attr-defined]
        assert len(rows) == 1  # the panel clips an entry to one row
        assert rows[0].endswith("…")

    def test_open_trial_with_run_dir_creates_symlink(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        run_dir = tmp_path / "runs" / "my-run"
        run_dir.mkdir(parents=True)
        router = LogRouter(log_dir=log_dir, log_format="text")
        router.open_trial("scn", "per", trial_index=1, num_trials=1, run_dir=run_dir)
        symlink = run_dir / "simulate.log"
        assert symlink.is_symlink(), "simulate.log should be a symlink"
        assert symlink.resolve() == (log_dir / "simulate-scn_per-01.log").resolve()

    def test_open_trial_with_run_dir_writes_visible_through_symlink(
        self, tmp_path: Path
    ) -> None:
        log_dir = tmp_path / "logs"
        run_dir = tmp_path / "runs" / "my-run"
        run_dir.mkdir(parents=True)
        router = LogRouter(log_dir=log_dir, log_format="text")
        router.open_trial("scn", "per", trial_index=1, num_trials=1, run_dir=run_dir)
        event_dict = {
            "event": "hello through symlink",
            "level": "info",
            "timestamp": "2026-09-17T10:00:00",
            "scenario_id": "scn",
            "persona_id": "per",
            "trial_index": 1,
        }
        self._process(router, event_dict)
        router.close_all()
        content = (run_dir / "simulate.log").read_text()
        assert "hello through symlink" in content

    def test_open_trial_without_run_dir_unchanged(self, tmp_path: Path) -> None:
        router = LogRouter(log_dir=tmp_path, log_format="text")
        router.open_trial("scn", "per", trial_index=1, num_trials=1)
        # No simulate.log symlink should appear at tmp_path level
        assert not (tmp_path / "simulate.log").exists()
        expected_log = tmp_path / "simulate-scn_per-01.log"
        assert expected_log.exists()

    def test_open_trial_symlink_failure_does_not_raise(
        self, tmp_path, monkeypatch
    ) -> None:
        log_dir = tmp_path / "logs"
        run_dir = tmp_path / "runs" / "my-run"
        run_dir.mkdir(parents=True)
        router = LogRouter(log_dir=log_dir, log_format="text")
        # Make symlink_to raise to simulate e.g. unsupported filesystem
        from pathlib import Path as _Path

        def broken_symlink(self, *args, **kwargs):
            raise OSError("symlinks not supported")

        monkeypatch.setattr(_Path, "symlink_to", broken_symlink)
        # Should not raise — guard swallows the error
        router.open_trial("scn", "per", trial_index=1, num_trials=1, run_dir=run_dir)

    def test_json_file_carries_exception_field(self, tmp_path: Path) -> None:
        import json

        router = LogRouter(log_dir=tmp_path, log_format="json")
        router.open_trial("scn", "per", trial_index=1, num_trials=1)
        event_dict = {
            "event": "worker crash",
            "level": "error",
            "timestamp": "2026-08-05T10:00:00",
            "scenario_id": "scn",
            "persona_id": "per",
            "trial_index": 1,
            "exception": "Traceback (most recent call last):\nRuntimeError: kaboom",
        }
        self._process(router, event_dict)
        router.close_all()
        line = (tmp_path / "simulate-scn_per-01.log").read_text().strip()
        parsed = json.loads(line)
        assert "RuntimeError: kaboom" in parsed["exception"]


class TestTracebackEndToEnd:
    """The exact bug configuration: text per-run logs with the TUI active."""

    def setup_method(self) -> None:
        structlog.reset_defaults()
        logging.getLogger().handlers.clear()

    def teardown_method(self) -> None:
        structlog.reset_defaults()
        logging.getLogger().handlers.clear()

    def test_exception_traceback_lands_in_text_run_file(self, tmp_path: Path) -> None:
        configure_logging(level="DEBUG", pretty=True)
        router = setup_engine_logging(tmp_path, log_format="text", use_tui=True)
        router.open_trial("scn", "per", trial_index=1, num_trials=1)
        log = get_logger("test.e2e")
        try:
            raise RuntimeError("kaboom-e2e")
        except RuntimeError:
            log.exception(
                "worker crash",
                scenario_id="scn",
                persona_id="per",
                trial_index=1,
            )
        teardown_engine_logging(router)

        content = (tmp_path / "simulate-scn_per-01.log").read_text()
        assert "worker crash" in content
        assert "Traceback (most recent call last):" in content
        assert "RuntimeError: kaboom-e2e" in content


class TestAppendWiring:
    """setup_engine_logging reconfigures structlog globally, so reset after each."""

    def teardown_method(self) -> None:
        structlog.reset_defaults()
        logging.getLogger().handlers.clear()

    def test_setup_engine_logging_passes_append_through(self, tmp_path: Path) -> None:
        """Reads the private flag deliberately. Observing it behaviourally would
        mean driving two full setup/teardown cycles against one directory, which
        tests structlog's global reconfiguration rather than the passthrough."""
        router = setup_engine_logging(tmp_path, log_format="text", append=True)
        try:
            assert router._append is True
        finally:
            teardown_engine_logging(router)
