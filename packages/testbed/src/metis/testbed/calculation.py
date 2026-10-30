"""Score a specification folder using reusable local embeddings."""

from __future__ import annotations

from itertools import combinations
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from metis.testbed.contracts import SpecificationScores
from metis.testbed.embeddings import (
    BehaviourText,
    CachedSimilarity,
    behaviour_texts,
    ensure_embeddings,
    text_hash,
)
from metis.testbed.scoring import compare_specifications

if TYPE_CHECKING:
    from metis.core.specification import Specification
    from metis.testbed.contracts import ItemMatch
    from metis.testbed.embeddings import TextEmbedder


TESTBED_ROOT = Path(__file__).resolve().parents[3]
RESULTS_ROOT = TESTBED_ROOT / "results"


def score_directory(path: Path) -> Path:
    """Keep reports under results and give external inputs a distinct folder."""
    path = path.resolve()
    if path.is_relative_to(RESULTS_ROOT.resolve()):
        return path.parent
    evals = TESTBED_ROOT / "wizard" / "cases"
    if path.is_relative_to(evals):
        return RESULTS_ROOT / "scores" / path.relative_to(evals).parent
    return RESULTS_ROOT / "scores" / f"{path.parent.name}-{text_hash(str(path))[:12]}"


class BehaviourNeighbour(BaseModel):
    behaviour_id: str
    neighbour_id: str
    similarity: float


class BehaviourMatrix(BaseModel):
    ids: list[str]
    names: list[str]
    feature_ids: list[str]
    matrix: list[list[float]]
    pair_count: int
    nearest_neighbours: list[BehaviourNeighbour]
    mean_nn_similarity: float | None


class PairDifference(BaseModel):
    reference_ids: tuple[str, str]
    generated_ids: tuple[str, str]
    reference_similarity: float
    generated_similarity: float
    error: float


class BehaviourAnalysis(BaseModel):
    reference: BehaviourMatrix
    generated: BehaviourMatrix | None = None
    pairs: list[PairDifference] = []
    difference_error: float | None = None


class FolderScores(BaseModel):
    specification: str
    specification_hash: str
    reference: str | None
    reference_hash: str | None
    embedding_model: str
    endpoint_hash: str
    pair_scope: str = "All distinct behaviour pairs within each specification, including pairs across features."
    scores: SpecificationScores | None
    behaviour_analysis: dict[BehaviourText, BehaviourAnalysis]


def _matrix(
    specification: Specification, version: BehaviourText, similarity: CachedSimilarity
) -> BehaviourMatrix:
    texts = behaviour_texts(specification, version)
    values = similarity.matrix(list(texts.values()), list(texts.values()))
    ids = list(texts)
    neighbours: list[BehaviourNeighbour] = []
    if len(ids) > 1:
        for i, identifier in enumerate(ids):
            closest = max(
                (j for j in range(len(ids)) if j != i), key=lambda j: values[i][j]
            )
            neighbours.append(
                BehaviourNeighbour(
                    behaviour_id=identifier,
                    neighbour_id=ids[closest],
                    similarity=values[i][closest],
                )
            )
    return BehaviourMatrix(
        ids=ids,
        names=[b.name for b in specification.behaviours()],
        feature_ids=[f.id for f in specification.features for _ in f.behaviours],
        matrix=values,
        pair_count=len(ids) * (len(ids) - 1) // 2,
        nearest_neighbours=neighbours,
        mean_nn_similarity=sum(item.similarity for item in neighbours) / len(neighbours)
        if neighbours
        else None,
    )


def _difference(
    reference: BehaviourMatrix, generated: BehaviourMatrix, matches: list[ItemMatch]
) -> BehaviourAnalysis:
    ref_index = {item: index for index, item in enumerate(reference.ids)}
    gen_index = {item: index for index, item in enumerate(generated.ids)}
    pairs: list[PairDifference] = []
    for a, b in combinations(matches, 2):
        rs = reference.matrix[ref_index[a.reference_id]][ref_index[b.reference_id]]
        gs = generated.matrix[gen_index[a.generated_id]][gen_index[b.generated_id]]
        pairs.append(
            PairDifference(
                reference_ids=(a.reference_id, b.reference_id),
                generated_ids=(a.generated_id, b.generated_id),
                reference_similarity=rs,
                generated_similarity=gs,
                error=abs(rs - gs),
            )
        )
    return BehaviourAnalysis(
        reference=reference,
        generated=generated,
        pairs=pairs,
        difference_error=sum(pair.error for pair in pairs) / len(pairs)
        if pairs
        else None,
    )


def calculate_scores(
    path: Path,
    *,
    reference: Path | None = None,
    embedder: TextEmbedder | None = None,
    report_directory: Path | None = None,
) -> FolderScores:
    """Score one folder, or compare it with an explicitly supplied reference."""
    embedded = ensure_embeddings(
        path, embedder=embedder, include_metrics=reference is not None
    )
    baseline = (
        ensure_embeddings(reference, embedder=embedder, include_metrics=True)
        if reference is not None
        else embedded
    )
    similarity = CachedSimilarity(baseline.cache, embedded.cache)
    scores = (
        compare_specifications(
            embedded.specification, baseline.specification, similarity
        )
        if reference is not None
        else None
    )
    analyses: dict[BehaviourText, BehaviourAnalysis] = {}
    for version in BehaviourText:
        matrix = _matrix(baseline.specification, version, similarity)
        analyses[version] = (
            _difference(
                matrix,
                _matrix(embedded.specification, version, similarity),
                scores.behaviours.matches,
            )
            if scores is not None
            else BehaviourAnalysis(reference=matrix)
        )
    result = FolderScores(
        specification=str(embedded.path),
        specification_hash=text_hash(embedded.path.read_text(encoding="utf-8")),
        reference=str(baseline.path) if reference is not None else None,
        reference_hash=text_hash(baseline.path.read_text(encoding="utf-8"))
        if reference is not None
        else None,
        embedding_model=embedded.cache.model,
        endpoint_hash=embedded.cache.endpoint_hash,
        scores=scores,
        behaviour_analysis=analyses,
    )
    destination = report_directory or score_directory(embedded.path)
    destination.mkdir(parents=True, exist_ok=True)
    report = destination / embedded.path.name
    report.with_suffix(".scores.json").write_text(
        result.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    report.with_suffix(".scores.md").write_text(render_scores(result), encoding="utf-8")
    return result


def render_scores(result: FolderScores) -> str:
    """Show reference similarity and generated differences as separate values."""

    def value(number: float | None) -> str:
        return "—" if number is None else f"{number:.3f}"

    lines = [
        "# Specification scores",
        "",
        f"Specification: `{result.specification}`",
        "",
        f"Embedding model: `{result.embedding_model}`",
        "",
        result.pair_scope,
        "",
        "Mean nearest-neighbour (NN) similarity averages each behaviour's highest similarity to another behaviour in the same specification. Lower means less overlap with the closest neighbours. Self-comparisons are excluded. Fewer than two behaviours gives no NN score. Compare behaviour counts alongside scores; this does not establish requirement coverage.",
        "",
    ]
    if result.scores is not None:
        lines += [
            f"Reference: `{result.reference}`",
            "",
            "| Metric | Similarity | Coverage | Precision |",
            "|---|---:|---:|---:|",
        ]
        for level in ("features", "behaviours", "criteria", "graders", "tasks"):
            score = getattr(result.scores, level)
            lines.append(
                f"| {level} | {value(score.similarity)} | {value(score.coverage)} | {value(score.precision)} |"
            )
    for version, analysis in result.behaviour_analysis.items():
        lines += [
            "",
            f"## {version}",
            "",
            f"Reference mean NN similarity: {value(analysis.reference.mean_nn_similarity)} ({len(analysis.reference.ids)} behaviours).",
            "",
        ]
        if analysis.generated is not None:
            lines += [
                f"Generated mean NN similarity: {value(analysis.generated.mean_nn_similarity)} ({len(analysis.generated.ids)} behaviours).",
                "",
                f"Difference error: {value(analysis.difference_error)}. Compared {len(analysis.pairs)} of {analysis.reference.pair_count} reference pairs. Both text versions use the existing behaviour alignment.",
                "",
                "NN similarity uses each full set independently. Pair difference error uses matched pairs only; lower error means closer reference and generated pair similarities.",
                "",
            ]
        for label, matrix in (
            ("Reference", analysis.reference),
            ("Generated", analysis.generated),
        ):
            if matrix is None:
                continue
            lines += [
                f"### {label} pairs",
                "",
                "| Behaviour | Name | Feature |",
                "|---|---|---|",
            ]
            for identifier, name, feature in zip(
                matrix.ids, matrix.names, matrix.feature_ids, strict=True
            ):
                lines.append(
                    f"| {identifier} | {name.replace('|', '/').replace(chr(10), ' ')} | {feature} |"
                )
            lines += [
                "",
                "| Behaviour | Nearest neighbour | Similarity |",
                "|---|---|---:|",
            ]
            for neighbour in matrix.nearest_neighbours:
                lines.append(
                    f"| {neighbour.behaviour_id} | {neighbour.neighbour_id} | {value(neighbour.similarity)} |"
                )
            lines += [
                "",
                "Ties use the first other behaviour in specification order. Each behaviour contributes once, including both members of a mutual nearest-neighbour pair.",
                "",
                "| Pair | Similarity |",
                "|---|---:|",
            ]
            for i, j in combinations(range(len(matrix.ids)), 2):
                lines.append(
                    f"| {matrix.ids[i]} / {matrix.ids[j]} | {value(matrix.matrix[i][j])} |"
                )
            lines.append("")
        if analysis.pairs:
            lines += [
                "| Reference pair | Generated pair | Reference similarity | Generated similarity | Error |",
                "|---|---|---:|---:|---:|",
            ]
            for pair in analysis.pairs:
                lines.append(
                    f"| {' / '.join(pair.reference_ids)} | {' / '.join(pair.generated_ids)} | {value(pair.reference_similarity)} | {value(pair.generated_similarity)} | {value(pair.error)} |"
                )
    return "\n".join(lines).rstrip() + "\n"


def main(path: Path, reference: Path | None = None) -> None:
    """Calculate scores from PATH; compare outputs only with --reference."""
    from metis.core.console import console

    result = calculate_scores(path, reference=reference)
    specification = Path(result.specification)
    report = (
        score_directory(specification) / specification.with_suffix(".scores.md").name
    )
    console.print(f"Saved: {report}")


if __name__ == "__main__":
    import typer

    typer.run(main)
