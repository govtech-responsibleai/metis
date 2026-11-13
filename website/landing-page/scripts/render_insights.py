"""Render the two Insights screenshots in the landing page hero.

Writes a small Enterprise AI Assistant experiment to a temporary directory, builds its
report with the real ``metis.insights`` renderer, and captures two views of ``report.html``
with headless Chrome. The scores are illustrative; the page and layout are the product's.

Run from the repository root:

    uv run python landing-page/scripts/render_insights.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml
from PIL import Image

from metis.core import SessionTraces, execution_layout
from metis.core.grading import RecordedResult
from metis.core.reporting import EvaluationResults, GraderRecord
from metis.core.traces import Observation, Trace
from metis.core.trials import TrialConfig, TrialOutcome, TrialRecord
from metis.insights.report import save_report

OUT = Path(__file__).resolve().parents[1] / "public" / "product"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
THRESHOLD = 0.7
TRIALS = 4

# (id, name, description) for each criterion, grouped under its behaviour.
CRITERIA = {
    "B-1": [
        (
            "C-1",
            "Factual accuracy",
            "Every fact in the answer matches the retrieved source.",
        ),
        (
            "C-2",
            "Evidence source suitability",
            "The assistant cites current, authorised sources.",
        ),
        (
            "C-3",
            "Claim support by evidence",
            "Each claim in the answer traces to a retrieved document.",
        ),
        (
            "C-4",
            "Capability limits handling",
            "The assistant says when it cannot find what the user needs.",
        ),
    ],
    "B-2": [
        (
            "C-5",
            "Audience and tone fit",
            "The draft matches the recipient and the requested tone.",
        ),
    ],
}
TASKS = {
    "T-1": ("S-1", "P-1"),
    "T-2": ("S-2", "P-1"),
    "T-3": ("S-3", "P-2"),
}
# Per criterion, the score of each trial of each test case.
SCORES: dict[str, dict[str, list[float]]] = {
    "C-1": {
        "T-1": [0.9, 0.4, 0.8, 0.9],
        "T-2": [0.8, 0.9, 0.5, 0.9],
        "T-3": [0.9, 0.8, 0.9, 0.6],
    },
    "C-2": {
        "T-1": [0.8, 0.5, 0.9, 0.6],
        "T-2": [0.9, 0.8, 0.9, 0.8],
        "T-3": [0.7, 0.9, 0.4, 0.8],
    },
    "C-3": {
        "T-1": [0.9, 0.9, 0.8, 1.0],
        "T-2": [0.9, 0.8, 0.9, 0.9],
        "T-3": [0.8, 0.9, 0.9, 0.7],
    },
    "C-4": {
        "T-1": [1.0, 0.9, 1.0, 0.9],
        "T-2": [0.9, 1.0, 1.0, 0.9],
        "T-3": [0.9, 0.8, 1.0, 1.0],
    },
    "C-5": {
        "T-1": [0.6, 0.8, 0.5, 0.9],
        "T-2": [0.8, 0.9, 0.7, 0.6],
        "T-3": [0.5, 0.8, 0.9, 0.4],
    },
}


def specification() -> dict[str, Any]:
    def behaviour(bid: str, name: str, description: str) -> dict[str, Any]:
        return {
            "id": bid,
            "name": name,
            "description": description,
            "measured": True,
            "criteria": [
                {
                    "id": cid,
                    "name": cname,
                    "description": text,
                    "grader_fqn": "metis.library.graders.CriterionJudgeGrader",
                    "grader_args": {"threshold": THRESHOLD},
                }
                for cid, cname, text in CRITERIA[bid]
            ],
        }

    return {
        "target": {"name": "Enterprise AI Assistant"},
        "features": [
            {
                "id": "F-1",
                "name": "Enterprise search and knowledge retrieval",
                "behaviours": [
                    behaviour(
                        "B-1",
                        "Find and use enterprise information",
                        "Find the authorised internal resource and use it accurately.",
                    )
                ],
            },
            {
                "id": "F-2",
                "name": "Email and messaging assistance",
                "behaviours": [
                    behaviour(
                        "B-2",
                        "Draft replies in the right tone",
                        "Draft replies that fit the thread and the recipient.",
                    )
                ],
            },
        ],
        "personas": [
            {
                "id": "P-1",
                "name": "Collaborative knowledge worker",
                "description": "Shares context and iterates.",
            },
            {
                "id": "P-2",
                "name": "Busy senior manager",
                "description": "Short, direct requests.",
            },
        ],
        "scenarios": [
            {
                "id": "S-1",
                "name": "Draft a reply using a past event record",
                "description": "Reply to the offsite thread.",
            },
            {
                "id": "S-2",
                "name": "Answer a staff HR question",
                "description": "Find the current leave policy.",
            },
            {
                "id": "S-3",
                "name": "Summarise a project update",
                "description": "Summarise the latest status deck.",
            },
        ],
        "tasks": [
            {
                "id": tid,
                "scenario_ref": scenario,
                "persona_ref": persona,
                "num_trials": TRIALS,
                "behaviour_refs": ["B-1", "B-2"],
            }
            for tid, (scenario, persona) in TASKS.items()
        ],
    }


def records() -> list[GraderRecord]:
    out = []
    for cid, by_task in SCORES.items():
        for tid, scores in by_task.items():
            for trial, score in enumerate(scores, start=1):
                outcome = "passed" if score >= THRESHOLD else "failed"
                out.append(
                    GraderRecord(
                        session_id=f"{tid}-{trial}",
                        scenario_id=TASKS[tid][0],
                        task_id=tid,
                        trial_index=trial,
                        criterion_id=cid,
                        grader_fqn="metis.library.graders.CriterionJudgeGrader",
                        grader_args={"threshold": THRESHOLD, "model": "gpt-4o"},
                        results=[
                            RecordedResult(
                                outcome=outcome, score=score, reason="scored"
                            )
                        ],
                    )
                )
    return out


def write_experiment(root: Path) -> EvaluationResults:
    (root / "inputs").mkdir(parents=True)
    (root / "inputs/specification.yaml").write_text(yaml.safe_dump(specification()))
    for tid, (scenario, persona) in TASKS.items():
        for trial in range(1, TRIALS + 1):
            trial_dir = root / "outputs/trials" / f"{tid}-{trial}"
            trial_dir.mkdir(parents=True)
            record = TrialRecord(
                config=TrialConfig(
                    task_id=tid, trial_index=trial, persona=persona, scenario=scenario
                ),
                outcome=TrialOutcome(
                    stop_reason="goal_achieved",
                    simulated_turns_completed=3,
                    duration_seconds=35.0,
                ),
                target_session_id=f"{tid}-{trial}",
            )
            (trial_dir / "record.json").write_text(record.model_dump_json())
            save_conversation(root, f"{tid}-{trial}", CONVERSATIONS[tid])
    return EvaluationResults(run_id="landing-page", records=records())


# The first user message and the target's reply in each test case.
CONVERSATIONS = {
    "T-1": (
        "Help me reply to Priya's thread about the offsite. What did we decide last year?",
        "Last year's offsite deck shows the team chose Sentosa with 42 attendees.",
    ),
    "T-2": (
        "How many days of family care leave can I take this year?",
        "The current leave policy allows six days of family care leave a year.",
    ),
    "T-3": (
        "Summarise the latest status update for the data platform project.",
        "The migration is two weeks behind; the team expects to finish in March.",
    ),
}


def save_conversation(root: Path, session_id: str, turn: tuple[str, str]) -> None:
    """Save one turn where `metis engine evaluate` puts a trial session's traces."""
    root_obs = Observation(
        id="o1", trace_id="t1", type="SPAN", input=turn[0], output=turn[1]
    )
    trace = Trace(id="t1", session_id=session_id, observations=(root_obs,))
    path = root / execution_layout.TRACES / execution_layout.trace_file_name(session_id)
    SessionTraces.from_traces(session_id, [trace]).save(path)


# Appended to report.html: put the page in the state each screenshot shows.
SETUP = {
    "dashboard": """
const tap=q=>document.querySelector(q)?.dispatchEvent(new MouseEvent('click',{bubbles:true}));
tap('[data-view="tree"]');
tap('.treewrap [data-toggle-behaviour="B-1"]');
tap('.treewrap [data-criterion="C-2"]');
// Show only the tree, full width: the Trials card already shows the criterion detail.
const s=document.createElement('style');
s.textContent='.inv{grid-template-columns:1fr!important;height:auto!important}.panel{display:none!important}.treewrap{max-height:none!important;overflow:visible!important}';
document.head.append(s);
document.getElementById('spec')?.scrollIntoView();
""",
    "detail": """
document.querySelector('[data-case="T-1"]')?.click();
""",
}
# Viewport, then the crop box in CSS pixels. The detail drawer opens 80px from the left.
VIEWS = {
    # Just the specification tree, about 16:10, so its labels read in a small card.
    "dashboard": ((1080, 1000), (20, 255, 1060, 905)),
    "detail": ((1380, 820), (80, 0, 1380, 820)),
}


def capture(html: Path, view: str, shot: Path, size: tuple[int, int]) -> None:
    page = html.with_name(f"{view}.html")
    page.write_text(
        html.read_text(encoding="utf-8").replace(
            "</body>",
            f"<script>addEventListener('load',()=>{{{SETUP[view]}}})</script></body>",
        ),
        encoding="utf-8",
    )
    subprocess.run(
        [
            CHROME,
            "--headless=new",
            f"--user-data-dir={html.parent / 'chrome-profile'}",
            "--hide-scrollbars",
            "--force-device-scale-factor=2",
            f"--window-size={size[0]},{size[1]}",
            "--virtual-time-budget=3000",
            f"--screenshot={shot}",
            page.as_uri(),
        ],
        check=True,
        capture_output=True,
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="metis-landing-"))
    try:
        results = write_experiment(root)
        written = save_report(results, root)
        if written is None:
            print("no report written", file=sys.stderr)
            return 1
        html = written[0]
        for view, (size, box) in VIEWS.items():
            shot = root / f"{view}.png"
            capture(html, view, shot, size)
            image = Image.open(shot).convert("RGB").crop(tuple(v * 2 for v in box))
            image = image.resize(
                (1600, round(image.height * 1600 / image.width)), Image.LANCZOS
            )
            image.save(OUT / f"insights-{view}.webp", "WEBP", quality=82, method=6)
            print(OUT / f"insights-{view}.webp", image.size)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
