"""Save Interview records in SQL and their uploaded files on server disk.

The default database is `<project>/experiments/metis.db`. Each Interview keeps its
Specification, Target details, and transcript in one JSON record. Its uploaded files stay in
`experiments/design/<target_id>/inputs/fixtures/`.

A save puts the new files in place, then saves the record, then deletes the files that the record
no longer refers to. Thus a saved record always has all its files. A save that stops before its
last step can leave a file that no record refers to. The next save of that Interview deletes it.

A save writes each upload under a temporary name first, so a read never gets a part of a file.
An upload with the name of a file in the folder moves that file to a backup name, then takes the
name. A save that fails puts each backup back. Thus it changes no file of the saved record.
"""

from __future__ import annotations

import os
import re
import shutil
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError
from sqlalchemy import create_engine, delete, insert, select, update
from sqlalchemy.engine import make_url

from metis.api.records import (
    TARGET_ID,
    InterviewRecord,
    TargetList,
    TargetProblem,
    TargetSummary,
    file_name_identity,
    record_problem,
)
from metis.api.tables import interviews, metadata
from metis.core import execution_layout

if TYPE_CHECKING:
    from typing import BinaryIO

EXPERIMENTS = execution_layout.EXECUTIONS.parent
"""The project folder that holds the database and the saved Interview folders."""
DATABASE = EXPERIMENTS / "metis.db"
"""The default SQLite file of the store, relative to the project folder."""
DESIGN = EXPERIMENTS / "design"
"""The folder of the Target folders. `metis wizard init` writes to the same folder."""
FILES = Path("inputs") / "fixtures"
"""The folder of a Target that holds the files of its Interview record."""


class StoreError(Exception):
    """A store request that the store refuses. The app maps it to the service error shape."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _not_found(message: str) -> StoreError:
    return StoreError(404, "not_found", message)


def _invalid(message: str) -> StoreError:
    return StoreError(400, "validation_error", message)


def _exists(message: str) -> StoreError:
    return StoreError(409, "target_exists", message)


_NOT_PORTABLE = re.compile(r'[\\/\x00-\x1f\x7f-\x9f<>:"|?*]|[. ]$')
"""A character or an ending that some file system refuses in a file name."""
_DEVICE = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", re.IGNORECASE)
"""A name before the first dot that Windows keeps for a device."""


def safe_name(name: str) -> str:
    """Return ``name`` when it is one portable path segment, else raise a 400 `StoreError`.

    The rule is the file name rule of the web app, so each name of a record is a name that
    every file system can hold and that a browser sends unchanged in a form part.
    """
    if not name or name in (".", "..") or _NOT_PORTABLE.search(name):
        raise _invalid("A file name must be a portable name without a path.")
    if _DEVICE.fullmatch(name.split(".", 1)[0]):
        raise _invalid("A file name cannot be a reserved device name.")
    return name


_MEDIA_TYPE = re.compile(
    r"[\w!#$&^.+-]+/[\w!#$&^.+-]+(?: ?; ?[\w-]+=[\w.+-]+)*", re.ASCII
)
"""A media type that is safe to write in a response header."""


def _media_type(value: str) -> str:
    """Return the type that a client wrote in a record, when a header can hold it."""
    return value if _MEDIA_TYPE.fullmatch(value) else "application/octet-stream"


def _target_id(target_id: str) -> str:
    if not TARGET_ID.fullmatch(target_id):
        raise _invalid("A Target id has 1 to 64 letters, digits, '-' or '_'.")
    return target_id


def _utc(value: datetime) -> datetime:
    """SQLite returns a naive time. The store writes UTC, so the time is UTC."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@dataclass(frozen=True)
class Upload:
    """One file part of an Interview save."""

    name: str
    stream: BinaryIO


@dataclass(frozen=True)
class StoredFile:
    """The path of an Interview file and the type of its reference."""

    path: Path
    media_type: str


class Store:
    """The Interview records in the database and their files under the project folder."""

    def __init__(self, url: str, project_dir: Path) -> None:
        self.project_dir = project_dir.resolve()
        database = make_url(url)
        if database.get_backend_name() == "sqlite" and database.database not in (
            None,
            "",
            ":memory:",
        ):
            Path(database.database).parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(url)
        metadata.create_all(self._engine)
        # One save or delete at a time, so the owner check and the write stay together.
        self._lock = threading.Lock()

    def target_dir(self, target_id: str) -> Path:
        return self.project_dir / DESIGN / _target_id(target_id)

    def files_dir(self, target_id: str) -> Path:
        return self.target_dir(target_id) / FILES

    def close(self) -> None:
        self._engine.dispose()

    def list_targets(self) -> TargetList:
        query = select(interviews).order_by(interviews.c.updated_at.desc())
        summaries: list[TargetSummary] = []
        problems: list[TargetProblem] = []
        with self._engine.connect() as connection:
            for row in connection.execute(query):
                message = record_problem(row.record)
                if message is not None:
                    problems.append(TargetProblem(id=row.target_id, message=message))
                    continue
                summaries.append(
                    TargetSummary(
                        id=row.target_id,
                        title=str(row.record["title"]),
                        updated_at=_utc(row.updated_at),
                    )
                )
        return TargetList(targets=summaries, problems=problems)

    def read_interview(self, target_id: str) -> InterviewRecord:
        raw = self._saved_record(_target_id(target_id))
        if raw is None:
            raise _not_found(f"The store has no Target {target_id}.")
        message = record_problem(raw)
        if message is not None:
            raise StoreError(409, "unreadable_record", message)
        return InterviewRecord.model_validate(raw)

    def interview_file(self, target_id: str, name: str) -> StoredFile:
        path = self.files_dir(target_id) / safe_name(name)
        ref = self.read_interview(target_id).files().get(name)
        if ref is None or not path.is_file():
            raise _not_found(f"The Interview has no file {name}.")
        return StoredFile(path=path, media_type=_media_type(ref.type))

    def put_interview(
        self, target_id: str, record: InterviewRecord, uploads: list[Upload]
    ) -> None:
        """Save one complete record and the files that the store does not have yet."""
        target_id = _target_id(target_id)
        if record.id != target_id:
            raise _invalid("The record id must be the Target id.")
        try:
            files = record.files()
        except ValidationError as exc:
            raise _invalid("A transcript entry has an invalid file list.") from exc
        except ValueError as exc:
            raise _invalid(str(exc)) from exc
        references = {safe_name(name) for name in files}
        uploaded = {safe_name(upload.name): upload for upload in uploads}
        for name in uploaded:
            if name not in references:
                raise _invalid(f"The record has no file {name}.")
        directory = self.files_dir(target_id)

        with self._lock:
            first_save = self._check_owner(target_id, record)
            for name in references - uploaded.keys():
                if not (directory / name).is_file():
                    raise _invalid(f"The file {name} was not uploaded.")
            written: list[Path] = []
            staged: dict[Path, Path] = {}
            backups: dict[Path, Path] = {}
            try:
                if uploaded:
                    directory.mkdir(parents=True, exist_ok=True)
                for name, upload in uploaded.items():
                    temporary = directory / f".{uuid.uuid4().hex}.part"
                    written.append(temporary)
                    with temporary.open("xb") as stream:
                        shutil.copyfileobj(upload.stream, stream)
                    staged[directory / name] = temporary
                # Each file is in place before the record refers to it. A file that is already
                # in the folder moves to a backup name first, so a failure can put it back.
                for path, temporary in staged.items():
                    if os.path.lexists(path):
                        backup = directory / f".{uuid.uuid4().hex}.old"
                        path.replace(backup)
                        backups[path] = backup
                    written.append(path)
                    temporary.replace(path)
                self._save_record(target_id, record)
            except BaseException:
                if first_save:
                    # No record owns this folder, so a later save would get `target_exists`.
                    shutil.rmtree(self.target_dir(target_id), ignore_errors=True)
                else:
                    for path in written:
                        path.unlink(missing_ok=True)
                    for path, backup in backups.items():
                        backup.replace(path)
                raise
            # The backups are files that the record does not refer to.
            keep = {file_name_identity(name) for name in references}
            for path in directory.iterdir() if directory.is_dir() else ():
                if path.is_file() and file_name_identity(path.name) not in keep:
                    path.unlink(missing_ok=True)

    def delete_target(self, target_id: str) -> None:
        """Delete a saved Interview and its folder."""
        target_id = _target_id(target_id)
        with self._lock:
            with self._engine.begin() as connection:
                deleted = connection.execute(
                    delete(interviews).where(interviews.c.target_id == target_id)
                ).rowcount
            if not deleted:
                raise _not_found(f"The store has no Target {target_id}.")
            shutil.rmtree(self.target_dir(target_id), ignore_errors=True)

    def _saved_record(self, target_id: str) -> Any:
        """The saved JSON of a Target, or ``None`` when the store has no row for it."""
        query = select(interviews.c.record).where(interviews.c.target_id == target_id)
        with self._engine.connect() as connection:
            return connection.execute(query).scalar_one_or_none()

    def _check_owner(self, target_id: str, record: InterviewRecord) -> bool:
        """Return whether this is the first save. Refuse an id that something else uses.

        The `created_at` of a record tells one Interview from another. A folder with no row is
        a folder of the CLI, and the store does not write in it.
        """
        saved = self._saved_record(target_id)
        if saved is None:
            if os.path.lexists(self.target_dir(target_id)):
                raise _exists(f"A folder already uses the Target id {target_id}.")
            return True
        if not isinstance(saved, dict) or saved.get("created_at") != record.created_at:
            raise _exists(f"Another Interview already uses the Target id {target_id}.")
        return False

    def _save_record(self, target_id: str, record: InterviewRecord) -> None:
        """Update the row of the Target, or insert it. Portable to any database."""
        values = {"record": record.to_json(), "updated_at": datetime.now(UTC)}
        where = interviews.c.target_id == target_id
        with self._engine.begin() as connection:
            updated = connection.execute(update(interviews).where(where).values(values))
            if updated.rowcount == 0:
                connection.execute(
                    insert(interviews).values(target_id=target_id, **values)
                )


__all__ = [
    "DATABASE",
    "DESIGN",
    "EXPERIMENTS",
    "FILES",
    "Store",
    "StoreError",
    "StoredFile",
    "Upload",
    "safe_name",
]
