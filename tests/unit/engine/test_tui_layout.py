"""Tests for TUI layout composition."""

import logging
from unittest.mock import MagicMock, patch

from rich.console import Console

from metis.engine.tui.layout import (
    TUIContext,
    _compute_tail_max_lines,
    _LiveTailRenderable,
    is_tui_active,
)
from metis.engine.tui.state import (
    SimulationScenarioState,
    SimulationState,
    SimulationTrialState,
)
from metis.engine.tui.tail import TailBuffer


def _make_state() -> SimulationState:
    scenarios = [
        SimulationScenarioState(
            scenario_id="test-scn",
            trials=[
                SimulationTrialState(
                    scenario_id="test-scn",
                    persona_id="test-per",
                    trial_index=1,
                    num_trials=1,
                    phase="pending",
                    current_turn=None,
                    max_turns=20,
                    turn_detail="",
                    duration_seconds=None,
                    stop_reason=None,
                ),
            ],
            phase="pending",
        ),
    ]
    return SimulationState(
        experiment_id="test-exp", scenarios=scenarios, total_trials=1
    )


class TestTUIContext:
    def test_context_manager_enters_and_exits(self) -> None:
        state = _make_state()
        tail = TailBuffer(max_lines=10)
        # Use a non-TTY console to avoid actual terminal manipulation
        with patch("metis.engine.tui.layout._create_live") as mock_live:
            mock_live.return_value.__enter__ = lambda s: s
            mock_live.return_value.__exit__ = lambda s, *a: None
            mock_live.return_value.update = lambda *a: None
            ctx = TUIContext(state=state, tail_buffers={"w0": tail})
            with ctx:
                assert is_tui_active()
            assert not is_tui_active()

    def test_refresh_does_not_raise(self) -> None:
        state = _make_state()
        tail = TailBuffer(max_lines=10)
        with patch("metis.engine.tui.layout._create_live") as mock_live:
            mock_live.return_value.__enter__ = lambda s: s
            mock_live.return_value.__exit__ = lambda s, *a: None
            mock_live.return_value.update = lambda *a: None
            ctx = TUIContext(state=state, tail_buffers={"w0": tail})
            with ctx:
                ctx.refresh()  # should not raise

    def test_refresh_debounces(self) -> None:
        state = _make_state()
        tail = TailBuffer(max_lines=10)
        with patch("metis.engine.tui.layout._create_live") as mock_live:
            mock_live.return_value.__enter__ = lambda s: s
            mock_live.return_value.__exit__ = lambda s, *a: None
            mock_live.return_value.refresh = MagicMock()
            ctx = TUIContext(state=state, tail_buffers={"w0": tail})
            with ctx:
                ctx.refresh()
                ctx.refresh()
                ctx.refresh()
            assert mock_live.return_value.refresh.call_count == 1


class TestLiveTailRenderable:
    def _render(self, renderable: _LiveTailRenderable, height: int = 10) -> str:
        console = Console(width=80)
        options = console.options.update(height=height)
        parts = list(renderable.__rich_console__(console, options))
        return parts[0].plain if parts else ""

    def test_empty_buffer_pads_to_full_height(self) -> None:
        buf = TailBuffer(max_lines=10)
        renderable = _LiveTailRenderable(buf)
        output = self._render(renderable, height=6)
        lines = output.split("\n")
        assert len(lines) == 5
        assert lines[0] == "(waiting for output)"
        assert all(line == "" for line in lines[1:])

    def test_partial_buffer_top_anchored(self) -> None:
        buf = TailBuffer(max_lines=10, min_level=logging.DEBUG)
        buf.append("line 1", level=logging.DEBUG)
        buf.append("line 2", level=logging.DEBUG)
        renderable = _LiveTailRenderable(buf)
        output = self._render(renderable, height=6)
        lines = output.split("\n")
        assert len(lines) == 5
        assert lines[0] == "line 1"
        assert lines[1] == "line 2"
        assert all(line == "" for line in lines[2:])

    def test_full_buffer_no_padding(self) -> None:
        buf = TailBuffer(max_lines=10, min_level=logging.DEBUG)
        for i in range(5):
            buf.append(f"line {i}", level=logging.DEBUG)
        renderable = _LiveTailRenderable(buf)
        output = self._render(renderable, height=6)
        lines = output.split("\n")
        assert len(lines) == 5
        assert lines == ["line 0", "line 1", "line 2", "line 3", "line 4"]

    def test_entries_stay_at_position_as_buffer_fills(self) -> None:
        buf = TailBuffer(max_lines=10, min_level=logging.DEBUG)
        renderable = _LiveTailRenderable(buf)

        buf.append("entry A", level=logging.DEBUG)
        output1 = self._render(renderable, height=6)
        assert output1.split("\n")[0] == "entry A"

        buf.append("entry B", level=logging.DEBUG)
        output2 = self._render(renderable, height=6)
        lines2 = output2.split("\n")
        assert lines2[0] == "entry A"
        assert lines2[1] == "entry B"

    def test_long_entries_truncated_to_single_row(self) -> None:
        buf = TailBuffer(max_lines=10, min_level=logging.DEBUG)
        buf.append("A" * 200, level=logging.DEBUG)
        renderable = _LiveTailRenderable(buf)
        output = self._render(renderable, height=6)
        lines = output.split("\n")
        assert len(lines) == 5
        assert len(lines[0]) <= 79


class TestComputeTailMaxLines:
    def test_standard_terminal(self) -> None:
        assert _compute_tail_max_lines(40, tail_ratio=3, total_ratio=5) == 22

    def test_small_terminal_clamps_to_minimum(self) -> None:
        assert _compute_tail_max_lines(10, tail_ratio=3, total_ratio=5) == 5
