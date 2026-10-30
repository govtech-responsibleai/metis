"""Offline checks for Wizard Target evaluation and saved comparisons."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from metis.core.specification import Specification
from metis.testbed.contracts import (
    CaseStatus,
    EvaluationProgress,
    EvaluationRequest,
    WizardInput,
    WizardState,
)
from metis.testbed.evaluation import (
    OneShotInteraction,
    compare_versions,
    run_evaluation,
)
from metis.testbed.scoring import compare_specifications

REPOSITORY = Path(__file__).resolve().parents[3]
EVALS = REPOSITORY / "packages/testbed/wizard/cases"


@pytest.fixture
def evaluation_config(tmp_path: Path) -> Path:
    """Use fixed test inputs independent of private local documents."""
    root = tmp_path / "evals"
    root.mkdir()
    config = yaml.safe_load((EVALS / "config.yaml").read_text())
    for relative in config["cases"]:
        folder = root / relative
        (folder / "inputs").mkdir(parents=True)
        (folder / "inputs/prompt.md").write_text("Product information for " + relative)
        shutil.copytree(EVALS / relative / "outputs", folder / "outputs")
    path = root / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    return path


class ExactSimilarity:
    """A deterministic offline substitute for semantic embeddings."""

    def matrix(self, left: list[str], right: list[str]) -> list[list[float]]:
        return [[float(a == b) for b in right] for a in left]


class ReferenceTarget:
    """Return each reference through the same Target interface as a real Wizard."""

    name = "reference-wizard"

    def __init__(self) -> None:
        self.specifications: dict[str, Specification] = {}
        self.evidence: list[WizardInput] = []
        config = yaml.safe_load((EVALS / "config.yaml").read_text())
        for relative in config["cases"]:
            root = EVALS / relative
            self.specifications[root.name] = Specification.model_validate(
                yaml.safe_load((root / "outputs/specification.yaml").read_text())
            )

    def start(self, evidence: WizardInput) -> WizardState:
        self.evidence.append(evidence)
        return WizardState(
            raw=evidence.case_id,
            specification=self.specifications[evidence.case_id],
            outcome="awaiting_response",
            stage="clarify",
            pending={"type": "chat"},
        )

    def respond(self, state: WizardState, response: object) -> WizardState:
        raise AssertionError(
            "The one-shot interaction must not answer the first request."
        )

    def end(self, state: WizardState) -> WizardState:
        return WizardState(
            raw=state.raw,
            specification=state.specification,
            outcome="done",
            stage="done",
        )


def _travel() -> Specification:
    return Specification.model_validate(
        yaml.safe_load(
            (EVALS / "travel-planner-langgraph/outputs/specification.yaml").read_text()
        )
    )


def test_similarity_uses_content_when_ids_and_order_change() -> None:
    reference = _travel()
    generated = reference.model_copy(deep=True)
    generated.features[0].id = "generated-feature"
    generated.features[0].behaviours.reverse()
    for index, behaviour in enumerate(generated.behaviours(), start=1):
        old_id = behaviour.id
        behaviour.id = f"generated-behaviour-{index}"
        for task in generated.tasks:
            task.behaviour_refs = [
                behaviour.id if item == old_id else item for item in task.behaviour_refs
            ]
        for criterion_index, criterion in enumerate(behaviour.criteria, start=1):
            criterion.id = f"generated-criterion-{index}-{criterion_index}"
    generated.tasks.reverse()
    for index, task in enumerate(generated.tasks, start=1):
        task.id = f"generated-task-{index}"

    scores = compare_specifications(generated, reference, ExactSimilarity())

    assert scores.features.similarity == 1.0
    assert scores.behaviours.similarity == 1.0
    assert scores.criteria.similarity == 1.0
    assert scores.graders.similarity is None
    assert scores.tasks.similarity == 1.0


def test_similarity_penalizes_missing_content_and_skips_unreviewed_graders() -> None:
    reference = _travel()
    generated = reference.model_copy(deep=True)
    generated.features[0].behaviours.pop(0)
    for criterion in generated.features[0].behaviours[-1].criteria:
        criterion.grader_fqn = "example.GeneratedGrader"

    scores = compare_specifications(generated, reference, ExactSimilarity())

    assert scores.features.similarity == 1.0
    assert scores.behaviours.similarity == 2 / 3
    assert scores.behaviours.missing == ["EB-1"]
    assert scores.graders.similarity is None
    assert scores.graders.reference_count == 0
    assert scores.graders.generated_count == 3


def test_one_command_records_every_configured_case(
    tmp_path: Path, evaluation_config: Path
) -> None:
    now = datetime(2026, 10, 15, 2, 30, tzinfo=UTC)
    supporting_document = (
        evaluation_config.parent / "enterprise-ai-assistant/inputs/policy.md"
    )
    supporting_document.write_text("Company policy content")
    target = ReferenceTarget()
    progress: list[EvaluationProgress] = []
    record, output = run_evaluation(
        EvaluationRequest(
            config_path=evaluation_config,
            results_root=tmp_path,
            target_version="v1.0.1",
        ),
        target=target,
        interaction=OneShotInteraction(),
        similarity=ExactSimilarity(),
        clock=lambda: now,
        on_progress=progress.append,
    )

    assert [result.case_id for result in record.cases] == [
        "enterprise-ai-assistant",
        "travel-planner-langgraph",
        "billing-support",
        "incident-triage",
    ]
    assert all(result.status is CaseStatus.SCORED for result in record.cases)
    assert [
        (item.case_id, item.phase) for item in progress if item.phase == "scored"
    ] == [(result.case_id, "scored") for result in record.cases]
    assert progress[0].completed == 0
    assert progress[-1].completed == progress[-1].total == len(record.cases)
    assert output == (tmp_path / "reference-wizard/v1.0.1/20261015T023000Z")
    assert (output / "run.json").is_file()
    assert (output / "report.md").is_file()
    assert (
        output / "cases/travel-planner-langgraph/generated-specification.yaml"
    ).is_file()
    assert record.cases[0].events[0].operation == "start"
    assert record.cases[0].events[1].operation == "end"
    assert all(
        item.description.startswith("Product information for ")
        for item in target.evidence
    )
    documents_by_case = {item.case_id: item.documents for item in target.evidence}
    assert documents_by_case["enterprise-ai-assistant"] == [
        ("policy.md", "Company policy content")
    ]
    assert all(
        not documents
        for case_id, documents in documents_by_case.items()
        if case_id != "enterprise-ai-assistant"
    )


def test_one_broken_case_does_not_stop_the_other_cases(tmp_path: Path) -> None:
    evals = tmp_path / "evals"
    missing = evals / "missing"
    valid = evals / "valid"
    (valid / "inputs").mkdir(parents=True)
    (valid / "outputs").mkdir()
    missing.mkdir(parents=True)
    (evals / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "isolation",
                "version": 1,
                "component": "wizard",
                "cases": ["missing", "valid"],
            }
        )
    )
    (valid / "inputs/prompt.md").write_text("A travel planner.")
    (valid / "outputs/specification.yaml").write_text(
        yaml.safe_dump(_travel().model_dump(mode="json"), sort_keys=False)
    )
    target = ReferenceTarget()
    target.specifications["valid"] = _travel()

    record, _ = run_evaluation(
        EvaluationRequest(
            config_path=evals / "config.yaml",
            results_root=tmp_path / "results",
            target_version="v1",
        ),
        target=target,
        interaction=OneShotInteraction(),
        similarity=ExactSimilarity(),
        clock=lambda: datetime(2026, 10, 15, tzinfo=UTC),
    )

    assert [item.status for item in record.cases] == [
        CaseStatus.INPUT_MISSING,
        CaseStatus.SCORED,
    ]


def test_saved_versions_compare_the_latest_execution(
    tmp_path: Path, evaluation_config: Path
) -> None:
    target = ReferenceTarget()
    for version, day in (("v1.0.0", 14), ("v1.0.1", 15)):
        run_evaluation(
            EvaluationRequest(
                config_path=evaluation_config,
                results_root=tmp_path,
                target_version=version,
            ),
            target=target,
            interaction=OneShotInteraction(),
            similarity=ExactSimilarity(),
            clock=lambda day=day: datetime(2026, 10, day, tzinfo=UTC),
        )

    comparison = compare_versions(
        tmp_path,
        target="reference-wizard",
        older_version="v1.0.0",
        newer_version="v1.0.1",
    )

    assert comparison.older_id == "20261014T000000Z"
    assert comparison.newer_id == "20261015T000000Z"
    # No reference has reviewed graders, so that level has nothing to compare.
    assert comparison.changes["graders"] is None
    assert {v for k, v in comparison.changes.items() if k != "graders"} == {0.0}


def test_structured_failure_is_saved_with_diagnostic_specification(
    tmp_path: Path,
    evaluation_config: Path,
) -> None:
    from tests.fixtures.wizard.context import interview_context

    from metis.testbed.evaluation import MetisWizardTarget
    from metis.wizard import InterviewFailure
    from metis.wizard.contracts.interview_state import InterviewState
    from metis.wizard.contracts.turn import (
        InterviewErrorCode,
        MissingData,
        MissingDataCode,
    )
    from metis.wizard.domain.permissions import InterviewStep

    failure = InterviewFailure(
        code=InterviewErrorCode.COMPLETION_FAILED,
        message="Missing coverage",
        retryable=False,
        diagnostic_state=InterviewState(
            specification=_travel().model_dump(), context=interview_context()
        ),
        missing=[
            MissingData(
                code=MissingDataCode.BEHAVIOUR_UNCOVERED,
                stage=InterviewStep.SCENARIOS,
                subject="EB-1",
                message="EB-1 needs coverage",
            )
        ],
    )

    class FailingTarget(ReferenceTarget):
        def end(self, state):
            return MetisWizardTarget._state(self, failure)

    record, output = run_evaluation(
        EvaluationRequest(
            config_path=evaluation_config,
            results_root=tmp_path,
            target_version="failure",
        ),
        target=FailingTarget(),
        interaction=OneShotInteraction(),
        similarity=ExactSimilarity(),
    )
    for case in record.cases:
        assert case.failure == failure.model_dump(mode="json")
        assert not case.completed
        assert case.events[0].operation == "start"
        assert (output / case.generated_specification).is_file()
    assert "EB-1 needs coverage" in (output / "report.md").read_text()


def test_incomplete_interview_keeps_scores_without_claiming_completion(
    tmp_path: Path,
    evaluation_config: Path,
) -> None:
    class IncompleteTarget(ReferenceTarget):
        def end(self, state):
            return state

    record, _ = run_evaluation(
        EvaluationRequest(
            config_path=evaluation_config,
            results_root=tmp_path,
            target_version="incomplete",
        ),
        target=IncompleteTarget(),
        interaction=OneShotInteraction(),
        similarity=ExactSimilarity(),
    )
    assert all(
        case.status is CaseStatus.INCOMPLETE
        and not case.completed
        and case.scores is not None
        for case in record.cases
    )


@pytest.mark.parametrize("enabled", [True, False])
def test_one_shot_accepts_only_ready_final_review(enabled: bool) -> None:
    from metis.wizard.contracts import ChoiceRequest, Option, OptionId

    class ReviewTarget(ReferenceTarget):
        def end(self, state):
            state.stage = "scenarios"
            state.pending = ChoiceRequest(
                prompt="Review",
                options=[
                    Option(
                        id=OptionId(action="continue"),
                        label="Continue",
                        enabled=enabled,
                    ),
                ],
            ).model_dump(mode="json")
            return state

        def respond(self, state, response):
            assert response == {"type": "choice", "selected": ["continue"]}
            state.outcome = "done"
            state.stage = "done"
            state.pending = None
            return state

    candidate = OneShotInteraction().run(
        ReviewTarget(), WizardInput(case_id="billing-support", description="Billing")
    )
    assert candidate.outcome == ("done" if enabled else "awaiting_response")
    assert [event.operation for event in candidate.events] == (
        ["start", "end", "accept_review"] if enabled else ["start", "end"]
    )
