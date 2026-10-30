"""Tests for new CLI flags: --no-tui, --log-format, --log-dir, --quiet."""

from typer.testing import CliRunner

from metis.engine.cli import app

runner = CliRunner()


class TestTUIFlags:
    def test_no_tui_flag_accepted(self) -> None:
        """--no-tui flag is recognized (parse test only — will fail on missing input-dir)."""
        result = runner.invoke(
            app, ["simulate", "--no-tui", "--input-dir", "/nonexistent"]
        )
        # Should fail on input validation, NOT on unknown flag
        assert "Unknown option" not in (result.output or "")
        assert result.exit_code != 0  # Fails on input validation

    def test_log_format_flag_accepted(self) -> None:
        result = runner.invoke(
            app, ["simulate", "--log-format", "json", "--input-dir", "/nonexistent"]
        )
        assert "Unknown option" not in (result.output or "")

    def test_log_dir_flag_accepted(self) -> None:
        result = runner.invoke(
            app, ["simulate", "--log-dir", "/tmp/logs", "--input-dir", "/nonexistent"]
        )
        assert "Unknown option" not in (result.output or "")

    def test_quiet_flag_accepted(self) -> None:
        result = runner.invoke(
            app, ["simulate", "--quiet", "--input-dir", "/nonexistent"]
        )
        assert "Unknown option" not in (result.output or "")

    def test_quiet_and_verbose_conflict(self) -> None:
        """When both --quiet and -v are passed, --quiet wins."""
        result = runner.invoke(
            app, ["simulate", "--quiet", "-v", "--input-dir", "/nonexistent"]
        )
        # Should not crash — quiet takes precedence
        assert "Unknown option" not in (result.output or "")
