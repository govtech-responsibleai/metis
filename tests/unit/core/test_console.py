"""Tests for metis.core.console module."""

from rich.console import Console

from metis.core.console import console


class TestConsole:
    def test_is_console_instance(self):
        assert isinstance(console, Console)

    def test_writes_to_stdout(self, capsys):
        console.print("hello")
        captured = capsys.readouterr()
        assert "hello" in captured.out
        assert captured.err == ""
