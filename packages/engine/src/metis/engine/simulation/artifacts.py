"""The one place a simulation records a file, and the facts it tells the user agent.

A runner decides what to fetch or send; this module records the result, so the checks that
keep an LLM-driven runner honest run in one place and not once per runner. It writes METIS's
own :class:`metis.core.Artifact`, unchanged.

:class:`ArtifactLedger` guarantees that

* an entry is never removed or replaced, and a file is never overwritten: a name that is
  taken becomes ``name-1.ext``, ``name-2.ext``;
* a download is saved under the last component of the target's name, inside
  ``<trial>/artifacts/``, however the target spelled it;
* ``path``, ``digest``, ``hash_algorithm``, ``state`` and ``content_description`` are set
  by code, never by the caller;
* bytes are written to ``<name>.part`` and renamed only once they are whole and checked,
  so a partial download is never kept;
* a fixture has one entry however often it is uploaded, with the first upload's turn
  stamped on it. Later uploads are in the transport log.

The byte check (:func:`bytes_problem`) catches wrong *kinds* of content: a typed file
that does not start with its signature, and a JSON document or JSON content type saved
under a name that is not ``.json``. A file of the right type with the wrong content, or
a name outside the signature list such as ``.csv``, passes.

:func:`file_facts` is one line per file, never its content: name, type and size, and for
a CSV its data rows, columns and header. Code computes it, once per distinct file.
"""

from __future__ import annotations

import csv
import hashlib
import json
import mimetypes
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal

from metis.core import Artifact

from .transport_log import ArtifactRef

if TYPE_CHECKING:
    from collections.abc import Iterable

ARTIFACTS_DIR = "artifacts"
"""Downloads go to ``<trial folder>/artifacts/``."""

_SIGNATURES = {
    "png": b"\x89PNG",
    "jpg": b"\xff\xd8\xff",
    "jpeg": b"\xff\xd8\xff",
    "gif": b"GIF8",
    "pdf": b"%PDF",
    "docx": b"PK\x03\x04",
    "xlsx": b"PK\x03\x04",
    "pptx": b"PK\x03\x04",
    "zip": b"PK\x03\x04",
}
_FALLBACK_NAME = "artifact"


class ArtifactRejected(ValueError):
    """The bytes cannot be the file their name says; nothing was saved or recorded."""


def bytes_problem(
    name: str, data: bytes, content_type: str | None = None
) -> str | None:
    """Why ``data`` cannot be the file ``name`` says, or ``None`` if it plausibly is."""
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    if ext != "json":
        if content_type and "json" in content_type.lower():
            return f"the target sent JSON, which cannot be saved as {name}"
        if data.lstrip()[:1] in (b"{", b"[") and _is_json(data):
            return f"the bytes are a JSON document, which cannot be saved as {name}"
    if ext in _SIGNATURES and not data.startswith(_SIGNATURES[ext]):
        return f"the bytes are not a .{ext} file"
    return None


def _is_json(data: bytes) -> bool:
    try:
        json.loads(data)
    except ValueError:
        return False
    return True


def file_facts(path: Path, name: str) -> str:
    """One line of facts about the file at ``path``, which is known as ``name``."""
    return _line(path, name, _content_facts(path, name))


def _line(path: Path, name: str, content: str) -> str:
    media_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    line = f"{name} ({media_type}, {path.stat().st_size} bytes)"
    return f"{line}: {content}" if content else line


def _content_facts(path: Path, name: str) -> str:
    """What the bytes add to name, type and size: for a CSV, rows, columns and header."""
    if not name.lower().endswith(".csv"):
        return ""
    try:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh)
            header = next(reader, None)
            if header is None:
                return ""
            rows = sum(1 for row in reader if row)
    except (UnicodeDecodeError, csv.Error):
        return ""
    names = ",".join(" ".join(cell.split()) for cell in header)
    return f"{rows} data rows, {len(header)} columns; header: {names}"


def _safe_name(reported: str) -> str:
    """The last component of ``reported``, however it was spelled."""
    name = PurePosixPath(reported.replace("\\", "/")).name
    return name if name not in ("", ".", "..") else _FALLBACK_NAME


def _unused_path(directory: Path, name: str) -> Path:
    """``directory/name``, or the first free ``directory/stem-N.ext``."""
    candidate = directory / name
    stem, suffix = Path(name).stem, Path(name).suffix
    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem}-{counter}{suffix}"
        counter += 1
    return candidate


class ArtifactLedger:
    """The entries of one trial's files, in order, and the only writer of its downloads.

    :param experiment_root: What each ``Artifact.path`` is relative to.
    :param trial_dir: The trial's folder, inside ``experiment_root``. Downloads go to its
        ``artifacts/`` folder, and an :class:`ArtifactRef` is relative to it.
    :param fixtures: The scenario's fixture entries, as ``build_fixture_artifacts`` makes
        them. A fixture without a description gets code-computed facts.
    """

    def __init__(
        self,
        experiment_root: Path,
        trial_dir: Path,
        fixtures: Iterable[Artifact] = (),
    ) -> None:
        self._root = experiment_root.resolve()
        self._trial_dir = trial_dir.resolve()
        if not self._trial_dir.is_relative_to(self._root):
            raise ValueError(f"the trial folder is outside the experiment: {trial_dir}")
        self._entries: list[Artifact] = []
        self._content: dict[tuple[str, str], str] = {}
        for fixture in fixtures:
            if fixture.source != "fixture":
                raise ValueError(f"{fixture.name!r} is not a fixture")
            entry = fixture.model_copy(deep=True)
            if entry.content_description is None and entry.path and entry.digest:
                entry.content_description = self._facts(
                    self._root / entry.path, entry.name, entry.digest
                )
            self._entries.append(entry)

    def artifacts(self) -> list[Artifact]:
        """Copies of every entry, in the order they were recorded."""
        return [entry.model_copy(deep=True) for entry in self._entries]

    def record_download(
        self,
        name: str,
        data: bytes | Iterable[bytes],
        *,
        at_simulated_turn: int | None,
        external_id: str | None = None,
        content_type: str | None = None,
    ) -> ArtifactRef:
        """Save a downloaded file and record it.

        :param name: The name the target reported; the file is saved under its last
            component.
        :param data: The body, whole or as the chunks of a stream.
        :param at_simulated_turn: The turn the download belongs to, as the caller works it out.
        :param content_type: The response's ``Content-Type``, for the byte check.
        :raises ArtifactRejected: The bytes do not match the name. Nothing is kept.
        :raises Exception: Whatever ends the stream early. Nothing is kept.
        """
        safe = _safe_name(name)
        directory = self._trial_dir / ARTIFACTS_DIR
        directory.mkdir(parents=True, exist_ok=True)
        dest = _unused_path(directory, safe)
        part = dest.with_name(dest.name + ".part")
        digest = hashlib.sha256()
        try:
            with part.open("wb") as fh:
                for chunk in [data] if isinstance(data, bytes) else data:
                    fh.write(chunk)
                    digest.update(chunk)
            if problem := bytes_problem(safe, part.read_bytes(), content_type):
                raise ArtifactRejected(f"{safe}: {problem}")
            part.rename(dest)
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        sha256 = digest.hexdigest()
        self._entries.append(
            Artifact(
                name=safe,
                source="target",
                state="received",
                external_id=external_id,
                path=dest.relative_to(self._root).as_posix(),
                at_simulated_turn=at_simulated_turn,
                content_description=self._facts(dest, safe, sha256),
                digest=sha256,
                hash_algorithm="SHA256",
            )
        )
        return ArtifactRef(
            path=dest.relative_to(self._trial_dir).as_posix(), sha256=sha256
        )

    def record_failure(
        self,
        name: str,
        state: Literal["unfetched", "unavailable"],
        reason: str,
        *,
        at_simulated_turn: int | None,
        external_id: str | None = None,
    ) -> Artifact | None:
        """Record a file that was not received: ``unfetched`` can be retried, ``unavailable`` not.

        :param reason: Becomes ``state_description``.
        :returns: The new entry, or ``None`` when the name is already held or already
            recorded as ``unavailable``, which is not recorded again.
        """
        safe = _safe_name(name)
        if any(
            e.name == safe and e.state in ("received", "unavailable")
            for e in self._entries
        ):
            return None
        entry = Artifact(
            name=safe,
            source="target",
            state=state,
            external_id=external_id,
            at_simulated_turn=at_simulated_turn,
            state_description=reason,
        )
        self._entries.append(entry)
        return entry.model_copy(deep=True)

    def record_upload(
        self, name: str, *, at_simulated_turn: int, external_id: str | None = None
    ) -> Artifact:
        """Note that a held file was sent to the target; no entry is added.

        A fixture's entry gets ``at_simulated_turn`` the first time it is uploaded. Later uploads
        change nothing: the transport log has each one.

        :param external_id: The target's ID for the uploaded file, kept on a fixture's
            entry so a listing's copy of the user's own upload can be told from the
            target's files. The latest one is kept.
        :raises KeyError: No held file has this name.
        """
        for entry in reversed(self._entries):
            if entry.name == name:
                if entry.source == "fixture":
                    if entry.at_simulated_turn is None:
                        entry.at_simulated_turn = at_simulated_turn
                    if external_id is not None:
                        entry.external_id = external_id
                return entry.model_copy(deep=True)
        raise KeyError(name)

    def _facts(self, path: Path, name: str, digest: str) -> str:
        """``file_facts``, with what the bytes add computed once per distinct file."""
        key = (digest, Path(name).suffix.lower())
        if key not in self._content:
            self._content[key] = _content_facts(path, name)
        return _line(path, name, self._content[key])
