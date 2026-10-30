"""Render the complete Specification as a human-readable review, including dormant Criteria."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from metis.wizard.application.trials import format_trials

if TYPE_CHECKING:
    from metis.wizard.contracts.connection import TargetConnection
    from metis.wizard.domain.specification import Behaviour, Criterion, Specification


def _criterion_lines(criterion: Criterion) -> list[str]:
    measured = criterion.grader_fqn or "not yet matched"
    return [
        f"    - {criterion.description}",
        f"      *measured by:* `{measured}`",
        f"      *parameters:* `{json.dumps(criterion.grader_args, ensure_ascii=False, sort_keys=True)}`",
    ]


def _behaviour_lines(behaviour: Behaviour) -> list[str]:
    mark = "measured" if behaviour.measured else "considered, not measured"

    lines = [f"- **{behaviour.name}** — {behaviour.description}  _({mark})_"]
    for criterion in behaviour.criteria:
        lines.extend(_criterion_lines(criterion))
    if not behaviour.criteria:
        lines.append("    - _no acceptance criteria_")
    return lines


def _connection_lines(
    connection: TargetConnection | None, connection_skipped: bool
) -> list[str]:
    """The target connection section. It is empty in spec-only mode."""
    from metis.wizard.application.connection import (
        TARGET_BINDING_FILE,
        optional_variables,
        required_variables,
    )
    from metis.wizard.contracts.connection import ConnectionStatus

    if connection is None:
        if not connection_skipped:
            return []
        return [
            "## Target connection",
            "",
            "The target binding was not valid, so this export uses the default runner. To add "
            "a binding, run `metis wizard connect --out-dir <experiment root>`.",
            "",
        ]
    required = required_variables(connection.binding)
    optional = optional_variables(connection.binding)
    lines = [
        "## Target connection",
        "",
        f"- Transport: {connection.transport.value}",
        f"- Binding: `{TARGET_BINDING_FILE}`",
        "- Status: "
        + (
            "checked against the target"
            if connection.status is ConnectionStatus.CHECKED
            else "not checked against the target"
        ),
    ]
    if required:
        lines.append(f"- Set before a run: {', '.join(f'`{n}`' for n in required)}")
    if optional:
        lines.append(f"- Optional: {', '.join(f'`{n}`' for n in optional)}")
    return [*lines, ""]


def render_review(
    specification: Specification,
    experiment_id: str,
    *,
    connection: TargetConnection | None = None,
    connection_skipped: bool = False,
) -> str:
    """Render the review. A run-mode export adds a target connection section."""
    target = specification.target
    out: list[str] = [
        f"# {target.name} — evaluation review",
        "",
        f"Experiment id: `{experiment_id}`",
        "",
        "## What it is",
        "",
        target.description,
        "",
        "## Who uses it",
        "",
        target.users,
        "",
    ]

    if target.detail:
        out += ["## How it works", "", target.detail, ""]

    out += ["## What should be true", ""]
    for feature in specification.features:
        out += [f"### {feature.id}: {feature.name}", ""]
        if feature.description:
            out += [feature.description, ""]
        for behaviour in feature.behaviours:
            out += _behaviour_lines(behaviour)
        out += [""]

    out += ["## Personas", ""]
    for persona in specification.personas:
        out += [f"- **{persona.name}** (`{persona.id}`) — {persona.description}"]
    if not specification.personas:
        out += ["_none_"]
    out += [""]

    out += ["## Test Cases", ""]
    for task in specification.tasks:
        scenario = specification.scenario(task.scenario_ref)
        out += [
            f"### {task.id}",
            "",
            scenario.description if scenario else "",
            "",
            f"- Scenario: {task.scenario_ref}",
            f"- Persona: {task.persona_ref}",
            f"- Behaviours: {', '.join(task.behaviour_refs)}",
            f"- Trials: {task.num_trials}",
            f"- Files: {', '.join(task.fixtures)}",
            "",
        ]

    # The same calculation the interview footer shows, so the document and the screen the
    # user decided on cannot disagree.
    out += [
        "## Trials",
        "",
        format_trials(specification.trial_count()),
        "",
    ]
    out += _connection_lines(connection, connection_skipped)

    not_measured = [
        b
        for feature in specification.features
        for b in feature.behaviours
        if not b.measured
    ]
    if not_measured:
        out += [
            "## Considered, not measured",
            "",
            "These were drafted and deliberately left out. They are kept as the record of "
            "what was decided against, not as an oversight.",
            "",
        ]
        out += [f"- **{b.name}** — {b.description}" for b in not_measured]
        out += [""]

    return "\n".join(out)


def write_review(specification: Specification, experiment_id: str, path: Path) -> str:
    text = render_review(specification, experiment_id)
    # encoding is explicit — write_text() otherwise falls back to the platform
    # locale encoding (cp1252 on Windows), and this text is arbitrary user- or
    # model-authored prose (target.description, criteria, personas) that can
    # contain any character.
    Path(path).write_text(text, encoding="utf-8")
    return text
