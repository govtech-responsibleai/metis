"""Build the demo Target files of the API from an engine example and one finished Experiment.

Run it again after a new run of the example, or after the example changes:

    uv run python apps/api/scripts/build_demo_target.py \
        --example packages/engine/examples/http-agentic_eval_toyapp-workshop-lite/specification \
        --experiment evaluations/experiments/toyapp-workshop-lite-<timestamp>

The Experiment needs its report, so run `metis insights report` on it first. The script keeps
only the files that the web app reads, and it replaces each session id with a made-up id.
The Experiment can have more trials than the example plans. The script then keeps only the
planned trials, and it builds the report again from them, with the conversations of the
first report.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from metis.api.demo import DEMO_FILES, EXPERIMENTS, INTERVIEW, RECORD
from metis.api.store import FILES
from metis.core import execution_layout
from metis.core.report import Report
from metis.core.reporting import EvaluationResults
from metis.core.target_binding import TargetBinding
from metis.insights import build_report
from metis.insights._report_page import render_report_page
from metis.wizard import (
    ConnectionTransport,
    InterviewContext,
    InterviewState,
    Specification,
    TargetConnection,
)

EVENTS = execution_layout.LOGS / execution_layout.EVENTS_FILE
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _interview(example: Path) -> dict[str, Any]:
    document = _load(example / "specification.yaml")
    binding = TargetBinding.model_validate(_load(example / document["target_binding"]))
    state = InterviewState(
        specification=Specification.model_validate(document),
        context=InterviewContext(
            connection=TargetConnection(
                transport=ConnectionTransport(binding.transport), binding=binding
            )
        ),
        behaviours_confirmed=True,
        confirmed=True,
    )
    return {
        "title": state.specification.target.name,
        "state": state.model_dump(mode="json"),
        "transcript": [],
    }


def _made_up_ids(texts: list[str]) -> dict[str, str]:
    found = sorted({match for text in texts for match in _UUID.findall(text)})
    return {
        real: f"00000000-0000-4000-8000-{number:012d}"
        for number, real in enumerate(found, start=1)
    }


def _planned(specification: dict[str, Any]) -> set[tuple[str, int]]:
    return {
        (task["id"], index)
        for task in specification["tasks"]
        for index in range(1, task["num_trials"] + 1)
    }


def _experiment_files(example: Path, experiment: Path) -> dict[PurePosixPath, str]:
    """The event log, the results and the report of the planned trials of ``experiment``."""
    specification = _load(example / "specification.yaml")
    planned = _planned(specification)
    results = EvaluationResults.load_file(experiment / execution_layout.RESULTS)
    results.records = [
        record
        for record in results.records
        if (record.task_id, record.trial_index) in planned
    ]
    first_report = json.loads(
        (experiment / execution_layout.REPORT_JSON).read_text(encoding="utf-8")
    )
    trials = [
        item
        for item in first_report["trials"]["items"]
        if (item["task_id"], item["trial_index"]) in planned
    ]
    report = build_report(
        specification, results, timestamp=first_report["date"], trial_outcomes=trials
    )

    kept = {item["id"] for item in trials}
    events = []
    for line in (experiment / EVENTS).read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event["trial"] is not None and event["trial"] not in kept:
            continue
        event["seq"] = len(events) + 1
        if "total" in event:
            event["total"] = len(kept)
        events.append(json.dumps(event, separators=(",", ":")) + "\n")
    return {
        EVENTS: "".join(events),
        execution_layout.RESULTS: results.model_dump_json(indent=1) + "\n",
        execution_layout.REPORT_JSON: json.dumps(
            Report.model_validate(report).model_dump(by_alias=True),
            indent=1,
            default=str,
        )
        + "\n",
        execution_layout.REPORT_HTML: render_report_page(
            report, title=report["target"]
        ),
    }


def build(example: Path, experiment: Path, output: Path) -> None:
    shutil.rmtree(output, ignore_errors=True)
    (output / INTERVIEW / FILES).mkdir(parents=True)
    (output / INTERVIEW / RECORD).write_text(
        json.dumps(_interview(example), indent=1) + "\n", encoding="utf-8"
    )
    for fixture in sorted((example / "fixtures").iterdir()):
        shutil.copyfile(fixture, output / INTERVIEW / FILES / fixture.name)

    folder = output / EXPERIMENTS / experiment.name
    shutil.copytree(example, folder / execution_layout.SPECIFICATION_DIR)
    texts = _experiment_files(example, experiment)
    ids = _made_up_ids(list(texts.values()))
    for relative, text in texts.items():
        path = folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            _UUID.sub(lambda match: ids[match.group()], text), encoding="utf-8"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the demo Target files.")
    parser.add_argument("--example", type=Path, required=True)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEMO_FILES)
    arguments = parser.parse_args()
    build(arguments.example, arguments.experiment, arguments.output)


if __name__ == "__main__":
    main()
