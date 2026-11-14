"""HTTP routes for the Targets in the store: the Interview and its files.

An Interview save is a multipart request. The `record` part is the record as a JSON file, so
that the size limit of a text field does not apply to it. Each file that the store does not have
yet is one part in the `files` field, and the filename of the part is the name in the record.
"""

from __future__ import annotations

from contextlib import suppress
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError

from metis.api.records import InterviewRecord, TargetList
from metis.api.routes.wizard import ServiceError
from metis.api.store import Store, Upload

router = APIRouter(prefix="/api/v1/targets", tags=["targets"])

_ERRORS: dict[int | str, dict[str, object]] = {
    400: {"model": ServiceError},
    404: {"model": ServiceError},
    422: {"model": ServiceError},
    500: {"model": ServiceError},
}


def get_store(request: Request) -> Store:
    """Return the store that the app composed at startup."""
    store: Store | None = getattr(request.app.state, "store", None)
    if store is None:
        raise RuntimeError("The store was not composed at application startup.")
    return store


@router.get("", summary="List the Targets", response_model=TargetList)
def list_targets(store: Annotated[Store, Depends(get_store)]) -> TargetList:
    """Return the Targets, newest first. A row that this version cannot read is a problem."""
    return store.list_targets()


@router.delete(
    "/{target_id}",
    summary="Delete a Target",
    status_code=204,
    responses=_ERRORS,
)
def delete_target(
    target_id: str, store: Annotated[Store, Depends(get_store)]
) -> Response:
    """Delete the saved Interview and its uploaded files."""
    store.delete_target(target_id)
    return Response(status_code=204)


@router.get(
    "/{target_id}/interview",
    summary="Read the Interview of a Target",
    response_model=InterviewRecord,
    responses={**_ERRORS, 409: {"model": ServiceError}},
)
def read_interview(
    target_id: str, store: Annotated[Store, Depends(get_store)]
) -> JSONResponse:
    """Return the record with its file references. Read each file from the files route."""
    return JSONResponse(store.read_interview(target_id).to_json())


@router.put(
    "/{target_id}/interview",
    summary="Save the Interview of a Target",
    status_code=204,
    responses={**_ERRORS, 409: {"model": ServiceError}},
)
def put_interview(
    target_id: str,
    record: Annotated[UploadFile, File()],
    store: Annotated[Store, Depends(get_store)],
    files: Annotated[list[UploadFile] | None, File()] = None,
) -> Response:
    """Save the record and the files that the store does not have yet.

    The first save creates the Target. The `created_at` of the record tells one Interview from
    another. Send the record as a file part that contains its JSON. When another Interview
    already uses the id, the save gives 409 `target_exists` and changes nothing. Send each new
    file as a part in the `files` field, with its record name as the filename. A fixture and a
    file of a waiting answer are both files of the record. A reference to a file that is neither
    in this request nor in the store gives 400. The store deletes the files of the Target that
    the record no longer refers to.

    The save keeps the complete Interview state. Compile and package are separate requests.
    """
    parts = [Upload(name=part.filename or "", stream=part.file) for part in files or []]
    try:
        parsed = InterviewRecord.model_validate_json(record.file.read())
        store.put_interview(target_id, parsed, parts)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors(include_input=False)) from None
    finally:
        for upload in [record, *(files or [])]:
            with suppress(OSError):
                upload.file.close()
    return Response(status_code=204)


@router.get(
    "/{target_id}/interview/files/{name}",
    summary="Read one file of an Interview",
    response_class=Response,
    responses={
        200: {"content": {"application/octet-stream": {}}},
        **_ERRORS,
        409: {"model": ServiceError},
    },
)
def read_interview_file(
    target_id: str,
    name: str,
    store: Annotated[Store, Depends(get_store)],
) -> Response:
    """Return a file that the record refers to, as a download.

    A client wrote the bytes and the type. The response is an attachment with `nosniff`, so a
    browser that opens the address does not show the file as a page of this origin. A later save
    can put other bytes under the same name, so a browser must not keep a copy.
    """
    stored = store.interview_file(target_id, name)
    return FileResponse(
        stored.path,
        media_type=stored.media_type,
        filename=name,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
    )


__all__ = ["get_store", "router"]
