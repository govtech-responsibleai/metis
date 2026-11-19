"""Each trial of report.json links to its session in the target's Langfuse."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from metis.core.langfuse_links import TargetProject
from metis.insights import _report
from tests.fixtures.insights.report_experiment import (
    TASKS,
    grader_records,
    trial_record,
    write_experiment,
)
from tests.fixtures.insights.report_page import build

if TYPE_CHECKING:
    from pathlib import Path


class Lookup:
    """A stand-in for the project lookup that counts its calls."""

    def __init__(self, answer: TargetProject | None) -> None:
        self.answer = answer
        self.calls = 0

    def __call__(self) -> TargetProject | None:
        self.calls += 1
        return self.answer


@pytest.fixture
def lookup(monkeypatch: pytest.MonkeyPatch) -> Lookup:
    stub = Lookup(TargetProject("https://lf.example", "p1"))
    monkeypatch.setattr(_report, "target_langfuse_project", stub)
    return stub


@pytest.fixture
def results(tmp_path: Path) -> Path:
    """The results file of an experiment whose records have no saved URL."""
    return write_experiment(tmp_path / "experiment", grader_records())


def _root(results: Path) -> Path:
    return results.parents[2]


def _trials(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        trial["session"]: trial
        for row in report["resultTable"]["rows"]
        for trial in row["trials"]
    }


def _rewrite(results: Path, session: str, **update: object) -> None:
    task_id, trial = session.rsplit("-", 1)
    record = trial_record(task_id, int(trial)).model_copy(update=update)
    path = _root(results) / "outputs/trials" / session / "record.json"
    path.write_text(record.model_dump_json())


def _save_urls(results: Path) -> None:
    for task_id in TASKS:
        for trial in (1, 2):
            session = f"{task_id}-{trial}"
            _rewrite(
                results,
                session,
                target_session_langfuse_url=f"https://saved.example/project/p0/sessions/{session}",
            )


def test_a_saved_url_is_used_with_no_lookup(results: Path, lookup: Lookup) -> None:
    _save_urls(results)
    trials = _trials(build(results))
    assert trials["T-1-1"]["sessionUrl"] == (
        "https://saved.example/project/p0/sessions/T-1-1"
    )
    assert lookup.calls == 0


def test_old_records_get_a_url_from_one_lookup(results: Path, lookup: Lookup) -> None:
    trials = _trials(build(results))
    assert len(trials) == 4
    for session, trial in trials.items():
        assert (
            trial["sessionUrl"] == f"https://lf.example/project/p1/sessions/{session}"
        )
    assert lookup.calls == 1


def test_a_failed_lookup_gives_no_link_and_is_tried_once(
    results: Path, lookup: Lookup
) -> None:
    lookup.answer = None
    trials = _trials(build(results))
    assert all(trial["sessionUrl"] is None for trial in trials.values())
    assert lookup.calls == 1


def test_a_trial_without_a_session_has_no_link_and_needs_no_lookup(
    results: Path, lookup: Lookup
) -> None:
    _save_urls(results)
    _rewrite(results, "T-1-1", target_session_id=None)
    sources = _report.load_report_sources(_root(results))
    assert sources is not None
    (trial,) = [t for t in sources[1] if t["id"] == "T-1-1"]
    assert trial["sessionUrl"] is None
    assert lookup.calls == 0
