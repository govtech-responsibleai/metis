"""The report of each experiment folder in the project folder.

An experiment id is the name of an experiment folder under
``<project folder>/experiments/execute/``. The routes find the folder among the names in that
directory, so an id can never name another path. metis-insights builds the reports. These
routes hold no report rules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from metis.api.routes.wizard import ServiceError
from metis.core import execution_layout
from metis.core.report import Report
from metis.insights import ReportBuildError, ReportFiles, ResultsMissing, ensure_report

if TYPE_CHECKING:
    from pathlib import Path

router = APIRouter(prefix="/api/v1/experiments", tags=["reports"])


def _failure(status_code: int, code: str, message: str) -> JSONResponse:
    error = ServiceError(code=code, message=message, retryable=False)
    return JSONResponse(error.model_dump(), status_code=status_code)


_RESPONSES = {
    404: {"model": ServiceError},
    409: {"model": ServiceError},
    500: {"model": ServiceError},
}


def _experiment_dir(request: Request, experiment_id: str) -> Path | JSONResponse:
    executions: Path = request.app.state.project_dir / execution_layout.EXECUTIONS
    if executions.is_dir():
        for path in executions.iterdir():
            if path.name == experiment_id and path.is_dir():
                return path
    return _failure(
        404, "experiment_not_found", f"No experiment folder is named {experiment_id!r}."
    )


def _report_files(request: Request, experiment_id: str) -> ReportFiles | JSONResponse:
    experiment_dir = _experiment_dir(request, experiment_id)
    if isinstance(experiment_dir, JSONResponse):
        return experiment_dir
    try:
        return ensure_report(experiment_dir)
    except ResultsMissing as exc:
        return _failure(
            409,
            "results_missing",
            f"{exc} Run `metis engine evaluate` on the experiment, then ask again.",
        )
    except ReportBuildError as exc:
        return _failure(409, "report_build_failed", str(exc))


@router.get(
    "/{experiment_id}/report",
    summary="Get the report of an experiment",
    response_model=Report,
    responses={200: {"content": {"application/json": {}}}, **_RESPONSES},
)
def experiment_report(experiment_id: str, request: Request) -> Response:
    """Return report.json of the experiment. The report is built when it is missing or older
    than results.json."""
    files = _report_files(request, experiment_id)
    if isinstance(files, JSONResponse):
        return files
    return Response(files.json.read_bytes(), media_type="application/json")


@router.get(
    "/{experiment_id}/report/download",
    summary="Download the HTML report of an experiment",
    response_class=Response,
    responses={
        200: {
            "content": {"text/html": {}},
            "description": "report.html of the experiment",
        },
        **_RESPONSES,
    },
)
def download_experiment_report(experiment_id: str, request: Request) -> Response:
    """Return report.html of the experiment as an attachment, the same file as
    `metis insights report` writes."""
    files = _report_files(request, experiment_id)
    if isinstance(files, JSONResponse):
        return files
    return Response(
        files.html.read_bytes(),
        media_type="text/html",
        headers={
            "Content-Disposition": f'attachment; filename="{experiment_id}-report.html"'
        },
    )


__all__ = ["router"]
