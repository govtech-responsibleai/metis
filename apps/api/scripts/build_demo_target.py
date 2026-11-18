"""Build the demo Target files of the API from an engine example and one finished Experiment.

Run it again after a new run of the example, or after the example changes:

    uv run python apps/api/scripts/build_demo_target.py \
        --example packages/engine/examples/http-agentic_eval_toyapp-workshop-lite/specification \
        --experiment evaluations/experiments/toyapp-workshop-lite-<timestamp>

The Experiment needs its report, so run `metis insights report` on it first. The script keeps
only the files that the web app reads, and it replaces each session id with a made-up id.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from metis.api.demo import DEMO_FILES, EXPERIMENT, INTERVIEW
from metis.api.store import FILES
from metis.core import execution_layout
from metis.core.target_binding import TargetBinding
from metis.wizard import (
    ConnectionTransport,
    InterviewContext,
    InterviewState,
    Specification,
    TargetConnection,
)

KEPT = (
    execution_layout.LOGS / execution_layout.EVENTS_FILE,
    execution_layout.RESULTS,
    execution_layout.REPORT_JSON,
    execution_layout.REPORT_HTML,
)
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


def build(example: Path, experiment: Path, output: Path) -> None:
    shutil.rmtree(output, ignore_errors=True)
    (output / FILES).mkdir(parents=True)
    (output / INTERVIEW).write_text(
        json.dumps(_interview(example), indent=1) + "\n", encoding="utf-8"
    )
    for fixture in sorted((example / "fixtures").iterdir()):
        shutil.copyfile(fixture, output / FILES / fixture.name)

    folder = output / EXPERIMENT / experiment.name
    shutil.copytree(
        experiment / execution_layout.SPECIFICATION_DIR,
        folder / execution_layout.SPECIFICATION_DIR,
    )
    texts = {
        relative: (experiment / relative).read_text(encoding="utf-8")
        for relative in KEPT
    }
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
