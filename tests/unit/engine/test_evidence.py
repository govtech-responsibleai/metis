"""Evidence pointers: code copies a fact from a logged result the agent points at (#508)."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

import pytest

from metis.engine.simulation.evidence import Pointer, PointerError, resolve
from metis.engine.simulation.transport_log import (
    INLINE_LIMIT,
    ArtifactRef,
    TransportLog,
)

if TYPE_CHECKING:
    from pathlib import Path

_DOC = {"data": {"id": "s-42", "items": [{"name": "a"}, {"name": "b"}], "a.b": "dot"}}


def _result(log: TransportLog, body: Any) -> str:
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return log.append("response", "GET /x -> 200", raw)


@pytest.fixture
def log(tmp_path: Path) -> TransportLog:
    return TransportLog.for_trial(tmp_path)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("$.data.id", "s-42"),
        ("$.data.items[1].name", "b"),
        ('$["data"]["a.b"]', "dot"),
        ("$.data.items[0]", {"name": "a"}),
    ],
)
def test_a_path_names_one_value(log: TransportLog, path: str, expected: Any) -> None:
    entry_id = _result(log, _DOC)

    value, entry = resolve(Pointer(entry_id, path), log)

    assert value == expected
    assert entry.id == entry_id


def test_without_a_path_the_value_is_the_body_as_text(log: TransportLog) -> None:
    entry_id = _result(log, b"hello")

    assert resolve(Pointer(entry_id), log)[0] == "hello"


def test_a_pattern_returns_its_group(log: TransportLog) -> None:
    entry_id = _result(log, {"url": "https://app.example/sessions/s-9/files"})

    pointer = Pointer(entry_id, "$.url", r"/sessions/([\w-]+)/")

    assert resolve(pointer, log)[0] == "s-9"


def test_a_pattern_without_a_group_returns_the_whole_match(log: TransportLog) -> None:
    entry_id = _result(log, {"url": "https://app.example/sessions/s-9/files"})

    assert resolve(Pointer(entry_id, "$.url", r"s-\d+"), log)[0] == "s-9"


@pytest.mark.parametrize(
    ("pointer", "message"),
    [
        (Pointer("e99"), "no entry e99"),
        (Pointer("e1", "$.data.nope"), r"\$\.data\.nope.*not in"),
        (Pointer("e1", "$.data.items[5]"), "not in"),
        (Pointer("e1", "data.id"), "starts with"),
        (Pointer("e1", "$.data.*"), "cannot read"),
        (Pointer("e1", "$.data.id", "(["), "does not compile"),
        (Pointer("e1", "$.data.id", r"\d{9}"), "does not match"),
        (Pointer("e1", "$.data.items[0]", "a"), "only to text"),
    ],
)
def test_every_refusal_is_a_pointer_error(
    log: TransportLog, pointer: Pointer, message: str
) -> None:
    _result(log, _DOC)

    with pytest.raises(PointerError, match=message):
        resolve(pointer, log)


def test_a_path_into_a_body_that_is_not_json_is_refused(log: TransportLog) -> None:
    entry_id = _result(log, b"plain text")

    with pytest.raises(PointerError, match="not JSON"):
        resolve(Pointer(entry_id, "$.a"), log)


def test_an_action_entry_cannot_be_cited(log: TransportLog) -> None:
    entry_id = log.append("request", "POST /x", b'{"a": 1}')

    with pytest.raises(PointerError, match="action"):
        resolve(Pointer(entry_id, "$.a"), log)


def test_an_entry_outside_the_allowed_set_is_refused(log: TransportLog) -> None:
    earlier = _result(log, _DOC)
    current = _result(log, _DOC)

    assert resolve(Pointer(current, "$.data.id"), log, {current})[0] == "s-42"
    with pytest.raises(PointerError, match="not one of the entries"):
        resolve(Pointer(earlier, "$.data.id"), log, {current})


def test_a_body_stored_in_a_file_resolves(log: TransportLog) -> None:
    padding = "x" * INLINE_LIMIT
    entry_id = _result(log, {"id": "big-1", "padding": padding})

    assert resolve(Pointer(entry_id, "$.id"), log)[0] == "big-1"


def test_an_artifact_body_resolves_while_its_digest_matches(
    tmp_path: Path, log: TransportLog
) -> None:
    content = b'{"id": "from-file"}'
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts" / "r.json").write_bytes(content)
    ref = ArtifactRef(
        path="artifacts/r.json", sha256=hashlib.sha256(content).hexdigest()
    )
    entry_id = log.append("response", "GET /f -> 200", ref)

    assert resolve(Pointer(entry_id, "$.id"), log)[0] == "from-file"

    (tmp_path / "artifacts" / "r.json").write_bytes(b'{"id": "changed"}')
    with pytest.raises(PointerError, match="sha256"):
        resolve(Pointer(entry_id, "$.id"), log)


_SNAPSHOT = """\
- main [ref=e1]:
  - paragraph [ref=e2]: Hello there
  - list [ref=e3]:
    - listitem [ref=e4]: a.txt
    - listitem [ref=e5]: b.txt
  - button "Send" [ref=e6]"""


def _capture(log: TransportLog, snapshot: str = _SNAPSHOT) -> str:
    return _result(
        log, {"url": "https://app.example/", "title": "T", "snapshot": snapshot}
    )


def test_a_ref_names_one_element_of_a_snapshot(log: TransportLog) -> None:
    entry_id = _capture(log)

    value, entry = resolve(Pointer(entry_id, ref="e2"), log)

    assert value == "- paragraph [ref=e2]: Hello there"
    assert entry.id == entry_id


def test_a_ref_brings_the_elements_nested_under_it(log: TransportLog) -> None:
    entry_id = _capture(log)

    value, _ = resolve(Pointer(entry_id, ref="e3"), log)

    assert value == (
        "- list [ref=e3]:\n  - listitem [ref=e4]: a.txt\n  - listitem [ref=e5]: b.txt"
    )


def test_a_pattern_narrows_a_ref(log: TransportLog) -> None:
    entry_id = _capture(log)

    assert resolve(Pointer(entry_id, ref="e5", pattern=r": (.+)$"), log)[0] == "b.txt"


def test_a_ref_absent_from_the_snapshot_is_refused(log: TransportLog) -> None:
    entry_id = _capture(log)

    with pytest.raises(PointerError, match="no element e9"):
        resolve(Pointer(entry_id, ref="e9"), log)


def test_a_ref_and_a_path_together_are_refused(log: TransportLog) -> None:
    entry_id = _capture(log)

    with pytest.raises(PointerError, match="ref or a path"):
        resolve(Pointer(entry_id, "$.title", ref="e2"), log)


def test_a_ref_needs_a_capture(log: TransportLog) -> None:
    text = _result(log, b"plain text")
    no_snapshot = _result(log, {"title": "T"})

    with pytest.raises(PointerError, match="not a page capture"):
        resolve(Pointer(text, ref="e1"), log)
    with pytest.raises(PointerError, match="not a page capture"):
        resolve(Pointer(no_snapshot, ref="e1"), log)
