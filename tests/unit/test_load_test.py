"""The pure parts of the load test: the input copies, the percentiles, the summary, the verdict."""

from __future__ import annotations

import filecmp
from pathlib import Path

import pytest
from metis_load_test import make_input_copies, rewrite_specification_id

from metis.engine.simulation.types import Specification

EXAMPLE = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "engine"
    / "examples"
    / "http-agentic_eval_toyapp-1"
)
STAMP = "20261119-101500"


# --- input copies ---------------------------------------------------------------------------


def test_copies_get_their_own_ids_and_load(tmp_path):
    copies = make_input_copies(EXAMPLE, tmp_path, 3, stamp=STAMP)

    assert [copy.user for copy in copies] == [1, 2, 3]
    for i, copy in enumerate(copies, start=1):
        new_id = f"toyapp-http-simple-load-{i}"
        assert copy.path == tmp_path / "evaluations" / "load-test" / STAMP / new_id
        assert copy.input_dir == f"evaluations/load-test/{STAMP}/{new_id}"
        assert Specification.load_file(copy.path / "specification.yaml").id == new_id


def test_copy_differs_only_in_the_id(tmp_path):
    (copy,) = make_input_copies(EXAMPLE, tmp_path, 1, stamp=STAMP)

    def differences(compare: filecmp.dircmp[str]) -> list[str]:
        found = [*compare.diff_files, *compare.left_only, *compare.right_only]
        for sub in compare.subdirs.values():
            found += differences(sub)
        return found

    assert differences(filecmp.dircmp(EXAMPLE, copy.path)) == ["specification.yaml"]
    source = Specification.load_file(EXAMPLE / "specification.yaml")
    loaded = Specification.load_file(copy.path / "specification.yaml")
    assert loaded.model_copy(update={"id": source.id}) == source


def test_existing_stamp_folder_is_refused(tmp_path):
    make_input_copies(EXAMPLE, tmp_path, 1, stamp=STAMP)

    with pytest.raises(FileExistsError):
        make_input_copies(EXAMPLE, tmp_path, 1, stamp=STAMP)


def test_source_without_specification_is_refused(tmp_path):
    with pytest.raises(ValueError, match="specification.yaml"):
        make_input_copies(tmp_path, tmp_path, 1, stamp=STAMP)


def test_rewrite_keeps_indented_ids():
    text = "schema_version: 1\nid: a\nfeatures:\n- id: F-1\n  name: x\n"

    assert rewrite_specification_id(text, "a-load-1") == (
        'schema_version: 1\nid: "a-load-1"\nfeatures:\n- id: F-1\n  name: x\n'
    )


@pytest.mark.parametrize("line", ["id: 'a'  # the target", 'id: "a"', "id:   a"])
def test_rewrite_handles_quotes_and_comments(line):
    assert rewrite_specification_id(f"{line}\nx: 1\n", "b") == 'id: "b"\nx: 1\n'


@pytest.mark.parametrize("text", ["features:\n- id: F-1\n", "id: a\nid: b\n"])
def test_rewrite_needs_one_top_level_id(text):
    with pytest.raises(ValueError, match="top-level id"):
        rewrite_specification_id(text, "b")
