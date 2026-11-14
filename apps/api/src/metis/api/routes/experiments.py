"""HTTP routes for the Experiment rows in the store.

An Experiment is a folder that the engine writes under `<project>/experiments/execute/`. Its name
is the Experiment id. The row keeps the Target, the start time, and the last engine step that the
web app started. The phase and the progress of an Experiment come from the Experiment folder.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from metis.api.records import ExperimentRecord, ExperimentSave
from metis.api.routes.targets import get_store
from metis.api.routes.wizard import ServiceError
from metis.api.store import Store  # noqa: TC001  (FastAPI resolves Depends at runtime)

router = APIRouter(prefix="/api/v1/experiments", tags=["experiments"])

_ERRORS: dict[int | str, dict[str, object]] = {
    400: {"model": ServiceError},
    404: {"model": ServiceError},
    422: {"model": ServiceError},
    500: {"model": ServiceError},
}


@router.get(
    "/{experiment_id}",
    summary="Read an Experiment",
    response_model=ExperimentRecord,
    responses=_ERRORS,
)
def read_experiment(
    experiment_id: str, store: Annotated[Store, Depends(get_store)]
) -> ExperimentRecord:
    """Return the row of the Experiment."""
    return store.read_experiment(experiment_id)


@router.put(
    "/{experiment_id}",
    summary="Save an Experiment",
    response_model=ExperimentRecord,
    responses=_ERRORS,
)
def put_experiment(
    experiment_id: str,
    body: ExperimentSave,
    store: Annotated[Store, Depends(get_store)],
) -> ExperimentRecord:
    """Save the last engine step that the web app started for the Experiment.

    The Experiment folder must exist under `experiments/execute/`, else the route gives 400. The
    first save keeps the start time.
    """
    return store.put_experiment(experiment_id, body)


@router.delete(
    "/{experiment_id}",
    summary="Delete an Experiment",
    status_code=204,
    responses=_ERRORS,
)
def delete_experiment(
    experiment_id: str, store: Annotated[Store, Depends(get_store)]
) -> Response:
    """Delete the row of the Experiment. The Experiment folder stays on disk."""
    store.delete_experiment(experiment_id)
    return Response(status_code=204)


__all__ = ["router"]
