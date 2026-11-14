"""`metis doctor` through the top-level CLI. `metis_cli` imports every package, so this test
lives outside `tests/unit/core`. The network is mocked."""

from __future__ import annotations

from typing import TYPE_CHECKING

from typer.testing import CliRunner

from metis.core import doctor
from tests.unit.core.test_doctor import GOOD_ENV, _mock_http

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_cli_exit_codes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import metis_cli

    monkeypatch.setenv("METIS_ENV_FILE", str(tmp_path / ".env"))
    (tmp_path / ".env").write_text("")
    for name in (*doctor.REQUIRED_VARS, *doctor.LANGFUSE_VARS):
        monkeypatch.delenv(name, raising=False)
    runner = CliRunner()
    assert runner.invoke(metis_cli.app, ["doctor"]).exit_code == 1

    _mock_http(monkeypatch)
    for name, value in GOOD_ENV.items():
        monkeypatch.setenv(name, value)
    assert runner.invoke(metis_cli.app, ["doctor"]).exit_code == 0
