"""The sections of report.html, built by the page renderers from report.json."""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from metis.insights._report_page import render_report_page
from tests.fixtures.insights.report_experiment import (
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
