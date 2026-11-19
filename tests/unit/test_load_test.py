"""The pure parts of the load test: the input copies, the percentiles, the summary, the verdict."""

from __future__ import annotations

import filecmp
from pathlib import Path

import pytest
from metis_load_test import (
    Outcome,
    StartResult,
    Tracked,
    is_ended,
    make_input_copies,
    percentile,
    rewrite_specification_id,
    summarise,
    summary_hint,
    verdict_reasons,
)

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


# --- percentiles, experiments, verdict, summary -----------------------------------------------


def test_percentile_uses_nearest_rank():
    assert percentile([4.0, 1.0, 3.0, 2.0], 0.50) == 2.0
    assert percentile([4.0, 1.0, 3.0, 2.0], 0.95) == 4.0
    assert percentile([], 0.95) is None


def test_observe_records_when_it_leaves_the_queue_and_ends():
    tracked = Tracked(user=1, experiment_id="e1", accepted_at=10.0)

    tracked.observe({"status": "queued", "phase": "simulating", "queue_ahead": 0}, 12.0)
    assert (tracked.left_queue_at, tracked.ended) == (None, False)
    tracked.observe({"status": "running", "phase": "simulating", "total": 3}, 14.0)
    tracked.observe({"status": "running", "phase": "evaluating", "total": 3}, 20.0)
    tracked.observe({"status": "completed", "phase": "evaluating", "total": 3}, 30.0)
    tracked.observe({"status": "completed", "phase": "evaluating", "total": 3}, 32.0)

    assert tracked.left_queue_at == 14.0
    assert tracked.ended_at == 30.0
    assert tracked.ended
    assert (tracked.queue_wait, tracked.run_time) == (4.0, 16.0)


def test_a_first_poll_that_is_not_queued_means_no_wait():
    tracked = Tracked(user=1, experiment_id="e1", accepted_at=10.0)

    tracked.observe({"status": "running", "phase": "simulating"}, 12.0)

    assert tracked.queue_wait == 0.0


@pytest.mark.parametrize(
    ("status", "ended"),
    [
        ("queued", False),
        ("running", False),
        ("stopping", False),
        ("completed", True),
        ("failed", True),
        ("interrupted", True),
        ("unfinished", True),
        ("not_started", True),
        (None, False),
    ],
)
def test_is_ended(status, ended):
    assert is_ended(status) is ended


def _accepted(user: int) -> StartResult:
    return StartResult(
        user=user,
        experiment_id=f"e{user}",
        http_status=202,
        code=None,
        message=None,
        accepted_at=0.0,
    )


def _done(user: int, status: str = "completed", phase: str = "evaluating") -> Tracked:
    tracked = Tracked(user=user, experiment_id=f"e{user}", accepted_at=0.0)
    tracked.observe({"status": "queued", "phase": "simulating"}, 2.0)
    tracked.observe({"status": "running", "phase": "simulating"}, 4.0)
    tracked.observe({"status": status, "phase": phase}, 10.0 * user)
    return tracked


def _outcome(**changes: object) -> Outcome:
    values: dict[str, object] = {
        "users": 2,
        "url": "http://127.0.0.1:8001",
        "starts": [_accepted(1), _accepted(2)],
        "experiments": [_done(1), _done(2)],
        "latencies": [0.1] * 20,
        "status_errors": 0,
        "timed_out": False,
        "interrupted": False,
        "elapsed_seconds": 20.0,
        "copies_dir": Path("/p/evaluations/load-test/s"),
        "project_dir": Path("/p"),
    }
    values.update(changes)
    return Outcome(**values)  # type: ignore[arg-type]


def test_all_good_is_yes():
    outcome = _outcome()

    assert verdict_reasons(outcome) == []
    assert summarise(outcome)["verdict"] == "yes"


_REFUSED = StartResult(
    user=2,
    experiment_id=None,
    http_status=409,
    code="experiment_exists",
    message="A run of the same Specification started in the same second.",
    accepted_at=None,
)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        (
            {"starts": [_accepted(1), _REFUSED], "experiments": [_done(1)]},
            "1 of 2 starts",
        ),
        ({"experiments": [_done(1), _done(2, status="failed")]}, "1 of 2 experiments"),
        (
            {"experiments": [_done(1), _done(2, phase="simulating")]},
            "1 of 2 experiments",
        ),
        ({"latencies": [0.1] * 18 + [1.0, 1.0]}, "p95"),
        ({"timed_out": True}, "timeout"),
        ({"interrupted": True}, "Ctrl-C"),
    ],
)
def test_each_failure_is_no(changes, reason):
    outcome = _outcome(**changes)

    reasons = verdict_reasons(outcome)
    assert len(reasons) == 1
    assert reason in reasons[0]
    assert summarise(outcome)["verdict"] == "no"


def test_no_status_answer_is_no():
    reasons = verdict_reasons(_outcome(latencies=[], status_errors=3))

    assert any("p95" in reason for reason in reasons)


def test_summary_shape():
    outcome = _outcome(
        users=3,
        starts=[_accepted(1), _REFUSED, _accepted(3)],
        experiments=[_done(1), _done(3, status="failed")],
        latencies=[0.1, 0.2, 0.3],
        status_errors=1,
    )

    summary = summarise(outcome)

    assert summary["users"] == 3
    assert summary["starts"] == {
        "accepted": 2,
        "failed": [
            {
                "user": 2,
                "http_status": 409,
                "code": "experiment_exists",
                "message": "A run of the same Specification started in the same second.",
            }
        ],
    }
    assert summary["final_statuses"] == {"completed": 1, "failed": 1}
    assert summary["status_latency_seconds"] == {
        "requests": 3,
        "errors": 1,
        "p50": 0.2,
        "p95": 0.3,
        "max": 0.3,
    }
    assert summary["queue_wait_seconds"] == {"p50": 4.0, "p95": 4.0, "max": 4.0}
    assert summary["run_seconds"] == {"p50": 6.0, "p95": 26.0, "max": 26.0}
    assert summary["per_user"] == [
        {
            "user": 1,
            "experiment_id": "e1",
            "status": "completed",
            "phase": "evaluating",
            "queue_wait_seconds": 4.0,
            "run_seconds": 6.0,
        },
        {
            "user": 2,
            "experiment_id": None,
            "status": None,
            "phase": None,
            "queue_wait_seconds": None,
            "run_seconds": None,
        },
        {
            "user": 3,
            "experiment_id": "e3",
            "status": "failed",
            "phase": "evaluating",
            "queue_wait_seconds": 4.0,
            "run_seconds": 26.0,
        },
    ]
    assert summary["input_copies"] == "/p/evaluations/load-test/s"
    assert summary["experiments"] == "/p/evaluations/experiments"
    assert summary["timed_out"] is False
    assert summary["elapsed_seconds"] == 20.0


def test_hint_names_the_project_folder_override():
    refused = StartResult(
        user=1,
        experiment_id=None,
        http_status=422,
        code="invalid_inputs",
        message="input directory does not exist",
        accepted_at=None,
    )

    hint = summary_hint(_outcome(starts=[refused], experiments=[]))

    assert hint is not None
    assert "LOAD_TEST_PROJECT_DIR" in hint
    assert "/p" in hint
    assert summary_hint(_outcome()) is None
