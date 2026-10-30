"""SessionTraces: a session's traces saved as the rows Langfuse returned."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from metis.core import SessionTraces, execution_layout
from metis.core.traces import Observation, Trace
from tests.fixtures.traces import SESSION_ID, load_session


def _saved(tmp_path: Path) -> tuple[Path, SessionTraces]:
    traces = load_session().traces
    saved = SessionTraces.from_traces(SESSION_ID, traces)
    path = tmp_path / "outputs" / "traces" / "s.json"
    saved.save(path)
    return path, saved


def test_round_trip_is_lossless(tmp_path: Path) -> None:
    path, saved = _saved(tmp_path)

    loaded = SessionTraces.load_file(path)

    assert loaded.to_traces() == load_session().traces
    again = tmp_path / "again.json"
    loaded.save(again)
    assert again.read_bytes() == path.read_bytes()


def test_unmodelled_row_fields_survive_a_save(tmp_path: Path) -> None:
    observation = Observation.model_validate(
        {"id": "o1", "traceId": "t1", "someNewField": {"deep": [1, 2]}}
    )
    trace = Trace.from_observations("t1", "s1", [observation])
    path = tmp_path / "s1.json"
    SessionTraces.from_traces("s1", [trace]).save(path)

    (loaded,) = SessionTraces.load_file(path).to_traces()

    assert loaded.observations[0].raw["someNewField"] == {"deep": [1, 2]}


def test_file_records_its_schema_and_source(tmp_path: Path) -> None:
    path, _ = _saved(tmp_path)

    data = json.loads(path.read_text(encoding="utf-8"))

    assert data["schema_version"] == 1
    assert data["source"] == "langfuse-observations-v2"
    assert data["session_id"] == SESSION_ID


@pytest.mark.parametrize(
    ("field", "value"), [("schema_version", 2), ("source", "langfuse-observations-v9")]
)
def test_rejects_unsupported_schema_version_and_source(
    tmp_path: Path, field: str, value: object
) -> None:
    path, _ = _saved(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data[field] = value
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match=field):
        SessionTraces.load_file(path)


@pytest.mark.parametrize("session_id", ["a/b", "../x", "..", "a\\b"])
def test_trace_file_name_cannot_escape_the_directory(session_id: str) -> None:
    name = execution_layout.trace_file_name(session_id)

    assert "/" not in name
    assert "\\" not in name
    assert Path(name).parent == Path()
    assert name.endswith(".json")


def test_trace_file_name_encodes_separators() -> None:
    assert execution_layout.trace_file_name("a/b") == "a%2Fb.json"
    assert execution_layout.trace_file_name("sess-1") == "sess-1.json"
