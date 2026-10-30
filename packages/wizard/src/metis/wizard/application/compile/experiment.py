"""Validate and serialize the shared evaluation Specification."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import yaml

from metis.wizard.application.matching.matcher import validate_grader_args

if TYPE_CHECKING:
    from pathlib import Path

    from metis.wizard.domain.specification import Specification

SCHEMA_VERSION = 2
DEFAULT_RUNNER_FACTORY_REF = "metis.engine.simulation.runners.http.HttpRunnerFactory"


class CompilationError(Exception):
    """The Specification is not ready for execution."""


def compile_experiment(
    specification: Specification, experiment_id: str
) -> dict[str, Any]:
    document = specification.model_copy(deep=True)
    document.id = specification.id or experiment_id
    from metis.wizard.domain.materializer import assign_task_ids

    assign_task_ids(document)
    errors = document.execution_errors()
    for behaviour in document.behaviours():
        for criterion in behaviour.criteria:
            try:
                validate_grader_args(
                    criterion.grader_fqn,
                    criterion.grader_args,
                    description=criterion.description,
                )
            except (ValueError, TypeError) as exc:
                errors.append(f"Criterion {criterion.id}: {exc}")
    if errors:
        raise CompilationError(" ".join(errors))
    return document.model_dump(mode="json")


def to_yaml(document: dict[str, Any]) -> str:
    header = {
        key: document[key] for key in ("schema_version", "id", "runner_factory_ref")
    }
    return yaml.safe_dump(
        {**header, **document}, sort_keys=False, allow_unicode=True, width=88
    )


def write_experiment(
    specification: Specification, experiment_id: str, path: Path
) -> dict[str, Any]:
    document = compile_experiment(specification, experiment_id)
    path.write_text(to_yaml(document), encoding="utf-8")
    return document
