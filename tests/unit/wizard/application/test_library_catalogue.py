"""The grader settings that the catalogue gives to clients."""

from metis.wizard.application.matching import library_catalogue
from metis.wizard.contracts.grader_spec import GraderSettingKind


def _settings(class_name: str) -> dict[str, dict[str, object]]:
    spec = next(
        spec
        for spec in library_catalogue()
        if spec.fqn == f"metis.library.graders.{class_name}"
    )
    return {setting.name: setting.model_dump(mode="json") for setting in spec.settings}


def test_a_grader_lists_the_base_settings_then_its_own_settings() -> None:
    settings = _settings("FactualAccuracyGrader")

    assert list(settings)[:4] == ["threshold", "scope", "judgment_form", "aggregation"]
    ground_truth = settings["ground_truth"]
    assert ground_truth["kind"] == GraderSettingKind.LIST
    assert ground_truth["required"] is True
    assert ground_truth["default"] is None
    assert ground_truth["base"] is False
    assert ground_truth["description"]
    assert settings["turn"]["kind"] == GraderSettingKind.CHOICE
    assert settings["turn"]["choices"] == ["each", "last"]
    assert settings["threshold"]["default"] == 0.5
    assert settings["threshold"]["kind"] == GraderSettingKind.NUMBER
    assert all(
        settings[name]["base"]
        for name in ("threshold", "scope", "judgment_form", "aggregation")
    )
    assert settings["scope"]["kind"] == GraderSettingKind.CHOICE
    assert settings["scope"]["choices"] == ["trace", "artifact"]
    assert settings["judgment_form"]["choices"] == ["binary"]


def test_no_grader_lists_a_setting_that_the_engine_fills() -> None:
    names = {setting.name for spec in library_catalogue() for setting in spec.settings}

    assert names.isdisjoint({"model", "max_input_tokens", "criterion"})
