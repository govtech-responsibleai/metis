"""Opening documents on the CLI.

The CLI reads opening files with the same extraction code and limits as the API. These tests drive `init` through the real Typer app with no model call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import typer
from typer.testing import CliRunner

from metis.wizard import InterviewStartRequest, InterviewState
from metis.wizard.adapters.cli import commands as cli
from metis.wizard.adapters.cli.documents import read_opening_documents
from metis.wizard.application import documents as extraction
from metis.wizard.bootstrap import create_cli_app
from tests.fixtures.wizard.context import interview_context
from tests.fixtures.wizard.specifications import research_assistant

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> list[InterviewStartRequest]:
    """Finish each Interview at once and record the start request that `init` sends."""
    requests: list[InterviewStartRequest] = []

    def finish(request, **_kwargs) -> InterviewState:
        requests.append(request)
        return InterviewState(
            specification=research_assistant(),
            context=interview_context(),
            confirmed=True,
        )

    monkeypatch.setattr(cli, "_load_env", list)
    monkeypatch.setattr(cli, "_new_interviewer", object)
    monkeypatch.setattr(cli, "_matcher", lambda _interviewer: None)
    monkeypatch.setattr(cli, "_drive", finish)
    return requests


def _init(out_dir: Path, *documents: Path):
    arguments = ["init", "A research assistant", "--out-dir", str(out_dir)]
    for path in documents:
        arguments += ["--document", str(path)]
    # A blank capability selection, then the confidence.
    return CliRunner().invoke(create_cli_app(), arguments, input="end_user\n\nlow\n")


def test_a_readable_document_goes_to_the_interview_with_its_text(
    tmp_path: Path, started: list[InterviewStartRequest]
) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_text("The assistant cites each source.", encoding="utf-8")
    diagram = tmp_path / "diagram.png"
    diagram.write_bytes(b"\x89PNG")

    result = _init(tmp_path / "eval", notes, diagram)

    assert result.exit_code == 0, result.output
    assert "Read: notes.txt" in result.output
    assert "Not read: diagram.png (no text reader for this file type)" in result.output
    [request] = started
    assert [(item.name, item.text) for item in request.documents] == [
        ("notes.txt", "The assistant cites each source."),
        ("diagram.png", None),
    ]


def test_an_unsupported_file_type_stops_before_any_model_call(
    tmp_path: Path, started: list[InterviewStartRequest]
) -> None:
    program = tmp_path / "setup.exe"
    program.write_bytes(b"MZ")

    result = _init(tmp_path / "eval", program)

    assert result.exit_code == 1
    assert "Unsupported fixture type" in result.output
    assert started == []
    assert not (tmp_path / "eval").exists()


def test_a_file_over_the_reading_limit_stops_a_run_with_no_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    started: list[InterviewStartRequest],
) -> None:
    monkeypatch.setattr(extraction, "MAX_EXTRACTION_FILE_BYTES", 8)
    large = tmp_path / "large.txt"
    large.write_text("more than eight bytes", encoding="utf-8")

    result = _init(tmp_path / "eval", large)

    assert result.exit_code == 1
    assert "Could not read: large.txt: Each document must be at most 8 bytes." in (
        result.output
    )
    assert started == []


@pytest.mark.parametrize("keep", [True, False])
def test_the_user_decides_whether_to_keep_a_file_that_could_not_be_read(
    tmp_path: Path, keep: bool
) -> None:
    empty = tmp_path / "empty.md"
    empty.write_bytes(b"")
    out: list[str] = []
    asked: list[str] = []

    def confirm(prompt: str) -> bool:
        asked.append(prompt)
        return keep

    if keep:
        documents = read_opening_documents([empty], out=out.append, confirm=confirm)
        assert [(item.name, item.text) for item in documents] == [("empty.md", None)]
    else:
        with pytest.raises(typer.Exit):
            read_opening_documents([empty], out=out.append, confirm=confirm)
    assert out == ["Could not read: empty.md: The file is empty."]
    assert asked == ["Keep unread files without text?"]


def test_a_test_case_gets_the_bytes_of_the_opening_document_that_it_uses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    started: list[InterviewStartRequest],
) -> None:
    specification = research_assistant()
    for task in specification.tasks:
        task.fixtures = ["notes.txt"] if task.fixtures else []
    monkeypatch.setattr(
        cli,
        "_drive",
        lambda request, **_kwargs: InterviewState(
            specification=specification, context=interview_context(), confirmed=True
        ),
    )
    notes = tmp_path / "notes.txt"
    notes.write_text("Use this policy.", encoding="utf-8")
    diagram = tmp_path / "diagram.png"
    diagram.write_bytes(b"\x89PNG")
    out_dir = tmp_path / "eval"

    result = _init(out_dir, notes, diagram)

    assert result.exit_code == 0, result.output
    # `resume` reads the originals from the experiment, so both files are kept there.
    assert sorted(path.name for path in (out_dir / "inputs/documents").iterdir()) == [
        "diagram.png",
        "notes.txt",
    ]
    # The package contains only the file that a Test Case uses.
    assert [path.name for path in (out_dir / "outputs/fixtures").iterdir()] == [
        "notes.txt"
    ]
    assert (out_dir / "outputs/fixtures/notes.txt").read_bytes() == notes.read_bytes()


def test_a_restart_with_new_documents_removes_the_old_copies_from_the_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    started: list[InterviewStartRequest],
) -> None:
    used: list[str] = ["old.txt"]

    def finish(request, **_kwargs) -> InterviewState:
        specification = research_assistant()
        for task in specification.tasks:
            task.fixtures = list(used) if task.fixtures else []
        return InterviewState(
            specification=specification, context=interview_context(), confirmed=True
        )

    monkeypatch.setattr(cli, "_drive", finish)
    old = tmp_path / "old.txt"
    old.write_text("The old policy.", encoding="utf-8")
    new = tmp_path / "new.txt"
    new.write_text("The new policy.", encoding="utf-8")
    out_dir = tmp_path / "eval"
    fixtures = out_dir / "outputs/fixtures"

    assert _init(out_dir, old).exit_code == 0
    # A file that the user adds has bytes of its own, so the export keeps it.
    (fixtures / "manual.csv").write_text("id\n1\n", encoding="utf-8")
    used[:] = ["new.txt"]
    result = CliRunner().invoke(
        create_cli_app(),
        ["init", "A research assistant", "--out-dir", str(out_dir), "--restart"]
        + ["--document", str(new)],
        input="end_user\n\nlow\n",
    )

    assert result.exit_code == 0, result.output
    assert sorted(path.name for path in fixtures.iterdir()) == [
        "manual.csv",
        "new.txt",
    ]


def test_the_export_names_a_used_file_that_is_not_an_opening_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    started: list[InterviewStartRequest],
) -> None:
    specification = research_assistant()
    for task in specification.tasks:
        task.fixtures = ["records.csv"] if task.fixtures else []
    monkeypatch.setattr(
        cli,
        "_drive",
        lambda request, **_kwargs: InterviewState(
            specification=specification, context=interview_context(), confirmed=True
        ),
    )
    out_dir = tmp_path / "eval"

    result = _init(out_dir)

    assert result.exit_code == 0, result.output
    fixtures = out_dir / "outputs/fixtures"
    assert f"Add records.csv to {fixtures} before you run." in " ".join(
        result.output.split()
    )
    assert list(fixtures.iterdir()) == []
