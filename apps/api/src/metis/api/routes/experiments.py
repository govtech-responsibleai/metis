"""HTTP routes for the Experiments of a Target, under `/api/v1/engine`.

An Experiment is a folder that the engine writes under `<project>/evaluations/experiments/`. Its name
is the Experiment id, `<Specification id>-<time>`. The Specification id of a Target is the Target
id, so the name of an Experiment folder gives its Target and its start time. The store keeps no
row for an Experiment. The phase and the progress come from the other engine routes.

`main.py` adds this router before the engine router, so `GET /engine/experiments` does not match
`GET /engine/{experiment_id}`.
"""

from __future__ import annotations

import shutil
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response

from metis.api.errors import RouteError
from metis.api.experiment_dirs import (
    find_experiment_dir,
    request_project_dir,
    target_experiments,
)
from metis.api.records import ExperimentList, ExperimentRecord
from metis.api.routes.targets import get_store
from metis.api.routes.wizard import ServiceError
from metis.api.store import Store  # noqa: TC001  (FastAPI resolves Depends at runtime)

router = APIRouter(prefix="/api/v1/engine", tags=["engine"])

_ERRORS: dict[int | str, dict[str, object]] = {
    400: {"model": ServiceError},
    404: {"model": ServiceError},
    422: {"model": ServiceError},
    500: {"model": ServiceError},
}


@router.get(
    "/experiments",
    summary="List the Experiments of a Target",
    response_model=ExperimentList,
    responses=_ERRORS,
)
def list_experiments(
    target_id: Annotated[str, Query(description="The Target of the Experiments.")],
    request: Request,
    store: Annotated[Store, Depends(get_store)],
) -> ExperimentList:
    """Return the Experiments of the Target, newest first, from the names of its Experiment folders."""
    store.require_target(target_id)
    return ExperimentList(
        experiments=[
            ExperimentRecord(
                experiment_id=experiment_id, target_id=target_id, started_at=started_at
            )
            for experiment_id, started_at in target_experiments(
                request_project_dir(request), target_id
            )
        ]
    )


@router.delete(
    "/{experiment_id}",
    summary="Delete an Experiment",
    status_code=204,
    responses={**_ERRORS, 409: {"model": ServiceError}},
)
def delete_experiment(experiment_id: str, request: Request) -> Response:
    """Delete the Experiment folder, with its results and its report.

    A run of the Experiment that is alive or queued gives 409 `run_in_progress`. Stop it first.
    """
    project_dir = request_project_dir(request)
    experiment_dir = find_experiment_dir(project_dir, experiment_id)
    if request.app.state.engine_runs.current(project_dir, experiment_id) is not None:
        raise RouteError(
            409,
            "run_in_progress",
            f"The experiment {experiment_id!r} runs now. Stop the run, then delete it.",
        )
    shutil.rmtree(experiment_dir)
    return Response(status_code=204)


__all__ = ["router"]
