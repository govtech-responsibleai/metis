"""The report of each experiment folder in the project folder.

An experiment id is the name of an experiment folder under
``<project folder>/evaluations/experiments/``, the project folder of the user account when login
is on. The routes find the folder with ``find_experiment_dir``, so an id can never name another
path. metis-insights builds the reports. These routes hold no report rules.

``/report`` returns report.json and ``/report.html`` returns report.html. Both are the same
report, and both responses are inline. A client that wants a file saves the response.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from metis.api.experiment_dirs import find_experiment_dir, request_project_dir
from metis.api.routes.wizard import ServiceError
from metis.core.report import Report
from metis.insights import ReportBuildError, ReportFiles, ResultsMissing, ensure_report

router = APIRouter(prefix="/api/v1/experiments", tags=["reports"])


def _failure(status_code: int, code: str, message: str) -> JSONResponse:
    error = ServiceError(code=code, message=message, retryable=False)
    return JSONResponse(error.model_dump(), status_code=status_code)


_RESPONSES = {
    404: {"model": ServiceError},
    409: {"model": ServiceError},
    500: {"model": ServiceError},
}


def _report_files(request: Request, experiment_id: str) -> ReportFiles | JSONResponse:
    experiment_dir = find_experiment_dir(request_project_dir(request), experiment_id)
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


def _inline(filename: str) -> str:
    """Name the file for a client that saves the response (RFC 6266).

    ``filename`` holds an ASCII fallback, because Starlette encodes headers as latin-1 and a
    quote would end the value. ``filename*`` holds the exact name.
    """
    fallback = "".join(
        char if char.isascii() and char.isprintable() and char not in '"\\' else "_"
        for char in filename
    )
    return (
        f"inline; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"
    )


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
    return Response(
        files.json.read_bytes(),
        media_type="application/json",
        headers={"Content-Disposition": _inline(f"{experiment_id}-report.json")},
    )


@router.get(
    "/{experiment_id}/report.html",
    summary="Get the HTML report page of an experiment",
    response_class=Response,
    responses={
        200: {
            "content": {"text/html": {}},
            "description": "report.html of the experiment",
        },
        **_RESPONSES,
    },
)
def experiment_report_page(experiment_id: str, request: Request) -> Response:
    """Return report.html of the experiment, the same page as `metis insights report` writes.
    The report is built when it is missing or older than results.json."""
    files = _report_files(request, experiment_id)
    if isinstance(files, JSONResponse):
        return files
    return Response(
        files.html.read_bytes(),
        media_type="text/html",
        headers={"Content-Disposition": _inline(f"{experiment_id}-report.html")},
    )


__all__ = ["router"]
