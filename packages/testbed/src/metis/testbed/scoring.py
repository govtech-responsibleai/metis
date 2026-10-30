"""Align and score generated Wizard Specifications against references."""

from __future__ import annotations

import json
import math
from typing import TYPE_CHECKING

from metis.testbed.contracts import (
    ItemMatch,
    LevelScore,
    Similarity,
    SpecificationScores,
)
from metis.testbed.embeddings import named_text as _text

if TYPE_CHECKING:
    from metis.core.profile import Criterion
    from metis.core.specification import Specification


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _optimal_pairs(scores: list[list[float]]) -> list[tuple[int, int]]:
    """Return a maximum-weight one-to-one assignment for a rectangular matrix."""
    if not scores or not scores[0]:
        return []
    rows = len(scores)
    columns = len(scores[0])
    transposed = rows > columns
    matrix = (
        [[scores[row][column] for row in range(rows)] for column in range(columns)]
        if transposed
        else scores
    )
    n = len(matrix)
    m = len(matrix[0])
    potentials_rows = [0.0] * (n + 1)
    potentials_columns = [0.0] * (m + 1)
    column_row = [0] * (m + 1)
    previous_column = [0] * (m + 1)

    for row in range(1, n + 1):
        column_row[0] = row
        minimum = [math.inf] * (m + 1)
        used = [False] * (m + 1)
        column = 0
        while True:
            used[column] = True
            current_row = column_row[column]
            delta = math.inf
            next_column = 0
            for candidate in range(1, m + 1):
                if used[candidate]:
                    continue
                cost = 1.0 - matrix[current_row - 1][candidate - 1]
                reduced = (
                    cost - potentials_rows[current_row] - potentials_columns[candidate]
                )
                if reduced < minimum[candidate]:
                    minimum[candidate] = reduced
                    previous_column[candidate] = column
                if minimum[candidate] < delta:
                    delta = minimum[candidate]
                    next_column = candidate
            for candidate in range(m + 1):
                if used[candidate]:
                    potentials_rows[column_row[candidate]] += delta
                    potentials_columns[candidate] -= delta
                else:
                    minimum[candidate] -= delta
            column = next_column
            if column_row[column] == 0:
                break
        while True:
            previous = previous_column[column]
            column_row[column] = column_row[previous]
            column = previous
            if column == 0:
                break

    pairs = [
        (row - 1, column - 1)
        for column, row in enumerate(column_row[1:], start=1)
        if row
    ]
    if transposed:
        return [(column, row) for row, column in pairs]
    return pairs


def _level(
    reference_ids: list[str],
    generated_ids: list[str],
    scores: list[list[float]],
    details: list[list[dict[str, float | None]]] | None = None,
) -> LevelScore:
    pairs = _optimal_pairs(scores)
    paired_reference = {reference for reference, _ in pairs}
    paired_generated = {generated for _, generated in pairs}
    matches = [
        ItemMatch(
            reference_id=reference_ids[reference],
            generated_id=generated_ids[generated],
            similarity=_clamp(scores[reference][generated]),
            details=details[reference][generated] if details else {},
        )
        for reference, generated in pairs
    ]
    denominator = max(len(reference_ids), len(generated_ids))
    return LevelScore(
        similarity=(sum(match.similarity for match in matches) / denominator)
        if denominator
        else None,
        coverage=(len(matches) / len(reference_ids)) if reference_ids else None,
        precision=(len(matches) / len(generated_ids)) if generated_ids else None,
        reference_count=len(reference_ids),
        generated_count=len(generated_ids),
        matches=matches,
        missing=[
            item
            for index, item in enumerate(reference_ids)
            if index not in paired_reference
        ],
        additional=[
            item
            for index, item in enumerate(generated_ids)
            if index not in paired_generated
        ],
    )


def _feature_score(
    reference: Specification, generated: Specification, similarity: Similarity
) -> LevelScore:
    reference_text = [_text(item.name, item.description) for item in reference.features]
    generated_text = [_text(item.name, item.description) for item in generated.features]
    return _level(
        [item.id for item in reference.features],
        [item.id for item in generated.features],
        similarity.matrix(reference_text, generated_text),
    )


def _behaviour_score(
    reference: Specification,
    generated: Specification,
    feature_matches: list[ItemMatch],
    similarity: Similarity,
) -> LevelScore:
    reference_by_id = {item.id: item for item in reference.features}
    generated_by_id = {item.id: item for item in generated.features}
    matches: list[ItemMatch] = []
    matched_reference: set[str] = set()
    matched_generated: set[str] = set()

    for feature_match in feature_matches:
        reference_feature = reference_by_id[feature_match.reference_id]
        generated_feature = generated_by_id[feature_match.generated_id]
        reference_text = [
            _text(item.name, item.description) for item in reference_feature.behaviours
        ]
        generated_text = [
            _text(item.name, item.description) for item in generated_feature.behaviours
        ]
        text_scores = similarity.matrix(reference_text, generated_text)
        combined: list[list[float]] = []
        details: list[list[dict[str, float | None]]] = []
        for row, reference_behaviour in enumerate(reference_feature.behaviours):
            score_row = []
            detail_row = []
            for column, generated_behaviour in enumerate(generated_feature.behaviours):
                measured = float(
                    reference_behaviour.measured == generated_behaviour.measured
                )
                score_row.append((text_scores[row][column] + measured) / 2)
                detail_row.append(
                    {"text": text_scores[row][column], "measured": measured}
                )
            combined.append(score_row)
            details.append(detail_row)
        local = _level(
            [item.id for item in reference_feature.behaviours],
            [item.id for item in generated_feature.behaviours],
            combined,
            details,
        )
        matches.extend(local.matches)
        matched_reference.update(match.reference_id for match in local.matches)
        matched_generated.update(match.generated_id for match in local.matches)

    reference_items = reference.behaviours()
    generated_items = generated.behaviours()
    denominator = max(len(reference_items), len(generated_items))
    return LevelScore(
        similarity=(sum(item.similarity for item in matches) / denominator)
        if denominator
        else None,
        coverage=(len(matches) / len(reference_items)) if reference_items else None,
        precision=(len(matches) / len(generated_items)) if generated_items else None,
        reference_count=len(reference_items),
        generated_count=len(generated_items),
        matches=matches,
        missing=[
            item.id for item in reference_items if item.id not in matched_reference
        ],
        additional=[
            item.id for item in generated_items if item.id not in matched_generated
        ],
    )


def _criterion_score(
    reference: Specification,
    generated: Specification,
    behaviour_matches: list[ItemMatch],
    similarity: Similarity,
) -> LevelScore:
    reference_by_id = {item.id: item for item in reference.behaviours()}
    generated_by_id = {item.id: item for item in generated.behaviours()}
    matches: list[ItemMatch] = []
    matched_reference: set[str] = set()
    matched_generated: set[str] = set()

    for behaviour_match in behaviour_matches:
        reference_behaviour = reference_by_id[behaviour_match.reference_id]
        generated_behaviour = generated_by_id[behaviour_match.generated_id]
        local = _level(
            [item.id for item in reference_behaviour.criteria],
            [item.id for item in generated_behaviour.criteria],
            similarity.matrix(
                [
                    _text(item.name, item.description)
                    for item in reference_behaviour.criteria
                ],
                [
                    _text(item.name, item.description)
                    for item in generated_behaviour.criteria
                ],
            ),
        )
        matches.extend(local.matches)
        matched_reference.update(match.reference_id for match in local.matches)
        matched_generated.update(match.generated_id for match in local.matches)

    reference_items = [item for b in reference.behaviours() for item in b.criteria]
    generated_items = [item for b in generated.behaviours() for item in b.criteria]
    denominator = max(len(reference_items), len(generated_items))
    return LevelScore(
        similarity=(sum(item.similarity for item in matches) / denominator)
        if denominator
        else None,
        coverage=(len(matches) / len(reference_items)) if reference_items else None,
        precision=(len(matches) / len(generated_items)) if generated_items else None,
        reference_count=len(reference_items),
        generated_count=len(generated_items),
        matches=matches,
        missing=[
            item.id for item in reference_items if item.id not in matched_reference
        ],
        additional=[
            item.id for item in generated_items if item.id not in matched_generated
        ],
    )


def _criterion_map(specification: Specification) -> dict[str, Criterion]:
    return {
        criterion.id: criterion
        for behaviour in specification.behaviours()
        for criterion in behaviour.criteria
    }


def _grader_score(
    reference: Specification,
    generated: Specification,
    criterion_matches: list[ItemMatch],
) -> LevelScore:
    reference_criteria = _criterion_map(reference)
    generated_criteria = _criterion_map(generated)
    reference_ids = [
        item.id for item in reference_criteria.values() if item.grader_fqn is not None
    ]
    generated_ids = [
        item.id for item in generated_criteria.values() if item.grader_fqn is not None
    ]
    if not reference_ids:
        return LevelScore(
            similarity=None,
            coverage=None,
            precision=None,
            reference_count=0,
            generated_count=len(generated_ids),
            additional=generated_ids,
        )
    aligned = {item.reference_id: item.generated_id for item in criterion_matches}
    matches: list[ItemMatch] = []
    for reference_id in reference_ids:
        generated_id = aligned.get(reference_id)
        if generated_id is None:
            continue
        reference_grader = reference_criteria[reference_id]
        generated_grader = generated_criteria[generated_id]
        if generated_grader.grader_fqn is None:
            continue
        fqn = float(reference_grader.grader_fqn == generated_grader.grader_fqn)
        arguments = float(reference_grader.grader_args == generated_grader.grader_args)
        matches.append(
            ItemMatch(
                reference_id=reference_id,
                generated_id=generated_id,
                similarity=(fqn + arguments) / 2,
                details={"fqn": fqn, "arguments": arguments},
            )
        )
    matched_reference = {item.reference_id for item in matches}
    matched_generated = {item.generated_id for item in matches}
    denominator = max(len(reference_ids), len(generated_ids))
    return LevelScore(
        similarity=(sum(item.similarity for item in matches) / denominator)
        if denominator
        else None,
        coverage=(len(matches) / len(reference_ids)) if reference_ids else None,
        precision=(len(matches) / len(generated_ids)) if generated_ids else None,
        reference_count=len(reference_ids),
        generated_count=len(generated_ids),
        matches=matches,
        missing=[item for item in reference_ids if item not in matched_reference],
        additional=[item for item in generated_ids if item not in matched_generated],
    )


def _jaccard(left: set[str], right: set[str], *, unresolved: int = 0) -> float:
    denominator = len(left | right) + unresolved
    return len(left & right) / denominator if denominator else 1.0


def _task_score(
    reference: Specification,
    generated: Specification,
    behaviour_matches: list[ItemMatch],
    similarity: Similarity,
) -> LevelScore:
    reference_scenarios = {item.id: item for item in reference.scenarios}
    generated_scenarios = {item.id: item for item in generated.scenarios}
    reference_personas = {item.id: item for item in reference.personas}
    generated_personas = {item.id: item for item in generated.personas}
    behaviour_map = {item.reference_id: item.generated_id for item in behaviour_matches}

    scenario_text = [
        _text(
            reference_scenarios[task.scenario_ref].name,
            reference_scenarios[task.scenario_ref].description,
        )
        for task in reference.tasks
    ]
    generated_scenario_text = [
        _text(
            generated_scenarios[task.scenario_ref].name,
            generated_scenarios[task.scenario_ref].description,
        )
        for task in generated.tasks
    ]
    persona_text = [
        _text(
            reference_personas[task.persona_ref].name,
            reference_personas[task.persona_ref].description,
        )
        for task in reference.tasks
    ]
    generated_persona_text = [
        _text(
            generated_personas[task.persona_ref].name,
            generated_personas[task.persona_ref].description,
        )
        for task in generated.tasks
    ]
    scenario_scores = similarity.matrix(scenario_text, generated_scenario_text)
    persona_scores = similarity.matrix(persona_text, generated_persona_text)
    scores: list[list[float]] = []
    details: list[list[dict[str, float | None]]] = []
    settings = (
        "num_trials",
        "max_turns",
        "timeout_minutes",
        "response_wait_ms",
        "max_run_retries",
    )
    for row, reference_task in enumerate(reference.tasks):
        score_row = []
        detail_row = []
        for column, generated_task in enumerate(generated.tasks):
            mapped_behaviours = {
                behaviour_map[item]
                for item in reference_task.behaviour_refs
                if item in behaviour_map
            }
            unresolved = len(reference_task.behaviour_refs) - len(mapped_behaviours)
            behaviour_score = _jaccard(
                mapped_behaviours,
                set(generated_task.behaviour_refs),
                unresolved=unresolved,
            )
            fixture_score = _jaccard(
                set(reference_task.fixtures), set(generated_task.fixtures)
            )
            setting_score = sum(
                getattr(reference_task, name) == getattr(generated_task, name)
                for name in settings
            ) / len(settings)
            components = {
                "scenario": scenario_scores[row][column],
                "persona": persona_scores[row][column],
                "behaviours": behaviour_score,
                "fixtures": fixture_score,
                "settings": setting_score,
            }
            score_row.append(sum(components.values()) / len(components))
            detail_row.append(components)
        scores.append(score_row)
        details.append(detail_row)
    return _level(
        [item.id for item in reference.tasks],
        [item.id for item in generated.tasks],
        scores,
        details,
    )


def compare_specifications(
    generated: Specification,
    reference: Specification,
    similarity: Similarity,
) -> SpecificationScores:
    """Return auditable scores at every Specification curation level."""
    features = _feature_score(reference, generated, similarity)
    behaviours = _behaviour_score(reference, generated, features.matches, similarity)
    criteria = _criterion_score(reference, generated, behaviours.matches, similarity)
    graders = _grader_score(reference, generated, criteria.matches)
    tasks = _task_score(reference, generated, behaviours.matches, similarity)
    return SpecificationScores(
        features=features,
        behaviours=behaviours,
        criteria=criteria,
        graders=graders,
        tasks=tasks,
    )


def grader_identity(criterion: Criterion) -> str:
    """Return the stable text used when a report shows one Grader."""
    return json.dumps(
        {"fqn": criterion.grader_fqn, "arguments": criterion.grader_args},
        sort_keys=True,
    )


__all__ = ["compare_specifications", "grader_identity"]
