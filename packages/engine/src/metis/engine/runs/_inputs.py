"""Check the inputs of a run and create its experiment folder."""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from typing import TYPE_CHECKING

from metis.core import execution_layout
from metis.engine.runs.errors import (
    EvaluationInputError,
    ExperimentExistsError,
    InvalidInputsError,
)

if TYPE_CHECKING:
    from pathlib import Path

    from rich.console import Console

    from metis.engine.simulation.types import Specification


def validate_inputs(input_dir: Path, *, console: Console) -> Specification:
    """Check every input of a new run before any model call, and return its Specification.

    It prints the first error to ``console`` and raises ``InvalidInputsError``. The grader
    errors are the exception: it prints all of them, so one run lists everything to fix.
    """
    from pydantic import ValidationError

    from metis.engine.simulation.types import Specification

    def fail(message: str) -> InvalidInputsError:
        console.print(f"Error: {message}", style="bold red")
        return InvalidInputsError(message)

    if not input_dir.is_dir():
        raise fail(f"input directory '{input_dir}' does not exist")

    experiment_path = input_dir / "specification.yaml"
    if not experiment_path.exists():
        raise fail(f"missing required file 'specification.yaml' in {input_dir}")

    try:
        specification = Specification.load_file(experiment_path)
    except ValidationError as e:
        first = e.errors()[0]
        loc = " → ".join(str(part) for part in first["loc"]) if first["loc"] else "root"
        raise fail(
            f"specification.yaml validation failed: {loc} — {first['msg']}"
        ) from None
    except Exception as e:
        raise fail(f"failed to parse specification.yaml: {e}") from None

    seen_personas: set[str] = set()
    for persona in specification.personas:
        if persona.id in seen_personas:
            raise fail(f"duplicate persona id '{persona.id}' in specification.yaml")
        seen_personas.add(persona.id)

    fixtures_dir = input_dir / "fixtures"
    for task in specification.resolved_tasks():
        for fixture in task.fixtures:
            if not (fixtures_dir / fixture).exists():
                raise fail(
                    f"Task '{task.task_id}' references fixture '{fixture}' which does not exist in {fixtures_dir}"
                )

    errors = _grader_setup_errors(specification)
    for message in errors:
        # markup=False: pydantic messages contain "[...]"; soft_wrap: keep each error on one
        # line so it can be grepped from logs.
        console.print(
            f"Error: {message}", style="bold red", markup=False, soft_wrap=True
        )
    if errors:
        raise InvalidInputsError("\n".join(errors))
    return specification


def _grader_setup_errors(specification: Specification) -> list[str]:
    """Every criterion whose grader can't be built from the spec alone, as messages.

    Each criterion is checked once, however many tasks reference it. The judge model is
    resolved exactly as the run will resolve it, so a JudgeArgs grader validates with a model
    in place. ``check_setup`` runs after its args validate. No client or credentials are
    needed: the gateway is checked separately, at the start of ``evaluate``.
    """
    from metis.engine.evaluation import GraderSetupError, build_grader

    errors: list[str] = []
    criteria_by_id = {c.id: c for b in specification.behaviours() for c in b.criteria}
    checked: set[str] = set()
    default_judge_model = specification.experiment.defaults.judge_model
    for scenario in specification.resolved_tasks():
        for ref in scenario.grader_refs:
            if ref.criterion_id in checked:
                continue
            checked.add(ref.criterion_id)
            try:
                built = build_grader(
                    criteria_by_id[ref.criterion_id],
                    default_judge_model=default_judge_model,
                    env=os.environ,
                )
            except GraderSetupError as exc:
                errors.append(str(exc))
                continue
            try:
                problems = type(built).check_setup(built.args, specification)
            except Exception as exc:  # a grader bug must not crash validation
                problems = [f"check_setup raised {type(exc).__name__}: {exc}"]
            errors.extend(f"Criterion '{ref.criterion_id}': {p}" for p in problems)
    return errors


def prepare_experiment(input_dir: Path, *, project_dir: Path, console: Console) -> Path:
    """Check ``input_dir``, create a new experiment folder, copy the inputs in, and return it.

    The folder is ``<project_dir>/experiments/execute/<specification id>-<YYYYmmdd-HHMMSS>/``.
    It calls no model and runs no trial, so a caller can name the experiment before the
    trials start. ``project_dir`` must be an existing folder.

    The caller sets up the process first: it loads ``.env``. Only one run at a time is safe
    in one process.

    :raises InvalidInputsError: When an input is not valid. Nothing is created.
    :raises ExperimentExistsError: When a run of the same Specification started in the
        same second. The folder that exists is left as it is.
    """
    source = input_dir.resolve()
    specification = validate_inputs(source, console=console)
    suffix = datetime.now().strftime("%Y%m%d-%H%M%S")
    experiment_dir = (
        project_dir / execution_layout.EXECUTIONS / f"{specification.id}-{suffix}"
    )
    experiment_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        experiment_dir.mkdir()
    except FileExistsError:
        message = (
            f"the run folder '{experiment_dir}' already exists. "
            "A run of this Specification started in the same second. "
            "Start the run again."
        )
        console.print(f"Error: {message}", style="bold red", markup=False)
        raise ExperimentExistsError(message) from None
    shutil.copytree(source, experiment_dir / execution_layout.INPUTS)
    return experiment_dir


def resolve_experiment_dir(experiment_dir: Path, *, console: Console) -> Path:
    """Return ``experiment_dir`` resolved, once it is an experiment folder of this layout.

    :raises EvaluationInputError: When it does not exist, has no ``inputs/`` snapshot, or
        uses the earlier folder layout.
    """
    resolved = experiment_dir.resolve()
    if not resolved.is_dir():
        console.print(
            f"Error: experiment directory '{resolved}' does not exist",
            style="bold red",
        )
        raise EvaluationInputError("invalid experiment directory")
    if not (resolved / execution_layout.INPUTS).is_dir():
        console.print(
            f"Error: '{resolved}' is not a simulation output directory "
            "(no 'inputs/' snapshot). Run 'metis engine simulate' first.",
            style="bold red",
        )
        raise EvaluationInputError("invalid experiment directory")
    if (resolved / "trials").is_dir() or (resolved / "reports").is_dir():
        console.print(
            "Error: this execution uses an earlier folder layout. "
            "Move it to outputs/trials/ and outputs/reports/ before use.",
            style="bold red",
        )
        raise EvaluationInputError("unsupported execution layout")
    return resolved
