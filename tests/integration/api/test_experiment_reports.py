"""The experiment report and download routes over experiment folders that the engine wrote."""

from __future__ import annotations

import json
import os
import re
import shutil
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from metis.api.main import create_app
from metis.core import execution_layout
from metis.core.report import Report
from metis.insights.cli import app as insights_app
from tests.fixtures.api._shared import scripted_interview_handler

if TYPE_CHECKING:
    from pathlib import Path

    from tests.fixtures.api.experiments import MakeExperiment


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = create_app(
        interview_handler=scripted_interview_handler(), project_dir=tmp_path
    )
    return TestClient(app)


def _page_data(html: str) -> Report:
    match = re.search(r"const V=(.*?);\n", html)
    assert match is not None
    return Report.model_validate(json.loads(match.group(1)))


@pytest.mark.parametrize("route", ["report", "report/download"])
def test_an_experiment_without_results_has_no_report(
    client: TestClient, make_experiment: MakeExperiment, route: str
) -> None:
    experiment_dir = make_experiment(evaluate=False)

    response = client.get(f"/api/v1/experiments/{experiment_dir.name}/{route}")

    assert response.status_code == 409
    assert response.json()["code"] == "results_missing"
    assert not (experiment_dir / execution_layout.REPORT_JSON).exists()
    assert not (experiment_dir / execution_layout.REPORT_HTML).exists()


def test_the_first_report_request_writes_the_report_files(
    client: TestClient, make_experiment: MakeExperiment
) -> None:
    experiment_dir = make_experiment()
    json_path = experiment_dir / execution_layout.REPORT_JSON
    html_path = experiment_dir / execution_layout.REPORT_HTML
    assert not json_path.exists() and not html_path.exists()

    response = client.get(f"/api/v1/experiments/{experiment_dir.name}/report")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.content == json_path.read_bytes()
    body = Report.model_validate_json(response.content)
    assert _page_data(html_path.read_text(encoding="utf-8")) == body
    assert set(body.criteria) == {"AC-1-1"}
    assert body.criteria["AC-1-1"].pass_ == 2


def test_a_second_request_keeps_a_current_report(
    client: TestClient, make_experiment: MakeExperiment
) -> None:
    experiment_dir = make_experiment()
    client.get(f"/api/v1/experiments/{experiment_dir.name}/report")
    json_path = experiment_dir / execution_layout.REPORT_JSON
    written = json_path.stat().st_mtime_ns

    client.get(f"/api/v1/experiments/{experiment_dir.name}/report")

    assert json_path.stat().st_mtime_ns == written


@pytest.mark.parametrize(
    ("stale_file", "fresh_file"),
    [
        (execution_layout.REPORT_JSON, execution_layout.REPORT_HTML),
        (execution_layout.REPORT_HTML, execution_layout.REPORT_JSON),
    ],
)
def test_a_report_file_older_than_the_results_is_rebuilt(
    client: TestClient,
    make_experiment: MakeExperiment,
    stale_file: str,
    fresh_file: str,
) -> None:
    experiment_dir = make_experiment()
    client.get(f"/api/v1/experiments/{experiment_dir.name}/report")
    stale_path = experiment_dir / stale_file
    results_time = (experiment_dir / execution_layout.RESULTS).stat().st_mtime_ns
    stale_path.write_text("stale", encoding="utf-8")
    older, newer = results_time - 1_000_000_000, results_time + 1_000_000_000
    os.utime(stale_path, ns=(older, older))
    os.utime(experiment_dir / fresh_file, ns=(newer, newer))

    response = client.get(f"/api/v1/experiments/{experiment_dir.name}/report")

    assert response.status_code == 200
    assert Report.model_validate_json(response.content).criteria["AC-1-1"].pass_ == 2
    assert stale_path.read_text(encoding="utf-8") != "stale"


@pytest.mark.parametrize(
    "specification_text", ["features: [\n", "- a list\n- not a mapping\n"]
)
def test_an_unreadable_specification_fails_the_report_build(
    client: TestClient, make_experiment: MakeExperiment, specification_text: str
) -> None:
    experiment_dir = make_experiment()
    (experiment_dir / execution_layout.SPECIFICATION).write_text(
        specification_text, encoding="utf-8"
    )

    response = client.get(f"/api/v1/experiments/{experiment_dir.name}/report")

    assert response.status_code == 409
    assert response.json()["code"] == "report_build_failed"
    assert not (experiment_dir / execution_layout.REPORT_JSON).exists()


def test_a_report_build_failure_keeps_source_values_private(
    client: TestClient, make_experiment: MakeExperiment
) -> None:
    experiment_dir = make_experiment()
    (experiment_dir / execution_layout.SPECIFICATION).write_text(
        "target: {name: {credential: private-source-value}}\n", encoding="utf-8"
    )

    response = client.get(f"/api/v1/experiments/{experiment_dir.name}/report")

    assert response.status_code == 409
    assert response.json()["code"] == "report_build_failed"
    assert "private-source-value" not in response.json()["message"]


def test_report_generation_methods_match(
    client: TestClient, make_experiment: MakeExperiment, tmp_path: Path
) -> None:
    experiment_dir = make_experiment()
    copy = tmp_path / "cli-copy"
    shutil.copytree(experiment_dir, copy)
    cli = CliRunner().invoke(
        insights_app,
        ["report", "--results-file", str(copy / execution_layout.RESULTS)],
    )
    assert cli.exit_code == 0, cli.output

    report = client.get(f"/api/v1/experiments/{experiment_dir.name}/report")
    download = client.get(f"/api/v1/experiments/{experiment_dir.name}/report/download")

    assert report.status_code == 200
    assert report.content == (copy / execution_layout.REPORT_JSON).read_bytes()
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("text/html")
    assert download.headers["content-disposition"] == (
        f'attachment; filename="{experiment_dir.name}-report.html"'
    )
    assert download.content == (copy / execution_layout.REPORT_HTML).read_bytes()


# The client resolves a literal ".." before it sends the request; "%2E%2E" reaches the
# route as "..", which names the experiments folder above the experiment folders.
@pytest.mark.parametrize("experiment_id", ["no-such-experiment", "%2E%2E"])
def test_an_unknown_experiment_id_is_not_found(
    client: TestClient, make_experiment: MakeExperiment, experiment_id: str
) -> None:
    make_experiment()

    response = client.get(f"/api/v1/experiments/{experiment_id}/report")

    assert response.status_code == 404
    assert response.json()["code"] == "experiment_not_found"
