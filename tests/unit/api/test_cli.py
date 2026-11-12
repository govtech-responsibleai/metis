"""The `metis-api` command: the project folder of the store, from `--project-dir` or the
working directory. Uvicorn does not start; the tests keep the app that it gets."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from metis.api import cli

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import FastAPI


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> list[FastAPI]:
    """The apps that `metis-api` gives to Uvicorn."""
    apps: list[FastAPI] = []

    def run(app: FastAPI, **_options: Any) -> None:
        apps.append(app)

    monkeypatch.setattr("uvicorn.run", run)
    monkeypatch.setenv("METIS_ENV_FILE", "")
    monkeypatch.delenv("METIS_DATABASE_URL", raising=False)
    return apps


def _project(folder: Path) -> Path:
    folder.mkdir(parents=True)
    (folder / "pyproject.toml").write_text('[project]\nname = "project"\n')
    return folder


def test_project_dir_gives_the_store_that_folder(
    served: list[FastAPI],
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    elsewhere = _project(tmp_path / "elsewhere")
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("HOME", str(tmp_path))

    cli.main(["--project-dir", "~/project"])

    with TestClient(served[0]):
        pass
    assert (project_dir / "experiments" / "metis.db").is_file()
    assert not (elsewhere / "experiments").exists()


def test_without_project_dir_the_store_is_in_the_project_above_the_working_directory(
    served: list[FastAPI], project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    working = project_dir / "notes"
    working.mkdir()
    monkeypatch.chdir(working)

    cli.main([])

    with TestClient(served[0]):
        pass
    assert (project_dir / "experiments" / "metis.db").is_file()
    assert not (working / "experiments").exists()


def test_a_project_dir_that_is_not_a_folder_stops_the_command(
    served: list[FastAPI], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as stopped:
        cli.main(["--project-dir", str(tmp_path / "missing")])

    assert stopped.value.code == 2
    assert "is not an existing folder" in capsys.readouterr().err
    assert served == []
