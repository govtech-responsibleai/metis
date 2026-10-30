"""An append-only log of every request and response a simulation sends.

The runner agent decides how to act, but code owns every fact in the record:
the reply, the session ID and each file are copied from a logged entry, never from the
agent's account. This module is where those entries are written. A trial's log goes to
``outputs/trials/<id>/evidence/log.jsonl``.

:class:`LoggingTransport` wraps an ``httpx`` transport, so every attempt is logged as
its own request entry and the response entry that answers it, retries included. Entries
are written after redaction: ``Authorization`` and every header the target binding lists
under ``secret_headers`` is replaced by ``***`` in both directions. Only header names
are redacted. A secret placed in a URL or a body would be written as it was sent, which
is why a summary leaves the query string out.

A body over :data:`INLINE_LIMIT` bytes is written to ``evidence/<id>.bin`` and the entry
points to it. A body that is a downloaded artifact is not copied at all: the entry holds
the artifact's path and digest (:class:`ArtifactRef`), so the bytes live once.

The entry model is private to ``metis-engine``: nothing outside the engine reads the
file yet.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Annotated, Literal

import httpx
from pydantic import BaseModel, Field, field_validator

from ._superseded import superseded_path
from .llm_calls import TRIAL_EVIDENCE

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

TRANSPORT_LOG_FILE = "log.jsonl"
INLINE_LIMIT = 64 * 1024
"""A body of exactly this many bytes stays in the log; a larger one goes to a file."""

_ROLES: dict[str, Literal["action", "result"]] = {
    "request": "action",
    "response": "result",
}
_REDACTED = "***"


class InlineBody(BaseModel):
    """A body written into the entry: UTF-8 text, else base64."""

    type: Literal["inline"] = "inline"
    encoding: Literal["utf-8", "base64"]
    text: str


class FileBody(BaseModel):
    """A body too large to inline, written beside the log."""

    type: Literal["file"] = "file"
    path: str
    """Relative to ``evidence/``."""


class ArtifactRef(BaseModel):
    """A body that is a downloaded artifact: where its file is and what it hashes to."""

    type: Literal["artifact"] = "artifact"
    path: str
    """Relative to the trial folder, e.g. ``artifacts/report.pdf``."""
    sha256: str

    @field_validator("path")
    @classmethod
    def _inside_the_trial(cls, path: str) -> str:
        pure = PurePosixPath(path)
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError(f"an artifact path must stay inside the trial: {path}")
        return path


Body = Annotated[InlineBody | FileBody | ArtifactRef, Field(discriminator="type")]


class LogEntry(BaseModel):
    """One request or response."""

    id: str
    at: datetime
    """When the entry was written (UTC)."""
    kind: Literal["request", "response"]
    role: Literal["action", "result"]
    pairs_with: str | None
    """For a response, the ID of the request it answers."""
    summary: str
    """One line written by code from the raw event, e.g. ``POST /api/v1/chat -> 201``."""
    headers: dict[str, str]
    """Lower-cased names; secret values already replaced by ``***``."""
    body: Body


class TransportLog:
    """Appends :class:`LogEntry` lines to one JSONL file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def for_trial(cls, run_dir: Path) -> TransportLog:
        """The log for the trial whose folder is ``run_dir``."""
        return cls(run_dir / TRIAL_EVIDENCE / TRANSPORT_LOG_FILE)

    def _entries(self) -> list[LogEntry]:
        if not self.path.is_file():
            return []
        return [
            LogEntry.model_validate_json(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
        ]

    def get(self, entry_id: str) -> LogEntry:
        """The entry with this ID.

        :raises ValueError: When the log has no such entry.
        """
        for entry in self._entries():
            if entry.id == entry_id:
                return entry
        raise ValueError(f"no entry {entry_id} in the transport log")

    def last_id(self) -> str | None:
        """The ID of the newest entry, or ``None`` when the log is empty."""
        entries = self._entries()
        return entries[-1].id if entries else None

    def body_bytes(self, entry: LogEntry) -> bytes:
        """The raw bytes of an entry's body, whichever way it was stored.

        :raises ValueError: When a stored path leaves its folder, or an artifact no
            longer matches the ``sha256`` recorded for it.
        """
        body = entry.body
        if isinstance(body, InlineBody):
            if body.encoding == "base64":
                return base64.b64decode(body.text)
            return body.text.encode("utf-8")
        if isinstance(body, FileBody):
            return _read_inside(self.path.parent, body.path)
        data = _read_inside(self.path.parent.parent, body.path)
        if hashlib.sha256(data).hexdigest() != body.sha256:
            raise ValueError(f"{body.path} no longer matches its recorded sha256")
        return data

    def append(
        self,
        kind: Literal["request", "response"],
        summary: str,
        body: bytes | ArtifactRef,
        *,
        headers: Mapping[str, str] | None = None,
        pairs_with: str | None = None,
    ) -> str:
        """Write one entry, creating the file and its folder on first use.

        :param summary: One line written by code, never by an LLM.
        :param body: The raw bytes, or a reference when they are an artifact.
        :param headers: Already redacted by the caller.
        :param pairs_with: For a response, the ID of an earlier request.
        :returns: The new entry's ID, ``e1``, ``e2`` and so on.
        :raises ValueError: When nothing should be written: a request that pairs with
            something, a response that pairs with no earlier request, or a summary that
            is not one line.
        """
        if "\n" in summary or "\r" in summary or not summary.strip():
            raise ValueError("a summary must be one non-empty line")
        entries = self._entries()
        if kind == "request" and pairs_with is not None:
            raise ValueError("a request pairs with nothing")
        if pairs_with is not None and not any(
            e.id == pairs_with and e.kind == "request" for e in entries
        ):
            raise ValueError(f"{pairs_with} is not a request already in the log")

        entry_id = f"e{len(entries) + 1}"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        entry = LogEntry(
            id=entry_id,
            at=datetime.now(tz=UTC),
            kind=kind,
            role=_ROLES[kind],
            pairs_with=pairs_with,
            summary=summary,
            headers=dict(headers or {}),
            body=self._store(entry_id, body),
        )
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(entry.model_dump_json() + "\n")
        return entry_id

    def _store(
        self, entry_id: str, body: bytes | ArtifactRef
    ) -> InlineBody | FileBody | ArtifactRef:
        if isinstance(body, ArtifactRef):
            return body
        if len(body) > INLINE_LIMIT:
            name = f"{entry_id}.bin"
            with (self.path.parent / name).open("xb") as fh:
                fh.write(body)
            return FileBody(path=name)
        try:
            return InlineBody(encoding="utf-8", text=body.decode("utf-8"))
        except UnicodeDecodeError:
            return InlineBody(
                encoding="base64", text=base64.b64encode(body).decode("ascii")
            )

    def supersede(self, *, now: datetime | None = None) -> Path | None:
        """Move an earlier attempt's log aside so this attempt starts a new one.

        The attempt's record describes that attempt only, so its log must too, but the
        earlier attempt's evidence is kept. The log becomes
        ``log-superseded-<UTC timestamp>.jsonl`` beside it, and the bodies it wrote to
        ``<id>.bin`` move into a folder of the same name, with the moved log's paths
        rewritten to match, so they cannot collide with the next attempt's ``e1.bin``.

        :param now: Timestamp for the destination name; injected by tests.
        :returns: Where the log was moved, or ``None`` when there was none.
        """
        if not self.path.is_file():
            return None
        dest = superseded_path(self.path, now=now)
        lines = []
        for entry in self._entries():
            if isinstance(entry.body, FileBody):
                folder = dest.with_suffix("")
                folder.mkdir(exist_ok=True)
                moved = folder / entry.body.path
                (self.path.parent / entry.body.path).rename(moved)
                entry.body = FileBody(path=f"{folder.name}/{entry.body.path}")
            lines.append(entry.model_dump_json() + "\n")
        dest.write_text("".join(lines), encoding="utf-8")
        self.path.unlink()
        return dest


def _read_inside(folder: Path, relative: str) -> bytes:
    path = (folder / relative).resolve()
    if not path.is_relative_to(folder.resolve()):
        raise ValueError(f"{relative} is outside {folder.name}/")
    return path.read_bytes()


def _redact(headers: httpx.Headers, secret_names: frozenset[str]) -> dict[str, str]:
    return {
        name: _REDACTED if name in secret_names else value
        for name, value in headers.items()
    }


class LoggingTransport(httpx.AsyncBaseTransport):
    """Logs every request that passes through ``inner`` and the response that answers it.

    Because it sits below the client, a retry loop above it needs no cooperation: each
    attempt is one more pair. A response is read in full before it is returned, so a
    streamed download is logged whole.
    """

    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        log: TransportLog,
        *,
        secret_headers: Iterable[str] = (),
    ) -> None:
        """
        :param secret_headers: Header names to redact besides ``Authorization``, e.g.
            ``SecretHeader.header`` for each of ``TargetBinding.secret_headers``.
        """
        self._inner = inner
        self._log = log
        self._secret_names = frozenset(
            name.lower() for name in ("authorization", *secret_headers)
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        label = f"{request.method} {request.url.path}"
        request_id = self._log.append(
            "request",
            label,
            await request.aread(),
            headers=_redact(request.headers, self._secret_names),
        )
        try:
            response = await self._inner.handle_async_request(request)
            await response.aread()
        except Exception as exc:
            # Never str(exc): some transports echo a header's raw value into their
            # own exception message (h11.LocalProtocolError does this for a header
            # value it rejects, e.g. one with an embedded CRLF), which would put an
            # unredacted secret in the log. The type name and a message we write
            # ourselves are the only things guaranteed not to carry one.
            self._log.append(
                "response",
                f"{label} -> {type(exc).__name__}",
                f"{type(exc).__name__}: request failed before a response was received".encode(),
                pairs_with=request_id,
            )
            raise
        self._log.append(
            "response",
            f"{label} -> {response.status_code}",
            response.content,
            headers=_redact(response.headers, self._secret_names),
            pairs_with=request_id,
        )
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


__all__ = [
    "INLINE_LIMIT",
    "ArtifactRef",
    "LogEntry",
    "LoggingTransport",
    "TransportLog",
]
