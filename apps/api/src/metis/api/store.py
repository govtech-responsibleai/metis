"""The store of Targets, Interviews, Specifications, and Experiments.

The store keeps its rows in a database that SQLAlchemy opens from a URL. The default is the
SQLite file `<project>/experiments/metis.db`. The tables use only portable SQL, so a PostgreSQL
URL also works.

The store keeps the files of each Target in the layout that `metis wizard init` writes, under
`<project>/experiments/design/<target_id>/`:

- `inputs/fixtures/` holds the files of the Interview record, by name. The user uploads these
  files: the fixtures of the Interview, and the files of an answer that the wizard has not
  accepted yet.
- `outputs/` is the input folder of the Specification. Give it to
  `metis engine simulate --input-dir`. It holds `specification.yaml`, `fixtures/`, and
  `target-binding.yaml` when the Interview has a target connection.

A save puts the new files in place, then saves the rows, then deletes the files that the record
no longer refers to. Thus a saved record always has all its files. A save that stops before its
last step can leave a file that no record refers to. The next save of that Interview deletes it.

A save writes each upload under a temporary name first, so a read never gets a part of a file.
An upload with the name of a file in the folder moves that file to a backup name, then takes the
name. A save that fails puts each backup back. Thus it changes no file of the saved record.

Each save of a done Interview writes the Specification row and `outputs/` again. A save of an
Interview that is not done keeps the last Specification. An Experiment is a folder that the
engine writes under `<project>/experiments/execute/`. The engine copies the input folder into
each Experiment folder, so a new Specification does not change an earlier Experiment.
"""

from __future__ import annotations

import hashlib
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
    InterviewRecord,
    SpecificationRecord,
    TargetList,
    TargetProblem,
    TargetSummary,
    file_name_identity,
    record_problem,
)
from metis.api.tables import experiments, interviews, metadata, specifications, targets
from metis.core import execution_layout
from metis.wizard import (
    CompilationError,
    InterviewStep,
    SpecificationError,
    derive_stage,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import BinaryIO

    from sqlalchemy import Table
    from sqlalchemy.engine import Connection, RowMapping

EXPERIMENTS = execution_layout.EXECUTIONS.parent
"""The folder in the project that holds the database, the Target folders, and the Experiment folders."""
DATABASE = EXPERIMENTS / "metis.db"
"""The default SQLite file of the store, relative to the project folder."""
DESIGN = EXPERIMENTS / "design"
"""The folder of the Target folders. `metis wizard init` writes to the same folder."""
FILES = Path("inputs") / "fixtures"
"""The folder of a Target that holds the files of its Interview record."""
OUTPUTS = "outputs"
"""The folder of a Target that `metis engine simulate --input-dir` reads."""


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


class Store:
    """The rows in the database and the Target files under the project folder."""

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
        self._fill_targets()

    @property
    def executions_dir(self) -> Path:
        return self.project_dir / execution_layout.EXECUTIONS

    def target_dir(self, target_id: str) -> Path:
        return self.project_dir / DESIGN / _target_id(target_id)

    def files_dir(self, target_id: str) -> Path:
        return self.target_dir(target_id) / FILES

    def input_dir(self, target_id: str) -> Path:
        return self.target_dir(target_id) / OUTPUTS

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
        outputs = self.input_dir(target_id)
        state = record.state
        done = derive_stage(state) == InterviewStep.DONE and state.pending is None

        with self._lock:
            first_save = self._check_owner(target_id, record)
            input_folder.recover(outputs)
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
                # Each file is in place before the record refers to it. A file that is already
                # in the folder moves to a backup name first, so a failure can put it back.
                for path, temporary in staged.items():
                    if os.path.lexists(path):
                        backup = directory / f".{uuid.uuid4().hex}.old"
                        path.replace(backup)
                        backups[path] = backup
                    written.append(path)
                    temporary.replace(path)
                files = self._specification_files(record, directory) if done else None
                if files is not None:
                    specification = input_folder.stage(outputs, files)
                self._save_rows(target_id, record, files)
            except BaseException:
                if specification is not None:
                    shutil.rmtree(specification, ignore_errors=True)
                if first_save:
                    # No record owns this folder, so a later save would get `target_exists`.
                    shutil.rmtree(self.target_dir(target_id), ignore_errors=True)
                else:
                    for path in written:
                        path.unlink(missing_ok=True)
                    for path, backup in backups.items():
                        backup.replace(path)
                raise
            if specification is not None:
                input_folder.swap(outputs, specification)
            # The backups are files that the record does not refer to.
            keep = {file_name_identity(name) for name in references}
            for path in directory.iterdir() if directory.is_dir() else ():
                if path.is_file() and file_name_identity(path.name) not in keep:
                    path.unlink(missing_ok=True)

    def delete_target(self, target_id: str) -> None:
        """Delete the rows of the Target and its folder in `experiments/design/`.

        The Experiment folders in `experiments/execute/` stay on disk.
        """
        target_id = _target_id(target_id)
        with self._lock:
            with self._engine.begin() as connection:
                for table in (experiments, specifications):
                    connection.execute(
                        delete(table).where(table.c.target_id == target_id)
                    )
                deleted = connection.execute(
                    delete(interviews).where(interviews.c.target_id == target_id)
                ).rowcount
                connection.execute(delete(targets).where(targets.c.id == target_id))
            if not deleted:
                raise _not_found(f"The store has no Target {target_id}.")
            shutil.rmtree(self.target_dir(target_id), ignore_errors=True)

    # Specifications.

    def read_specification(self, target_id: str) -> SpecificationRecord:
        query = select(specifications).where(specifications.c.target_id == target_id)
        with self._lock:
            outputs = self.input_dir(target_id)
            input_folder.recover(outputs)
            document = outputs / input_folder.SPECIFICATION
            with self._engine.connect() as connection:
                row = connection.execute(query).first()
            if (
                row is None
                or not document.is_file()
                or hashlib.sha256(document.read_bytes()).hexdigest() != row.sha256
            ):
                record = self.read_interview(target_id)
                if (
                    derive_stage(record.state) != InterviewStep.DONE
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
                    row = connection.execute(query).one()
        return SpecificationRecord(
            target_id=target_id,
            specification_yaml=row.specification_yaml,
            sha256=row.sha256,
            input_dir=str(self.input_dir(target_id)),
            updated_at=_utc(row.updated_at),
        )

    # Experiments.

    def list_experiments(self, target_id: str) -> list[ExperimentRecord]:
        self._require_target(target_id)
        query = (
            select(experiments)
            .where(experiments.c.target_id == target_id)
            .order_by(experiments.c.started_at.desc())
        )
        with self._engine.connect() as connection:
            return [_experiment(row._mapping) for row in connection.execute(query)]

    def read_experiment(self, experiment_id: str) -> ExperimentRecord:
        query = select(experiments).where(
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
        folder = self.executions_dir / _experiment_id(experiment_id)
        self._require_target(body.target_id)
        with self._lock, self._engine.begin() as connection:
            row = connection.execute(
                select(experiments).where(experiments.c.experiment_id == experiment_id)
            ).first()
            if row is None:
                if not folder.is_dir():
                    raise _invalid(
                        f"The Experiment folder {execution_layout.EXECUTIONS / experiment_id} "
                        "does not exist."
                    )
                connection.execute(
                    insert(experiments).values(
                        experiment_id=experiment_id,
                        target_id=body.target_id,
                        started_at=datetime.now(UTC),
                        step=body.step.value,
                    )
                )
            elif row.target_id != body.target_id:
                raise _invalid(
                    f"The Experiment {experiment_id} belongs to another Target."
                )
            else:
                connection.execute(
                    update(experiments)
                    .where(experiments.c.experiment_id == experiment_id)
                    .values(step=body.step.value)
                )
        return self.read_experiment(experiment_id)

    def delete_experiment(self, experiment_id: str) -> None:
        """Delete the row of an Experiment. The Experiment folder stays on disk."""
        with self._engine.begin() as connection:
            connection.execute(
                delete(experiments).where(
                    experiments.c.experiment_id == _experiment_id(experiment_id)
                )
            )

    # Internals.

    def _fill_targets(self) -> None:
        """Add Target metadata for saved Interviews that have no Target row."""
        query = (
            select(interviews)
            .outerjoin(targets, interviews.c.target_id == targets.c.id)
            .where(targets.c.id.is_(None))
        )
        with self._engine.begin() as connection:
            for row in connection.execute(query):
                if record_problem(row.record) is not None:
                    continue
                record = InterviewRecord.model_validate(row.record)
                connection.execute(
                    insert(targets).values(
                        id=row.target_id,
                        name=record.state.specification.target.name,
                        created_at=row.updated_at,
                        updated_at=row.updated_at,
                    )
                )

    def _require_target(self, target_id: str) -> None:
        if self._saved_record(_target_id(target_id)) is None:
            raise _not_found(f"The store has no Target {target_id}.")

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

    def _save_rows(
        self,
        target_id: str,
        record: InterviewRecord,
        specification: Mapping[str, bytes] | None,
    ) -> None:
        """Write the Target, Interview, and Specification rows in one transaction."""
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            _upsert(
                connection,
                targets,
                targets.c.id == target_id,
                {"name": record.state.specification.target.name, "updated_at": now},
                {"id": target_id, "created_at": now},
            )
            _upsert(
                connection,
                interviews,
                interviews.c.target_id == target_id,
                {"record": record.to_json(), "updated_at": now},
                {"target_id": target_id},
            )
            if specification is not None:
                self._save_specification(connection, target_id, specification, now)

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
    "DATABASE",
    "DESIGN",
    "EXPERIMENTS",
    "FILES",
    "OUTPUTS",
    "Store",
    "StoreError",
    "StoredFile",
    "Upload",
    "safe_name",
]
