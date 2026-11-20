"""Save and load Targets, Interviews, Specifications, and Experiments.

A saved record has two parts: rows in a database and files in a project folder. `Store` writes
the two parts together. The routes call `Store`, and they do not use the database or the files
themselves.

Where the records are
---------------------

The rows are in a database that SQLAlchemy opens from a URL. The default is the SQLite file
`evaluations/metis.db` in the project folder of the server. The tables use only portable SQL, so
a PostgreSQL URL also works.

The files of a Target are in two folders with the Target id as their name, in the layout that
`metis wizard init` writes:

- `<project>/evaluations/interviews/<target_id>/` holds the Interview.
  `interview_state.json` holds its state. `metis wizard resume` reads and writes the same file.
  The Interview row holds the other parts of the web record: the transcript, the times, and the
  file references. `documents/` holds the files of the Interview record, by name. The user
  uploads these files: the documents of the Interview, the files for the Test Cases, and the
  files of an answer that the wizard has not accepted yet. The wizard CLI keeps its opening
  documents in the same folder.
- `<project>/evaluations/specifications/<target_id>/` is the input folder of the
  Specification. Give it to `metis engine simulate --input-dir`. It holds `specification.yaml`,
  `fixtures/`, and `target-binding.yaml` when the Interview has a target connection.

An Experiment is a folder that the engine writes under `<project>/evaluations/experiments/`. The
engine copies the input folder into each Experiment folder, so a new Specification does not
change an earlier Experiment.

Who owns a record
-----------------

Each Target belongs to one user account. Its Interview, its Specification, and its Experiments
belong to that user account through the Target. A `Store` object works for one user account: it
reads and writes only the Targets of that user account, and `<project>` is the project folder of
that user account.

- With login off, the user account is the local user account, and `<project>` is the project
  folder of the server.
- With login on, the user account is the one of the request, and `<project>` is
  `users/<user id>/` in the project folder of the server.

How a save works
----------------

A save puts the new files and the state file in place, then saves the rows, then deletes the
files that the record no longer refers to. Thus a saved record always has all its files. A save
that stops before its last step can leave a file that no record refers to. The next save of
that Interview deletes it.

A save writes each upload under a temporary name first, so a read never gets a part of a file.
An upload with the name of a file in the folder moves that file to a backup name, then takes the
name. A save that fails puts each backup back. Thus it changes no file of the saved record.

Each save of a done Interview writes the Specification row and the Specification folder again. A
save of an Interview that is not done keeps the last Specification.
"""

from __future__ import annotations

import copy
import hashlib
import json
import mimetypes
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

from metis.api import input_folder
from metis.api.records import (
    EXPERIMENT_ID,
    TARGET_ID,
    ExperimentRecord,
    ExperimentSave,
    FileRef,
    InterviewRecord,
    SpecificationRecord,
    TargetList,
    TargetProblem,
    TargetSummary,
    file_name_identity,
    record_problem,
)
from metis.api.tables import (
    admins,
    experiments,
    interviews,
    login_sessions,
    metadata,
    specifications,
    targets,
    users,
)
from metis.core import project_layout
from metis.core.logging import get_logger
from metis.wizard import (
    CompilationError,
    InterviewState,
    InterviewStep,
    SpecificationError,
    derive_stage,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import BinaryIO

    from sqlalchemy import Table
    from sqlalchemy.engine import Connection, Engine, RowMapping

logger = get_logger(__name__)

DATABASE = Path(project_layout.DATABASE)
"""The default SQLite file of the store, relative to the project folder."""
INTERVIEWS = Path(project_layout.INTERVIEWS)
"""The folder of the Interview folders. `metis wizard init` writes to the same folder."""
SPECIFICATIONS = Path(project_layout.SPECIFICATIONS)
"""The folder of the Specification folders, which `metis engine simulate --input-dir` reads."""
FILES = Path("documents")
"""The folder in an Interview folder that holds the files of its Interview record."""
STATE = Path("interview_state.json")
"""The file in an Interview folder that holds the state of the Interview. The wizard CLI uses
the same file."""
USERS = Path("users")
"""The folder of the server project folder that holds the project folder of each user account,
on a server with login on."""
LOCAL_USER_ID = "local"
"""The id of the local user account. With login off, each record belongs to it."""
_USER_ID = re.compile(r"[0-9a-f]{32}")
"""The id of a user account that the store made. It is a safe folder name."""


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


def _experiment_id(experiment_id: str) -> str:
    if not EXPERIMENT_ID.fullmatch(experiment_id):
        raise _invalid("An Experiment id is the name of one Experiment folder.")
    return experiment_id


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


def user_project_dir(server_dir: Path, user_id: str) -> Path:
    """The project folder of a user account of a server with login on.

    It is `users/<user id>/` in the server project folder. The layout inside it is the layout
    of a project folder, so the engine and the reports use it as one.
    """
    if not _USER_ID.fullmatch(user_id):
        raise ValueError("A user account id is 32 hexadecimal digits.")
    return server_dir / USERS / user_id


class Store:
    """Save and load the records of one user account.

    ``user_id`` is that user account. A Target of another user account gets the same answer as
    a Target that does not exist.

    `Store(url, project_dir)` works for the local user account, which owns each record when
    login is off. ``for_user`` gives a `Store` for a different user account on the same
    database.

    A Target id is the name of the Target folder. The web app puts a random part in it, so the
    Targets of two user accounts have different ids.
    """

    def __init__(self, url: str, project_dir: Path) -> None:
        self._server_dir = project_dir.resolve()
        self.project_dir = self._server_dir
        self.user_id = LOCAL_USER_ID
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
        self._add_cli_interviews()

    def for_user(self, user_id: str) -> Store:
        """A `Store` for the user account ``user_id`` of a server with login on.

        It uses the database and the lock of this store. Its project folder is
        `users/<user id>/` in the server project folder, with the layout of a project folder
        inside.
        """
        store = copy.copy(self)
        store.user_id = user_id
        store.project_dir = user_project_dir(self._server_dir, user_id)
        return store

    @property
    def experiments_dir(self) -> Path:
        return self.project_dir / project_layout.EXPERIMENTS

    def interview_dir(self, target_id: str) -> Path:
        return self.project_dir / INTERVIEWS / _target_id(target_id)

    def target_dirs(self, target_id: str) -> tuple[Path, Path]:
        """The Interview folder and the Specification folder of a Target."""
        return self.interview_dir(target_id), self.input_dir(target_id)

    def files_dir(self, target_id: str) -> Path:
        return self.interview_dir(target_id) / FILES

    @property
    def engine(self) -> Engine:
        """The database engine. The user accounts use the same database as the records."""
        return self._engine

    def state_path(self, target_id: str) -> Path:
        return self.interview_dir(target_id) / STATE

    def input_dir(self, target_id: str) -> Path:
        return self.project_dir / SPECIFICATIONS / _target_id(target_id)

    def close(self) -> None:
        self._engine.dispose()

    def list_targets(self) -> TargetList:
        self._add_cli_interviews()
        query = (
            select(targets.c.id, interviews.c.record, interviews.c.updated_at)
            .join(targets, interviews.c.target_id == targets.c.id)
            .where(targets.c.user_id == self.user_id)
            .order_by(interviews.c.updated_at.desc())
        )
        summaries: list[TargetSummary] = []
        problems: list[TargetProblem] = []
        with self._engine.connect() as connection:
            for row in connection.execute(query):
                message = record_problem(self._with_state(row.id, row.record))
                if message is not None:
                    problems.append(TargetProblem(id=row.id, message=message))
                    continue
                summaries.append(
                    TargetSummary(
                        id=row.id,
                        title=str(row.record["title"]),
                        updated_at=_utc(row.updated_at),
                    )
                )
        return TargetList(targets=summaries, problems=problems)

    def read_interview(self, target_id: str) -> InterviewRecord:
        raw = self._saved_record(_target_id(target_id))
        if raw is None:
            raise _not_found(f"The store has no Target {target_id}.")
        raw = self._with_state(target_id, raw)
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
        """Save one complete record and its new files. A done Interview also writes its Specification.

        When the store refuses the record, the Specification does not compile, or the rows do not
        commit, the rows and the files stay as they were.
        """
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
        state_path = self.state_path(target_id)
        package = self.input_dir(target_id)
        state = record.state
        done = derive_stage(state) == InterviewStep.DONE and state.pending is None

        with self._lock:
            first_save = self._check_owner(target_id, record)
            input_folder.recover(package)
            for name in references - uploaded.keys():
                if not (directory / name).is_file():
                    raise _invalid(f"The file {name} was not uploaded.")
            written: list[Path] = []
            staged: dict[Path, Path] = {}
            backups: dict[Path, Path] = {}
            specification: Path | None = None
            try:
                if uploaded:
                    directory.mkdir(parents=True, exist_ok=True)
                for name, upload in uploaded.items():
                    temporary = directory / f".{uuid.uuid4().hex}.part"
                    written.append(temporary)
                    with temporary.open("xb") as stream:
                        shutil.copyfileobj(upload.stream, stream)
                    staged[directory / name] = temporary
                state_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = state_path.with_name(f".{uuid.uuid4().hex}.part")
                written.append(temporary)
                temporary.write_text(state.model_dump_json(), encoding="utf-8")
                staged[state_path] = temporary
                # Each file is in place before the record refers to it. A file that is already
                # in the folder moves to a backup name first, so a failure can put it back.
                for path, temporary in staged.items():
                    if os.path.lexists(path):
                        backup = path.with_name(f".{uuid.uuid4().hex}.old")
                        path.replace(backup)
                        backups[path] = backup
                    written.append(path)
                    temporary.replace(path)
                files = self._specification_files(record, directory) if done else None
                if files is not None:
                    specification = input_folder.stage(package, files)
                self._save_rows(target_id, record, files)
            except BaseException:
                if specification is not None:
                    shutil.rmtree(specification, ignore_errors=True)
                if first_save:
                    # No record owns these folders, so a later save would get `target_exists`.
                    for folder in self.target_dirs(target_id):
                        shutil.rmtree(folder, ignore_errors=True)
                else:
                    for path in written:
                        path.unlink(missing_ok=True)
                    for path, backup in backups.items():
                        backup.replace(path)
                raise
            if specification is not None:
                input_folder.swap(package, specification)
            if state_path in backups:
                backups[state_path].unlink(missing_ok=True)
            # The backups of the fixture folder are files that the record does not refer to.
            keep = {file_name_identity(name) for name in references}
            for path in directory.iterdir() if directory.is_dir() else ():
                if path.is_file() and file_name_identity(path.name) not in keep:
                    path.unlink(missing_ok=True)

    def delete_target(self, target_id: str) -> None:
        """Delete the rows of the Target, its Interview folder, and its Specification folder.

        The Experiment folders in `evaluations/experiments/` stay on disk.
        """
        target_id = _target_id(target_id)
        with self._lock:
            with self._engine.begin() as connection:
                owned = self._owns(connection, target_id)
                if owned:
                    for table in (experiments, specifications, interviews):
                        connection.execute(
                            delete(table).where(table.c.target_id == target_id)
                        )
                    connection.execute(delete(targets).where(targets.c.id == target_id))
            if not owned:
                raise _not_found(f"The store has no Target {target_id}.")
            for folder in self.target_dirs(target_id):
                shutil.rmtree(folder, ignore_errors=True)

    def delete_user_account(self, user_id: str) -> None:
        """Delete a user account with its login sessions and its records, then its folder.

        One transaction deletes the rows of the user account: its login sessions, its admin
        row, the Experiment, Specification, and Interview rows of its Targets, its Targets, and
        its ``users`` row. Then the store deletes `users/<user id>/` in the server project
        folder. A folder that the store cannot delete is logged, and the rows stay deleted.

        The store lock covers the full delete, so it does not mix with a save of that user
        account. An unknown ``user_id`` changes no row.

        :raises ValueError: When ``user_id`` is not the id of a user account that the store
            made, for example the local user account.
        """
        folder = user_project_dir(self._server_dir, user_id)
        owned = select(targets.c.id).where(targets.c.user_id == user_id)
        with self._lock:
            with self._engine.begin() as connection:
                for table in (experiments, specifications, interviews):
                    connection.execute(
                        delete(table).where(table.c.target_id.in_(owned))
                    )
                connection.execute(delete(targets).where(targets.c.user_id == user_id))
                for table in (login_sessions, admins):
                    connection.execute(delete(table).where(table.c.user_id == user_id))
                connection.execute(delete(users).where(users.c.id == user_id))
            try:
                shutil.rmtree(folder)
            except FileNotFoundError:
                pass
            except OSError as exc:
                logger.warning(
                    "user_folder_not_deleted",
                    user_id=user_id,
                    error_type=type(exc).__name__,
                )

    # Specifications.

    def read_specification(self, target_id: str) -> SpecificationRecord:
        with self._lock:
            package = self.input_dir(target_id)
            input_folder.recover(package)
            document = package / input_folder.SPECIFICATION
            with self._engine.connect() as connection:
                owned = self._owns(connection, target_id)
                row = (
                    None
                    if not owned
                    else connection.execute(
                        select(specifications).where(
                            specifications.c.target_id == target_id
                        )
                    ).first()
                )
            if (
                row is None
                or not document.is_file()
                or hashlib.sha256(document.read_bytes()).hexdigest() != row.sha256
            ):
                record = self.read_interview(target_id)
                if (
                    not owned
                    or derive_stage(record.state) != InterviewStep.DONE
                    or record.state.pending is not None
                ):
                    raise _not_found(
                        "The Target has no Specification. Finish the Interview."
                    )
                files = self._specification_files(record, self.files_dir(target_id))
                staged = input_folder.stage(self.input_dir(target_id), files)
                try:
                    with self._engine.begin() as connection:
                        self._save_specification(
                            connection, target_id, files, datetime.now(UTC)
                        )
                except BaseException:
                    shutil.rmtree(staged, ignore_errors=True)
                    raise
                input_folder.swap(self.input_dir(target_id), staged)
                with self._engine.connect() as connection:
                    row = connection.execute(
                        select(specifications).where(
                            specifications.c.target_id == target_id
                        )
                    ).one()
        return SpecificationRecord(
            target_id=target_id,
            specification_yaml=row.specification_yaml,
            sha256=row.sha256,
            input_dir=self.input_dir(target_id)
            .relative_to(self.project_dir)
            .as_posix(),
            updated_at=_utc(row.updated_at),
        )

    # Experiments.

    def list_experiments(self, target_id: str) -> list[ExperimentRecord]:
        self._require_target(target_id)
        query = (
            self._experiment_rows()
            .where(targets.c.id == target_id)
            .order_by(experiments.c.started_at.desc())
        )
        with self._engine.connect() as connection:
            return [_experiment(row._mapping) for row in connection.execute(query)]

    def read_experiment(self, experiment_id: str) -> ExperimentRecord:
        query = self._experiment_rows().where(
            experiments.c.experiment_id == _experiment_id(experiment_id)
        )
        with self._engine.connect() as connection:
            row = connection.execute(query).first()
        if row is None:
            raise _not_found(f"The store has no Experiment {experiment_id}.")
        return _experiment(row._mapping)

    def put_experiment(
        self, experiment_id: str, body: ExperimentSave
    ) -> ExperimentRecord:
        """Save the last step of an Experiment. The first save checks the Experiment folder."""
        folder = self.experiments_dir / _experiment_id(experiment_id)
        target_id = _target_id(body.target_id)
        with self._lock, self._engine.begin() as connection:
            owned = self._owns(connection, target_id)
            if not owned:
                raise _not_found(f"The store has no Target {target_id}.")
            row = connection.execute(
                self._experiment_rows().where(
                    experiments.c.experiment_id == experiment_id
                )
            ).first()
            if row is None:
                if not folder.is_dir():
                    raise _invalid(
                        f"The Experiment folder {project_layout.EXPERIMENTS / experiment_id} "
                        "does not exist."
                    )
                connection.execute(
                    insert(experiments).values(
                        target_id=target_id,
                        experiment_id=experiment_id,
                        started_at=datetime.now(UTC),
                        step=body.step.value,
                    )
                )
            elif row.target_id != target_id:
                raise _invalid(
                    f"The Experiment {experiment_id} belongs to another Target."
                )
            else:
                connection.execute(
                    update(experiments)
                    .where(
                        experiments.c.target_id == target_id,
                        experiments.c.experiment_id == experiment_id,
                    )
                    .values(step=body.step.value)
                )
        return self.read_experiment(experiment_id)

    def delete_experiment(self, experiment_id: str) -> None:
        """Delete the row of an Experiment. The Experiment folder stays on disk."""
        own = select(targets.c.id).where(targets.c.user_id == self.user_id)
        with self._engine.begin() as connection:
            connection.execute(
                delete(experiments).where(
                    experiments.c.experiment_id == _experiment_id(experiment_id),
                    experiments.c.target_id.in_(own),
                )
            )

    # Internals.

    def _add_cli_interviews(self) -> None:
        """Add rows for the Interview folders of the wizard CLI that have no row.

        A folder is an Interview of the CLI when it has a state file that validates. The row
        gets no transcript, because the CLI keeps none. Its file references are the files in
        the document folder. The times are the last change of the state file.
        """
        interviews_dir = self.project_dir / INTERVIEWS
        if not interviews_dir.is_dir():
            return
        with self._lock:
            with self._engine.connect() as connection:
                # The ids of all user accounts, because a Target id is the key of the table.
                known = set(connection.execute(select(targets.c.id)).scalars())
            for folder in sorted(interviews_dir.iterdir()):
                target_id = folder.name
                if target_id in known or not TARGET_ID.fullmatch(target_id):
                    continue
                path = self.state_path(target_id)
                try:
                    state = InterviewState.model_validate_json(
                        path.read_text(encoding="utf-8")
                    )
                    changed = path.stat().st_mtime
                except (OSError, ValueError):
                    continue
                record = InterviewRecord(
                    id=target_id,
                    title=state.specification.target.name.strip()
                    or "Untitled Interview",
                    stage=(state.pending and state.pending.stage)
                    or derive_stage(state),
                    created_at=round(changed * 1000),
                    updated_at=round(changed * 1000),
                    state=state,
                    transcript=[],
                    fixtures=self._document_refs(target_id),
                )
                self._save_rows(
                    target_id, record, None, datetime.fromtimestamp(changed, UTC)
                )

    def _document_refs(self, target_id: str) -> list[FileRef]:
        """A reference for each file in the document folder that a record can name."""
        directory = self.files_dir(target_id)
        refs: dict[str, FileRef] = {}
        for path in sorted(directory.iterdir()) if directory.is_dir() else ():
            if not path.is_file() or path.name.startswith("."):
                continue
            try:
                name = safe_name(path.name)
            except StoreError:
                continue
            refs.setdefault(
                file_name_identity(name),
                FileRef(
                    name=name,
                    type=mimetypes.guess_type(name)[0] or "application/octet-stream",
                    size=path.stat().st_size,
                ),
            )
        return list(refs.values())

    def _with_state(self, target_id: str, saved: Any) -> Any:
        """The saved JSON of a row with the state from the state file of the Target.

        A state file that is missing or is not JSON gives the row as it is. Such a record does
        not validate, so the store reports it as a record that it cannot read.
        """
        if not isinstance(saved, dict) or not TARGET_ID.fullmatch(target_id):
            return saved
        try:
            state = json.loads(self.state_path(target_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return saved
        return {**saved, "state": state}

    def _require_target(self, target_id: str) -> None:
        if self._saved_record(_target_id(target_id)) is None:
            raise _not_found(f"The store has no Target {target_id}.")

    def _saved_record(self, target_id: str) -> Any:
        """The saved JSON of the row of a Target, or ``None`` when the store has no row for it."""
        query = (
            select(interviews.c.record)
            .join(targets, interviews.c.target_id == targets.c.id)
            .where(targets.c.user_id == self.user_id, targets.c.id == target_id)
        )
        with self._engine.connect() as connection:
            return connection.execute(query).scalar_one_or_none()

    def _owns(self, connection: Connection, target_id: str) -> bool:
        """Whether this user account has the Target.

        This is the one place that finds a Target for a request. A Target of another user
        account gives ``False``, as a Target that does not exist.
        """
        return (
            connection.execute(
                select(targets.c.id).where(
                    targets.c.user_id == self.user_id, targets.c.id == target_id
                )
            ).first()
            is not None
        )

    def _experiment_rows(self) -> Any:
        """The Experiment rows of this user account."""
        return (
            select(
                experiments.c.experiment_id,
                experiments.c.target_id,
                experiments.c.started_at,
                experiments.c.step,
            )
            .join(targets, experiments.c.target_id == targets.c.id)
            .where(targets.c.user_id == self.user_id)
        )

    def _check_owner(self, target_id: str, record: InterviewRecord) -> bool:
        """Return whether this is the first save. Refuse an id that something else uses.

        The `created_at` of a record tells one Interview from another. An Interview folder or a
        Specification folder with no row has no Interview state that the store can read, and the
        store does not write in it.
        """
        saved = self._saved_record(target_id)
        if saved is None:
            with self._engine.connect() as connection:
                taken = connection.execute(
                    select(targets.c.id).where(targets.c.id == target_id)
                ).first()
            if taken is not None:
                # The Target of another user account. The answer does not show its record.
                raise _exists(
                    f"Another Interview already uses the Target id {target_id}."
                )
            if any(os.path.lexists(folder) for folder in self.target_dirs(target_id)):
                raise _exists(f"A folder already uses the Target id {target_id}.")
            return True
        if not isinstance(saved, dict) or saved.get("created_at") != record.created_at:
            raise _exists(f"Another Interview already uses the Target id {target_id}.")
        return False

    def _save_rows(
        self,
        target_id: str,
        record: InterviewRecord,
        specification: Mapping[str, bytes] | None,
        now: datetime | None = None,
    ) -> None:
        """Write the Target, Interview, and Specification rows in one transaction."""
        now = now or datetime.now(UTC)
        name = record.state.specification.target.name
        with self._engine.begin() as connection:
            owned = self._owns(connection, target_id)
            if not owned:
                self._add_local_user(connection, now)
                connection.execute(
                    insert(targets).values(
                        id=target_id,
                        user_id=self.user_id,
                        name=name,
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                connection.execute(
                    update(targets)
                    .where(targets.c.id == target_id)
                    .values(name=name, updated_at=now)
                )
            _upsert(
                connection,
                interviews,
                interviews.c.target_id == target_id,
                {"record": record.web_parts(), "updated_at": now},
                {"target_id": target_id},
            )
            if specification is not None:
                self._save_specification(connection, target_id, specification, now)

    def _add_local_user(self, connection: Connection, now: datetime) -> None:
        """Add the row of the local user account before its first Target.

        The local user account has no password hash, so no person can log in to it.
        """
        if self.user_id != LOCAL_USER_ID:
            return
        known = connection.execute(
            select(users.c.id).where(users.c.id == LOCAL_USER_ID)
        ).first()
        if known is None:
            connection.execute(
                insert(users).values(
                    id=LOCAL_USER_ID,
                    username=LOCAL_USER_ID,
                    password_hash=None,
                    created_at=now,
                )
            )

    @staticmethod
    def _save_specification(
        connection: Connection,
        target_id: str,
        files: Mapping[str, bytes],
        updated_at: datetime,
    ) -> None:
        text = files[input_folder.SPECIFICATION]
        _upsert(
            connection,
            specifications,
            specifications.c.target_id == target_id,
            {
                "specification_yaml": text.decode("utf-8"),
                "sha256": hashlib.sha256(text).hexdigest(),
                "updated_at": updated_at,
            },
            {"target_id": target_id},
        )

    @staticmethod
    def _specification_files(
        record: InterviewRecord, directory: Path
    ) -> dict[str, bytes]:
        """Package the Specification and return the files of its input folder, by path."""
        state = record.state
        excluded = set(state.excluded_tasks)
        referenced = {
            name
            for task in state.specification.tasks
            if task.id not in excluded
            for name in task.fixtures
        }
        fixtures = [
            (ref.name, (directory / ref.name).read_bytes())
            for ref in record.fixtures
            if ref.name in referenced
        ]
        try:
            return input_folder.build(state, fixtures)
        except (CompilationError, SpecificationError) as exc:
            raise StoreError(400, "compilation_failed", str(exc)) from exc


def _upsert(
    connection: Connection,
    table: Table,
    where: Any,
    values: Mapping[str, Any],
    keys: Mapping[str, Any],
) -> None:
    """Update the row that ``where`` selects, or insert it. Portable to any database."""
    if connection.execute(update(table).where(where).values(**values)).rowcount == 0:
        connection.execute(insert(table).values(**keys, **values))


def _experiment(row: RowMapping) -> ExperimentRecord:
    return ExperimentRecord(
        experiment_id=row["experiment_id"],
        target_id=row["target_id"],
        started_at=_utc(row["started_at"]),
        step=row["step"],
    )


__all__ = [
    "Store",
    "StoreError",
    "StoredFile",
    "Upload",
    "safe_name",
    "user_project_dir",
    "DATABASE",
    "FILES",
    "INTERVIEWS",
    "LOCAL_USER_ID",
    "SPECIFICATIONS",
    "STATE",
    "USERS",
]
