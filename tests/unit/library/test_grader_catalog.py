"""The grader catalogue exports concrete production graders."""

from __future__ import annotations

import importlib
import inspect

import pytest

import metis.library.graders as catalog
from metis.library.grader import Grader

EXECUTION_AND_DECISION_QUALITY = {
    "ActionChoiceAppropriatenessGrader",
    "AdaptationToChangedConditionsGrader",
    "AppropriateHandlingOfCapabilityLimitsGrader",
    "AvoidingUnproductiveRepetitionGrader",
    "CoordinationQualityGrader",
    "ErrorDetectionGrader",
    "ErrorRecoveryGrader",
    "OutcomeVerificationGrader",
    "PlanningQualityGrader",
    "ReasoningValidityGrader",
    "StateTrackingGrader",
    "StoppingAppropriatenessGrader",
    "ToolArgumentCorrectnessGrader",
    "ToolChoiceAppropriatenessGrader",
    "UseOfPriorInformationGrader",
}
TASK_AND_OUTPUT_QUALITY = {
    "AttributionAccuracyGrader",
    "ClaimSupportByEvidenceGrader",
    "ContentFidelityGrader",
    "EvidenceSourceSuitabilityGrader",
    "FactualAccuracyGrader",
    "FormatSchemaComplianceGrader",
    "OutputCorrectnessGrader",
    "RequiredComponentCompletenessGrader",
    "SpeechRecognitionAccuracyGrader",
    "TaskConstraintAdherenceGrader",
    "TaskSuccessGrader",
}
INTERACTION_QUALITY = {
    "ActionStatusTransparencyGrader",
    "ClarificationAppropriatenessGrader",
    "CommunicationClarityGrader",
    "CrossTurnCoherenceGrader",
    "ExplanationUsefulnessGrader",
    "OutputNaturalnessGrader",
    "RelevanceGrader",
    "ToneAppropriatenessGrader",
    "UserCorrectionSupportGrader",
}
RELIABILITY_AND_ROBUSTNESS = {
    "LongTaskPerformanceStabilityGrader",
    "RobustnessToContextDegradationGrader",
    "RobustnessToToolFailuresGrader",
}
EXPECTED = (
    {"CriterionJudgeGrader"}
    | EXECUTION_AND_DECISION_QUALITY
    | INTERACTION_QUALITY
    | RELIABILITY_AND_ROBUSTNESS
    | TASK_AND_OUTPUT_QUALITY
)


def _exported_classes() -> dict[str, type]:
    return {
        name: obj
        for name, obj in vars(catalog).items()
        if inspect.isclass(obj) and not name.startswith("_")
    }


def test_exports_exactly_the_catalogue_graders() -> None:
    assert set(_exported_classes()) == EXPECTED


def test_every_export_is_a_concrete_grader() -> None:
    for name, cls in _exported_classes().items():
        assert issubclass(cls, Grader), name
        assert not inspect.isabstract(cls), name


@pytest.mark.parametrize(
    "name",
    [
        "TurnBudgetGrader",
        "SynthesisFaithfulnessGrader",
        "CancellationGrader",
        "MetisTurnGrader",
        "MetisSessionGrader",
    ],
)
def test_old_graders_and_bases_are_gone(name: str) -> None:
    assert not hasattr(catalog, name)


@pytest.mark.parametrize(
    "module", ["default", "_base", "_judge", "_types", "_extraction"]
)
def test_old_support_modules_are_gone(module: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(f"metis.library.graders.{module}")


def test_library_does_not_import_deepeval() -> None:
    """Importing the library must not pull DeepEval in, even transitively."""
    import sys

    importlib.import_module("metis.library.graders")
    assert "deepeval" not in sys.modules
