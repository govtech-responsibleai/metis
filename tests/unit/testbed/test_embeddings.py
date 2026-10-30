"""Reusable embedding files and local specification calculations."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
from rich.console import Console
from typer.testing import CliRunner

from metis.core.model_settings import ROLES, ModelRole
from metis.testbed.calculation import calculate_scores, score_directory
from metis.testbed.cli import _print_behaviour_nn, app
from metis.testbed.contracts import EvaluationRequest, WizardState
from metis.testbed.embeddings import (
    BehaviourText,
    CachedSimilarity,
    EmbeddingCache,
    GatewayEmbedder,
    TextEmbedding,
    behaviour_texts,
    ensure_embeddings,
    read_specification,
    text_hash,
)
from metis.testbed.evaluation import OneShotInteraction, run_evaluation

EVALS = Path(__file__).resolve().parents[3] / "packages/testbed/wizard/cases"


class LocalEmbedder:
    model = ROLES[ModelRole.EMBEDDINGS].own_default or ""
    endpoint_hash = "test-endpoint"

    def __init__(self):
        self.calls: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return [
            float(value + 1) for value in hashlib.sha256(text.encode()).digest()[:8]
        ]


@pytest.fixture(autouse=True)
def report_root(tmp_path, monkeypatch):
    monkeypatch.setattr("metis.testbed.calculation.RESULTS_ROOT", tmp_path / "results")


@pytest.fixture
def specification_path(tmp_path):
    path = tmp_path / "reference/specification.yaml"
    path.parent.mkdir()
    shutil.copyfile(EVALS / "billing-support/outputs/specification.yaml", path)
    return path


def test_cache_saves_exact_text_and_reuses_unchanged_inputs(specification_path):
    provider = LocalEmbedder()
    embedded = ensure_embeddings(specification_path, embedder=provider)
    assert specification_path.with_suffix(".embeddings.json").is_file()
    texts = {entry.text for entry in embedded.cache.entries.values()}
    behaviour = "Manage billing requests\nHandle billing requests within the caller’s verified identity and account scope."
    assert behaviour in texts
    context = next(
        text for text in texts if text.startswith("Feature:") and behaviour in text
    )
    assert "Feature: Billing support\n" in context
    assert "Criteria:\nVerify identity before high-risk changes\nGiven" in context
    assert "Keep access within the caller’s account\nGiven" in context
    assert "grader_fqn" not in context
    assert len(provider.calls) == len(set(provider.calls))
    provider.calls.clear()
    ensure_embeddings(specification_path.parent, embedder=provider)
    assert provider.calls == []

    data = yaml.safe_load(specification_path.read_text())
    data["features"][0]["behaviours"][0]["description"] = (
        "Updated behaviour description."
    )
    specification_path.write_text(yaml.safe_dump(data))
    updated = ensure_embeddings(specification_path, embedder=provider)
    assert len(provider.calls) == 2
    assert all("Updated behaviour description." in text for text in provider.calls)
    assert text_hash(behaviour) not in updated.cache.entries


def test_cache_refreshes_when_model_or_endpoint_changes(specification_path):
    provider = LocalEmbedder()
    first = ensure_embeddings(specification_path, embedder=provider)
    for field, value in (
        ("model", "another-model"),
        ("endpoint_hash", "another-endpoint"),
    ):
        provider.calls.clear()
        setattr(provider, field, value)
        ensure_embeddings(specification_path, embedder=provider)
        assert len(provider.calls) == len(first.cache.entries)


def test_interrupted_embedding_run_retains_completed_requests(specification_path):
    class Interrupted(LocalEmbedder):
        def embed(self, text):
            if len(self.calls) == 2:
                raise RuntimeError("Provider unavailable")
            return super().embed(text)

    provider = Interrupted()
    with pytest.raises(RuntimeError, match="Provider unavailable"):
        ensure_embeddings(specification_path, embedder=provider)
    retry = LocalEmbedder()
    embedded = ensure_embeddings(specification_path, embedder=retry)
    assert not set(provider.calls) & set(retry.calls)
    assert len(embedded.cache.entries) == len(provider.calls) + len(retry.calls)


def test_reference_calculation_is_offline_after_embedding(
    specification_path, monkeypatch
):
    provider = LocalEmbedder()
    ensure_embeddings(specification_path, embedder=provider)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    api = MagicMock(side_effect=AssertionError("No API call expected"))
    monkeypatch.setattr("metis.testbed.embeddings.OpenAI", api)
    result = calculate_scores(specification_path.parent)
    assert result.reference is None
    assert result.scores is None
    assert set(result.behaviour_analysis) == set(BehaviourText)
    for analysis in result.behaviour_analysis.values():
        assert analysis.reference.pair_count == 1
        assert analysis.reference.matrix[0][0] == pytest.approx(1)
        assert analysis.reference.matrix[0][1] == analysis.reference.matrix[1][0]
        assert analysis.generated is None
        assert analysis.difference_error is None
    report = score_directory(specification_path) / specification_path.name
    assert report.with_suffix(".scores.json").is_file()
    assert report.with_suffix(".scores.md").is_file()
    api.assert_not_called()


def test_comparison_uses_shared_cache_and_all_metrics(specification_path, tmp_path):
    generated = tmp_path / "generated/generated-specification.yaml"
    generated.parent.mkdir()
    shutil.copyfile(specification_path, generated)
    provider = LocalEmbedder()
    result = calculate_scores(
        generated.parent, reference=specification_path.parent, embedder=provider
    )
    assert result.scores is not None
    for name in ("features", "behaviours", "criteria", "tasks"):
        assert getattr(result.scores, name).similarity == pytest.approx(1)
    assert result.scores.graders.similarity is None
    for analysis in result.behaviour_analysis.values():
        assert analysis.difference_error == pytest.approx(0)
        assert len(analysis.pairs) == 1
    provider.calls.clear()
    calculate_scores(generated, reference=specification_path, embedder=provider)
    assert provider.calls == []

    data = yaml.safe_load(generated.read_text())
    first, second = data["features"][0]["behaviours"]
    second["name"], second["description"] = first["name"], first["description"]
    generated.write_text(yaml.safe_dump(data))
    duplicate = calculate_scores(
        generated, reference=specification_path, embedder=provider
    )
    analysis = duplicate.behaviour_analysis[BehaviourText.BEHAVIOUR]
    assert analysis.generated is not None
    assert analysis.generated.mean_nn_similarity == pytest.approx(1)
    assert analysis.difference_error > 0


@pytest.mark.parametrize("count", [0, 1])
def test_fewer_than_two_behaviours_has_no_nn_score(tmp_path, count):
    path = tmp_path / "specification.yaml"
    shutil.copyfile(EVALS / "incident-triage/outputs/specification.yaml", path)
    if count == 0:
        specification = read_specification(path)
        specification.features = []
        specification.tasks = []
        path.write_text(yaml.safe_dump(specification.model_dump(mode="json")))
    result = calculate_scores(path, embedder=LocalEmbedder())
    for analysis in result.behaviour_analysis.values():
        assert analysis.reference.pair_count == 0
        assert analysis.reference.mean_nn_similarity is None
        assert analysis.reference.nearest_neighbours == []


def test_mean_nn_similarity_counts_each_behaviour_and_excludes_self(tmp_path):
    path = tmp_path / "specification.yaml"
    shutil.copyfile(EVALS / "travel-planner-langgraph/outputs/specification.yaml", path)
    specification = read_specification(path)
    vectors: dict[str, list[float]] = {}
    for version in BehaviourText:
        texts = list(behaviour_texts(specification, version).values())
        vectors.update(zip(texts, [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]], strict=True))

    class KnownVectors(LocalEmbedder):
        def embed(self, text):
            return vectors[text]

    result = calculate_scores(path, embedder=KnownVectors())
    for analysis in result.behaviour_analysis.values():
        matrix = analysis.reference
        assert matrix.mean_nn_similarity == pytest.approx(2 / 3)
        assert [item.similarity for item in matrix.nearest_neighbours] == [1, 1, 0]
        assert [item.neighbour_id for item in matrix.nearest_neighbours] == [
            matrix.ids[1],
            matrix.ids[0],
            matrix.ids[0],
        ]
        assert all(
            item.behaviour_id != item.neighbour_id for item in matrix.nearest_neighbours
        )
    report = score_directory(path) / "specification.scores.md"
    assert "Reference mean NN similarity: 0.667 (3 behaviours)" in report.read_text()


def test_pair_scores_include_behaviours_across_features(tmp_path):
    path = tmp_path / "specification.yaml"
    shutil.copyfile(EVALS / "enterprise-ai-assistant/outputs/specification.yaml", path)
    result = calculate_scores(path, embedder=LocalEmbedder())
    for analysis in result.behaviour_analysis.values():
        assert len(set(analysis.reference.feature_ids)) > 1
        assert analysis.reference.pair_count == 105


def test_missing_behaviour_has_no_pair_difference(specification_path, tmp_path):
    data = yaml.safe_load(specification_path.read_text())
    data["features"][0]["behaviours"].pop()
    generated = tmp_path / "generated.yaml"
    generated.write_text(yaml.safe_dump(data))
    result = calculate_scores(
        generated, reference=specification_path, embedder=LocalEmbedder()
    )
    assert result.scores is not None
    assert result.scores.behaviours.coverage == 0.5
    for analysis in result.behaviour_analysis.values():
        assert analysis.reference.pair_count == 1
        assert analysis.pairs == []
        assert analysis.difference_error is None


@pytest.mark.parametrize("case_name", ["billing-support", "incident-triage"])
def test_evaluation_saves_embeddings_and_metric_reports(
    tmp_path, monkeypatch, case_name
):
    case = tmp_path / "evals" / case_name
    (case / "inputs").mkdir(parents=True)
    (case / "outputs").mkdir()
    (case / "inputs/prompt.md").write_text("Billing support product")
    reference = case / "outputs/specification.yaml"
    shutil.copyfile(EVALS / case_name / "outputs/specification.yaml", reference)
    config = case.parent / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "id": "test",
                "version": 1,
                "component": "wizard",
                "cases": [case_name],
            }
        )
    )
    provider = LocalEmbedder()
    monkeypatch.setattr("metis.testbed.embeddings.GatewayEmbedder", lambda: provider)
    from metis.testbed.embeddings import read_specification

    specification = read_specification(reference)

    class Target:
        name = "test-target"

        def start(self, evidence):
            return WizardState(
                raw=None,
                specification=specification,
                outcome="awaiting_response",
                stage="clarify",
                pending={"type": "chat"},
            )

        def respond(self, state, response):
            raise AssertionError("No response is needed")

        def end(self, state):
            return WizardState(
                raw=None, specification=specification, outcome="done", stage="done"
            )

    record, output = run_evaluation(
        EvaluationRequest(
            config_path=config, results_root=tmp_path / "results", target_version="test"
        ),
        target=Target(),
        interaction=OneShotInteraction(),
    )
    assert record.cases[0].error is None
    assert record.cases[0].completed
    assert reference.with_suffix(".embeddings.json").is_file()
    generated = output / "cases" / case_name / "generated-specification.yaml"
    assert generated.with_suffix(".embeddings.json").is_file()
    assert generated.with_suffix(".scores.json").is_file()
    assert (
        record.cases[0].score_report
        == f"cases/{case_name}/generated-specification.scores.md"
    )
    summary = record.cases[0].behaviour_nn
    assert set(summary) == {version.value for version in BehaviourText}
    for values in summary.values():
        assert (
            values.reference_count
            == values.generated_count
            == len(specification.behaviours())
        )
        assert values.reference_mean_nn == values.generated_mean_nn
        if case_name == "incident-triage":
            assert values.reference_mean_nn is None
        else:
            assert values.reference_mean_nn is not None
            assert 0 < values.reference_mean_nn <= 1
    stored_case = json.loads((generated.parent / "result.json").read_text())
    stored_run = json.loads((output / "run.json").read_text())
    assert stored_case["behaviour_nn"] == stored_run["cases"][0]["behaviour_nn"]
    assert stored_case["behaviour_nn"] == {
        key: value.model_dump() for key, value in summary.items()
    }
    assert "Reference mean NN" in (output / "report.md").read_text()
    display = io.StringIO()
    monkeypatch.setattr("metis.testbed.cli.console", Console(file=display, width=160))
    _print_behaviour_nn(record)
    assert "experimental" in display.getvalue()
    assert "With context" in display.getvalue()
    assert "Ref count" in display.getvalue()
    provider.calls.clear()
    calculate_scores(generated, reference=reference)
    assert provider.calls == []


def test_cli_embeds_missing_inputs_once_and_reuses_them(
    specification_path, monkeypatch
):
    provider = LocalEmbedder()
    monkeypatch.setattr("metis.testbed.embeddings.GatewayEmbedder", lambda: provider)
    runner = CliRunner()
    result = runner.invoke(app, ["score", str(specification_path.parent)])
    assert result.exit_code == 0, result.output
    assert provider.calls
    provider.calls.clear()
    result = runner.invoke(app, ["embed", str(specification_path)])
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["score", str(specification_path)])
    assert result.exit_code == 0, result.output
    assert provider.calls == []


def test_gateway_sends_one_string_per_request(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.example/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("EMBEDDING_MODEL", "custom-embedding")
    client = MagicMock()
    client.embeddings.create.return_value.data = [MagicMock(embedding=[1.0, 0.0])]
    monkeypatch.setattr("metis.testbed.embeddings.OpenAI", lambda **_: client)
    provider = GatewayEmbedder()
    assert provider.embed("one behaviour") == [1.0, 0.0]
    client.embeddings.create.assert_called_once_with(
        model="custom-embedding", input="one behaviour"
    )


@pytest.mark.parametrize("vector", [[], [0.0, 0.0], [float("nan")], [float("inf")]])
def test_invalid_vectors_are_rejected(vector):
    with pytest.raises(ValueError):
        TextEmbedding(text="text", vector=vector)


def test_caches_with_different_dimensions_cannot_be_compared():
    first = EmbeddingCache(
        model="model",
        endpoint_hash="endpoint",
        entries={text_hash("a"): TextEmbedding(text="a", vector=[1.0])},
    )
    second = EmbeddingCache(
        model="model",
        endpoint_hash="endpoint",
        entries={text_hash("b"): TextEmbedding(text="b", vector=[1.0, 2.0])},
    )
    with pytest.raises(ValueError, match="dimensions"):
        CachedSimilarity(first, second)


def test_modified_cache_text_is_rejected(specification_path):
    ensure_embeddings(specification_path, embedder=LocalEmbedder())
    path = specification_path.with_suffix(".embeddings.json")
    data = json.loads(path.read_text())
    next(iter(data["entries"].values()))["text"] = "Unexpected text"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="hash"):
        ensure_embeddings(specification_path, embedder=LocalEmbedder())
