"""The lookup that turns an experiment id into its folder under experiments/execute/."""

from __future__ import annotations

from typing import TYPE_CHECKING

from metis.api.experiment_dirs import ExperimentNotFound, find_experiment_dir
from metis.core import execution_layout

if TYPE_CHECKING:
    from pathlib import Path

import pytest


def test_an_id_finds_the_folder_of_that_name(project_dir: Path) -> None:
    folder = project_dir / execution_layout.EXECUTIONS / "spec-20261116-101500"
    folder.mkdir(parents=True)

    assert find_experiment_dir(project_dir, "spec-20261116-101500") == folder


@pytest.mark.parametrize("experiment_id", ["..", "../design", "spec-*", "missing"])
def test_an_id_that_is_not_a_folder_name_finds_nothing(
    project_dir: Path, experiment_id: str
) -> None:
    executions = project_dir / execution_layout.EXECUTIONS
    (executions / "spec-20261116-101500").mkdir(parents=True)
    (project_dir / "experiments" / "design").mkdir()

    with pytest.raises(ExperimentNotFound) as caught:
        find_experiment_dir(project_dir, experiment_id)

    assert caught.value.code == "experiment_not_found"
    assert caught.value.status == 404
    assert caught.value.message == f"No experiment folder is named {experiment_id!r}."


def test_a_project_with_no_experiments_finds_nothing(project_dir: Path) -> None:
    with pytest.raises(ExperimentNotFound):
        find_experiment_dir(project_dir, "spec-20261116-101500")


def test_a_file_with_the_id_is_not_an_experiment(project_dir: Path) -> None:
    executions = project_dir / execution_layout.EXECUTIONS
    executions.mkdir(parents=True)
    (executions / "spec-20261116-101500").write_text("")

    with pytest.raises(ExperimentNotFound):
        find_experiment_dir(project_dir, "spec-20261116-101500")
