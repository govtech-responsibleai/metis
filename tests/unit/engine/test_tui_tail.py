"""Tests for TUI tail ring buffer."""

import logging

from metis.engine.tui.tail import TailBuffer


class TestTailBuffer:
    def test_empty_buffer(self) -> None:
        buf = TailBuffer(max_lines=5)
        assert buf.get_lines() == []

    def test_append_within_capacity(self) -> None:
        buf = TailBuffer(max_lines=5, min_level=logging.DEBUG)
        buf.append("line 1", level=logging.DEBUG)
        buf.append("line 2", level=logging.INFO)
        assert buf.get_lines() == ["line 1", "line 2"]

    def test_evicts_oldest_beyond_capacity(self) -> None:
        buf = TailBuffer(max_lines=3, min_level=logging.DEBUG)
        for i in range(5):
            buf.append(f"line {i}", level=logging.DEBUG)
        assert buf.get_lines() == ["line 2", "line 3", "line 4"]

    def test_level_filtering(self) -> None:
        buf = TailBuffer(max_lines=10, min_level=logging.WARNING)
        buf.append("debug msg", level=logging.DEBUG)
        buf.append("info msg", level=logging.INFO)
        buf.append("warning msg", level=logging.WARNING)
        buf.append("error msg", level=logging.ERROR)
        assert buf.get_lines() == ["warning msg", "error msg"]

    def test_set_min_level_changes_filter(self) -> None:
        buf = TailBuffer(max_lines=10, min_level=logging.WARNING)
        buf.append("info msg", level=logging.INFO)
        assert buf.get_lines() == []
        buf.set_min_level(logging.DEBUG)
        buf.append("info msg 2", level=logging.INFO)
        assert buf.get_lines() == ["info msg 2"]

    def test_resize_grows(self) -> None:
        buf = TailBuffer(max_lines=3, min_level=logging.DEBUG)
        for i in range(3):
            buf.append(f"line {i}", level=logging.DEBUG)
        buf.resize(5)
        buf.append("line 3", level=logging.DEBUG)
        buf.append("line 4", level=logging.DEBUG)
        assert buf.get_lines() == ["line 0", "line 1", "line 2", "line 3", "line 4"]

    def test_resize_shrinks(self) -> None:
        buf = TailBuffer(max_lines=5, min_level=logging.DEBUG)
        for i in range(5):
            buf.append(f"line {i}", level=logging.DEBUG)
        buf.resize(3)
        assert buf.get_lines() == ["line 2", "line 3", "line 4"]

    def test_clear(self) -> None:
        buf = TailBuffer(max_lines=5, min_level=logging.DEBUG)
        buf.append("line 1", level=logging.DEBUG)
        buf.clear()
        assert buf.get_lines() == []
