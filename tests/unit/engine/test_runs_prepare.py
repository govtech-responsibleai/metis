"""Tests for ``metis.engine.runs.prepare_experiment``, called with no CLI."""

from __future__ import annotations

import io
import re
from datetime import datetime
from pathlib import Path

import pytest
from rich.console import Console

from metis.engine.runs import (
    ExperimentExistsError,
    InvalidInputsError,
    RunError,
    prepare_experiment,
)
from tests.unit.engine.test_cli_simulate import MINIMAL_EXPERIMENT

_FIXED_START = datetime(2026, 11, 7, 14, 30, 0)


class _FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return _FIXED_START


def _console() -> tuple[Console, io.StringIO]:
    text = io.StringIO()
    return Console(file=text, width=200), text


def _write_source(tmp_path: Path, content: str = MINIMAL_EXPERIMENT) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    (source / "specification.yaml").write_text(content)
    return source


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    return project


def test_prepare_experiment_returns_the_folder_before_any_trial_runs(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    def no_trials(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("prepare_experiment must not run a trial")

    monkeypatch.setattr(
        "metis.engine.simulation.experiment.execute_experiment", no_trials
    )
    source = _write_source(tmp_path)
    project = _project(tmp_path)
    console, text = _console()

    experiment_dir = prepare_experiment(source, project_dir=project, console=console)

    assert experiment_dir.parent == project / "experiments" / "execute"
    assert re.fullmatch(r"test-exp-\d{8}-\d{6}", experiment_dir.name)
    assert (experiment_dir / "inputs" / "specification.yaml").read_text() == (
        MINIMAL_EXPERIMENT
    )
    assert not (experiment_dir / "outputs").exists()
    assert text.getvalue() == ""
    assert capsys.readouterr().out == ""


def _missing_folder(tmp_path: Path) -> Path:
    return tmp_path / "nonexistent"


def _missing_specification(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    return source


def _not_valid(tmp_path: Path) -> Path:
    return _write_source(tmp_path, "schema_version: 1\nid: x\n")


def _missing_fixture(tmp_path: Path) -> Path:
    return _write_source(
        tmp_path, MINIMAL_EXPERIMENT.replace("fixtures: []", "fixtures: [gone.txt]")
    )


def _bad_criterion(tmp_path: Path) -> Path:
    return _write_source(
        tmp_path,
        MINIMAL_EXPERIMENT.replace(
            "tests.unit.engine.graders_for_tests.FixedScoreGrader", "no.such.Grader"
        ),
    )


@pytest.mark.parametrize(
    ("make_source", "message"),
    [
        (_missing_folder, "does not exist"),
        (_missing_specification, "missing required file 'specification.yaml'"),
        (_not_valid, "specification.yaml validation failed"),
        (_missing_fixture, "references fixture 'gone.txt'"),
        (_bad_criterion, "AC-1-1"),
    ],
)
def test_prepare_experiment_raises_for_inputs_that_are_not_valid(
    tmp_path: Path, capsys, make_source, message: str
) -> None:
    source = make_source(tmp_path)
    project = _project(tmp_path)
    console, text = _console()

    with pytest.raises(InvalidInputsError) as caught:
        prepare_experiment(source, project_dir=project, console=console)

    assert isinstance(caught.value, RunError)
    assert str(caught.value)
    assert "Error:" in text.getvalue()
    assert message in " ".join(text.getvalue().split())
    assert not (project / "experiments").exists()
    assert capsys.readouterr().out == ""


def test_prepare_experiment_raises_when_the_folder_name_is_used(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("metis.engine.runs._inputs.datetime", _FixedClock)
    source = _write_source(tmp_path)
    project = _project(tmp_path)
    console, text = _console()

    first = prepare_experiment(source, project_dir=project, console=console)
    first_files = sorted(p.relative_to(first) for p in first.rglob("*"))
    with pytest.raises(ExperimentExistsError) as caught:
        prepare_experiment(source, project_dir=project, console=console)

    assert isinstance(caught.value, RunError)
    assert "already exists" in " ".join(text.getvalue().split())
    assert sorted(p.relative_to(first) for p in first.rglob("*")) == first_files
