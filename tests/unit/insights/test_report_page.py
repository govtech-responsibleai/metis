"""The sections of report.html, built by the page renderers from report.json."""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from metis.insights._report_page import render_report_page
from tests.fixtures.insights.report_experiment import (
    grader_record,
    grader_records,
    save_trial_traces,
    turn_trace,
    write_experiment,
)
from tests.fixtures.insights.report_page import build, open_case, render_js

if TYPE_CHECKING:
    from pathlib import Path

TABLE = "{openCase:null,trialByCase:{},markCol:null,markRow:null}"


@pytest.fixture
def experiment(tmp_path: Path) -> Path:
    return write_experiment(tmp_path / "experiment", grader_records())


def test_page_shows_the_target_and_score(experiment: Path, tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed to check the page script")
    records = grader_records()
    records[0].results[0].reason = "</script><script>alert(1)</script> <!--<script>"
    report = build(experiment, records)
    html = render_report_page(report, title="<Target>")
    assert "<title>&lt;Target&gt;</title>" in html
    assert "</script><script>alert(1)</script>" not in html
    assert "<!--<script" not in html
    page = tmp_path / "page.js"
    page.write_text(
        html[html.index("<script>") + len("<script>") : html.rindex("</script>")],
        encoding="utf-8",
    )
    subprocess.run([node, "--check", str(page)], check=True, capture_output=True)
    assert "Target" in render_js(report, "renderHeader(V)")
    score = render_js(report, "renderScore(V)")
    assert f"{report['scores']['graderPassRate']['rate']}%" in score
    assert (
        "The default pass-rate target is 70%. Scores below it are shown in red."
        in score
    )


def test_specification_shows_as_list_and_tree(experiment: Path) -> None:
    report = build(experiment)
    state = "{view:'list',open:new Set(['B-1']),selected:null}"
    listed = render_js(report, f"renderList(V,{state})")
    assert "Feature one" in listed
    assert 'data-criterion="C-1"' in listed
    tree = render_js(report, f"renderTree(V,{state})")
    assert "<title>Target</title>" in tree
    assert 'data-criterion="C-1"' in tree


def _node(html: str, start: str, mark: str) -> str:
    """The one node of ``html`` that starts with ``start`` and holds ``mark``."""
    return next(part for part in html.split(start) if mark in part)


def test_the_headline_warns_how_many_grader_runs_errored(experiment: Path) -> None:
    """Seven grader runs: one errored, one skipped, five graded."""
    score = render_js(build(experiment), "renderScore(V)")
    warning = score.split('<div class="warn-line"', 1)[1].split("</div>", 1)[0]
    assert 'aria-hidden="true"' in warning
    assert "<span>1 of 7 grader runs errored</span>" in warning
    assert "<span>Grader runs completed</span><b>6 of 7</b>" in score


def _state(*, closed: tuple[str, ...] = (), opened: tuple[str, ...] = ()) -> str:
    """A view state with the Features ``closed`` and the Behaviours ``opened``."""
    return (
        f"{{open:new Set({list(opened)}),closed:new Set({list(closed)}),selected:null}}"
    )


def _views(report: dict, state: str) -> list[tuple[str, str]]:
    """The list view and the tree view, each with the text that starts one node."""
    return [
        (render_js(report, f"renderList(V,{state})"), "<button"),
        (render_js(report, f"renderTree(V,{state})"), '<g class="tree-node"'),
    ]


def test_a_closed_feature_with_errored_runs_shows_the_mini_icon(
    experiment: Path,
) -> None:
    report = build(experiment)
    feature = ('data-toggle-feature="F-1"', "<title>Feature one</title>")
    for (html, start), mark in zip(
        _views(report, _state(closed=("F-1",))), feature, strict=True
    ):
        node = _node(html, start, mark)
        assert 'class="warn mini"' in node
        assert 'aria-label="1 of 7 grader runs errored"' in node
    for (html, start), mark in zip(_views(report, _state()), feature, strict=True):
        assert "grader runs errored" not in _node(html, start, mark)


def test_the_target_node_shows_the_mini_icon_when_errored_features_are_closed(
    experiment: Path,
) -> None:
    report = build(experiment)
    target = "<title>Target</title>"
    closed = render_js(report, f"renderTree(V,{_state(closed=('F-1',))})")
    assert 'class="warn mini"' in _node(closed, '<g class="tree-node"', target)
    opened = render_js(report, f"renderTree(V,{_state()})")
    assert "grader runs errored" not in _node(opened, '<g class="tree-node"', target)


def test_a_closed_behaviour_with_errored_runs_shows_the_icon(
    experiment: Path,
) -> None:
    report = build(experiment)
    for html, start in _views(report, _state()):
        behaviour = _node(html, start, 'data-behaviour="B-2"')
        assert 'class="warn"' in behaviour
        assert 'aria-label="1 of 2 grader runs errored"' in behaviour
        assert "grader runs errored" not in _node(html, start, 'data-behaviour="B-1"')
    for html, start in _views(report, _state(opened=("B-2",))):
        assert "grader runs errored" not in _node(html, start, 'data-behaviour="B-2"')


def test_a_criterion_with_no_rate_from_errored_runs_is_not_graded(
    experiment: Path,
) -> None:
    """C-3 has one errored and one skipped run, so it has no rate."""
    for html, start in _views(build(experiment), _state(opened=("B-2",))):
        criterion = _node(html, start, 'data-criterion="C-3"')
        assert "Not graded" in criterion
        assert 'class="not-graded"' in criterion
        assert "grader runs errored" not in criterion


def test_a_criterion_with_a_rate_and_errored_runs_shows_the_icon(
    experiment: Path,
) -> None:
    records = [*grader_records(), grader_record("T-2", 1, "C-2", "errored")]
    report = build(experiment, records)
    for html, start in _views(report, _state(opened=("B-1",))):
        criterion = _node(html, start, 'data-criterion="C-2"')
        assert 'aria-label="1 of 2 grader runs errored"' in criterion
        assert "grader runs errored" not in _node(html, start, 'data-criterion="C-1"')


def test_no_errored_run_adds_no_warning(experiment: Path) -> None:
    records = [r for r in grader_records() if r.results[0].outcome != "errored"]
    report = build(experiment, records)
    score = render_js(report, "renderScore(V)")
    assert "warn-line" not in score
    assert "<span>Grader runs completed</span><b>6 of 6</b>" in score
    for state in (_state(opened=("B-1", "B-2")), _state(closed=("F-1",))):
        for html, _start in _views(report, state):
            assert "grader runs errored" not in html


def test_criterion_panel_counts_graded_results_and_explains_the_squares(
    experiment: Path,
) -> None:
    """C-3 has one errored and one skipped run. The squares show the errored run."""
    html = render_js(build(experiment), "renderPanel(V,{selected:'C-3'})")
    assert "0 of 0 graded results passed" in html
    assert "1 skipped" in html
    assert "1 errored" not in html
    legend = html.split('<div class="legend">', 1)[1].split("</div>", 1)[0]
    assert legend == "".join(
        f'<span><i class="q {outcome.lower()}"></i>{outcome}</span>'
        for outcome in ("Passed", "Failed", "Errored", "Skipped")
    )


def test_results_table_shows_the_rates(experiment: Path) -> None:
    html = render_js(build(experiment), f"renderTable(V,{TABLE})")
    assert "Results by test case" in html
    assert 'style="background:rgb(198,230,222)"' in html
    assert ">100%<" in html
    assert '<span class="ci">(0–79%)</span>' in html
    assert '<span class="ci">(34–100%)</span>' in html


def test_test_cases_link_to_the_results(experiment: Path) -> None:
    html = render_js(build(experiment), "renderPanel(V,{selected:'C-1'})")
    assert 'data-goto-case="T-1" data-goto-criterion="C-1"' in html
    assert 'data-goto-case="T-2" data-goto-criterion="C-1"' in html


def test_measured_numbers_show_as_bars_beside_the_score_and_pass_mark(
    experiment: Path,
) -> None:
    """The pass mark applies to the score, so it shows beside the score and on no bar."""
    records = [
        grader_record(
            "T-1",
            1,
            "C-1",
            0.73,
            threshold=0.8,
            measurements={"applicable": 0.89, "satisfied": 0.73},
        )
    ]
    html = open_case(build(experiment, records), "T-1")
    assert "Applicable" in html
    assert "Satisfied" in html
    assert "Pass mark" in html
    assert "≥ 0.80" in html
    assert 'style="width:89%"' in html
    assert 'style="width:73%"' in html
    assert 'Score <b class="mono">0.73</b>' in html
    measures = html.split('<div class="measures">', 1)[1].split(
        '<p class="n mnote">', 1
    )[0]
    assert "ci-tg" not in measures
    assert '<p class="n mnote">scored</p>' in html


def test_a_result_with_no_verdict_shows_its_numbers_without_a_pass_mark(
    experiment: Path,
) -> None:
    """A pass mark beside no score would read as a verdict the grader did not reach."""
    records = [
        grader_record(
            "T-1",
            1,
            "C-1",
            "errored",
            threshold=0.8,
            measurements={"applicable": 0.49, "satisfied": 0.87},
        )
    ]
    html = open_case(build(experiment, records), "T-1")
    assert 'style="width:49%"' in html
    assert "No score" in html
    assert "Pass mark" not in html
    assert "ci-tg" not in html
    assert '<p class="n mnote">errored</p>' in html


def test_a_grader_that_measures_nothing_still_shows_its_reason(
    experiment: Path,
) -> None:
    html = open_case(build(experiment), "T-1")
    assert "Applicable" not in html
    assert '<p class="why">scored</p>' in html


def test_trial_shows_its_conversation(experiment: Path) -> None:
    save_trial_traces(
        experiment.parents[2],
        "T-1-1",
        [turn_trace(1, "Plan my trip", "Here is a plan")],
    )
    html = open_case(build(experiment), "T-1")
    assert 'class="trow on" data-trial="T-1:1"' in html
    assert 'data-trial="T-1:2"' in html
    assert "Plan my trip" in html
    assert "Here is a plan" in html
    assert "Reached its goal · 1 turn<" in html
    assert '<span class="tn">Turn 1</span>' in html


def test_skipped_tab_names_each_criterion_and_its_reason(tmp_path: Path) -> None:
    extra = ["C-4", "C-5", "C-6", "C-7"]
    records = [
        grader_record("T-1", 1, cid, "skipped", reason=f"{cid} has no tool calls.")
        for cid in ["C-3", *extra]
    ]
    experiment = write_experiment(
        tmp_path / "experiment",
        records,
        extra_criteria=extra,
        stop_reasons={"T-1-1": "max_turns"},
    )
    html = open_case(build(experiment, records), "T-1")
    assert "Ended early." in html
    assert "These criteria did not apply in this trial." in html
    for cid in ["C-3", *extra]:
        assert f"{cid} has no tool calls." in html
