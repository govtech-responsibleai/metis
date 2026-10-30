"""The package-owned interview settings and status copy."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from metis.wizard.application import config
from metis.wizard.application.driver import DriverState, StepDriver
from metis.wizard.contracts.interview_state import InterviewMessage, Perspective
from metis.wizard.domain.permissions import InterviewStep
from tests.fixtures.wizard.context import interview_context
from tests.fixtures.wizard.scripted import ScriptedInterviewer
from tests.fixtures.wizard.specifications import research_assistant

_EXPECTED_STATUSES = {
    "clarify": "Understanding your agent…",
    "behaviours": "Shaping expected behaviours…",
    "criteria": "Writing testable criteria…",
    "personas": "Designing evaluator personas…",
    "scenarios": "Building coverage scenarios…",
    "test_cases": "Matching personas to scenarios…",
    "done": "Finishing up…",
}
_EXPECTED_WORKING_STATUS = "Working on your Interview…"
_EXPECTED_PERSPECTIVES = {
    "end_user",
    "engineer",
    "compliance",
    "security",
}


def _document() -> dict[str, Any]:
    value = yaml.safe_load(config._read_config_text())
    assert isinstance(value, dict)
    return value


def _install_document(
    monkeypatch: pytest.MonkeyPatch, document: dict[str, Any]
) -> None:
    monkeypatch.setattr(
        config,
        "_read_config_text",
        lambda: yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
    )


def _capability_document() -> dict[str, Any]:
    value = yaml.safe_load(config._read_capabilities_text())
    assert isinstance(value, dict)
    return value


def _install_capability_document(
    monkeypatch: pytest.MonkeyPatch, document: dict[str, Any]
) -> None:
    monkeypatch.setattr(
        config,
        "_read_capabilities_text",
        lambda: yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
    )


def _assert_complete_interview_document_is_validated(
    monkeypatch: pytest.MonkeyPatch,
    change: Callable[[dict[str, Any]], None],
    broken_key: str,
) -> None:
    document = _document()
    change(document)
    _install_document(monkeypatch, document)

    with pytest.raises(config.ConfigError) as caught:
        config.load_config()

    message = str(caught.value)
    assert config.CONFIG_FILE in message
    assert broken_key in message


def _set_settings_to_list(document: dict[str, Any]) -> None:
    document["settings"] = []


def _set_statuses_to_list(document: dict[str, Any]) -> None:
    document["statuses"] = []


def _remove_status(document: dict[str, Any]) -> None:
    del document["statuses"]["criteria"]


def _blank_status(document: dict[str, Any]) -> None:
    document["statuses"]["criteria"] = "  "


def _remove_working_status(document: dict[str, Any]) -> None:
    del document["statuses"]["working"]


def _blank_working_status(document: dict[str, Any]) -> None:
    document["statuses"]["working"] = "  "


def _restore_removed_status(document: dict[str, Any]) -> None:
    document["statuses"]["prioritise"] = "Choosing what to measure…"


def _remove_perspective(document: dict[str, Any]) -> None:
    document["perspectives"] = document["perspectives"][:-1]


def _duplicate_perspective(document: dict[str, Any]) -> None:
    document["perspectives"].append(document["perspectives"][0].copy())


def _unknown_perspective(document: dict[str, Any]) -> None:
    document["perspectives"][0]["id"] = "business"


@pytest.mark.parametrize(
    ("change", "broken_key"),
    [
        (_set_settings_to_list, "settings"),
        (_set_statuses_to_list, "statuses"),
        (_remove_status, "statuses.criteria"),
        (_blank_status, "statuses.criteria"),
        (_remove_working_status, "statuses.working"),
        (_blank_working_status, "statuses.working"),
        (_restore_removed_status, "statuses.prioritise"),
        (_remove_perspective, "perspectives"),
        (_duplicate_perspective, "perspectives[4].id"),
        (_unknown_perspective, "perspectives[0].id"),
    ],
)
def test_interview_validation_cases(
    monkeypatch: pytest.MonkeyPatch,
    change: Callable[[dict[str, Any]], None],
    broken_key: str,
) -> None:
    _assert_complete_interview_document_is_validated(monkeypatch, change, broken_key)


def test_a_missing_config_file_is_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(config.resources, "files", lambda _package: tmp_path)

    with pytest.raises(config.ConfigError) as caught:
        config.load_config()

    assert config.CONFIG_FILE in str(caught.value)
    assert "missing" in str(caught.value)


def test_a_wrong_config_root_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "_read_config_text", lambda: "[]")

    with pytest.raises(config.ConfigError, match="<document>"):
        config.load_config()


@pytest.mark.parametrize("value", ["5", True, 0, -1])
def test_the_clarify_limit_must_be_a_positive_non_boolean_integer(
    monkeypatch: pytest.MonkeyPatch, value: object
) -> None:
    document = _document()
    document["settings"]["clarify_turn_cap"] = value
    _install_document(monkeypatch, document)

    with pytest.raises(config.ConfigError, match="settings.clarify_turn_cap"):
        config.clarify_turn_cap()


def test_every_interview_step_has_the_existing_status_copy() -> None:
    loaded = config.load_config()

    assert {
        step.value: loaded.statuses[step] for step in InterviewStep
    } == _EXPECTED_STATUSES


def test_the_general_working_status_comes_from_the_package_config() -> None:
    assert config.working_status() == _EXPECTED_WORKING_STATUS


def test_a_status_edit_affects_the_next_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _document()
    _install_document(monkeypatch, document)

    first = config.status_for(InterviewStep.CRITERIA)
    document["statuses"]["criteria"] = "Updated criteria status."
    second = config.status_for(InterviewStep.CRITERIA)

    assert first == _EXPECTED_STATUSES["criteria"]
    assert second == "Updated criteria status."


def test_a_limit_edit_affects_an_active_interview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _document()
    document["settings"]["clarify_turn_cap"] = 3
    _install_document(monkeypatch, document)
    state = DriverState(
        specification=research_assistant(),
        context=interview_context(),
        step=InterviewStep.CLARIFY,
        history=[
            InterviewMessage(role="assistant", text=config.opening_question()),
            InterviewMessage(role="user", text="the first answer"),
            InterviewMessage(role="assistant", text="question one"),
            InterviewMessage(role="assistant", text="question two"),
        ],
    )
    driver = StepDriver(interviewer=ScriptedInterviewer(clarify_questions=5))

    driver.compose(state)
    assert state.step is InterviewStep.CLARIFY

    document["settings"]["clarify_turn_cap"] = 2
    driver.compose(state)

    assert state.step is InterviewStep.BEHAVIOURS


def test_interview_configuration_is_a_package_resource() -> None:
    loaded = config.load_config()

    assert loaded.clarify_turn_cap > 0
    assert loaded.opening_question
    assert loaded.working_status
    assert set(loaded.statuses) == set(InterviewStep)
    assert {item.id.value for item in loaded.perspectives} == _EXPECTED_PERSPECTIVES


def test_the_final_arc_catalogue_and_metadata_are_validated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = config.load_config()
    expected = [
        (
            "cognitive",
            [
                (
                    "planning_goal_management",
                    "Planning & Goal Management",
                    "Builds, tracks, and adjusts multi-step plans to meet goals.",
                ),
                (
                    "agent_delegation",
                    "Agent Delegation",
                    "Assigns work to other agents and coordinates their work.",
                ),
                (
                    "tool_use",
                    "Tool Use",
                    "Selects and sequences suitable tools for a task.",
                ),
            ],
        ),
        (
            "interaction",
            [
                (
                    "multimodal_understanding_generation",
                    "Multimodal Understanding & Generation",
                    "Understands or creates natural language, images, audio, or video.",
                ),
                (
                    "official_communication",
                    "Official Communication",
                    "Sends authoritative external communications for an organisation without prior human approval.",
                ),
                (
                    "business_transactions",
                    "Business Transactions",
                    "Starts, authorises, or executes binding payments, purchases, reservations, or service commitments.",
                ),
                (
                    "internet_search_access",
                    "Internet & Search Access",
                    "Searches, browses, and retrieves information from the Internet.",
                ),
                (
                    "computer_use",
                    "Computer Use",
                    "Operates a graphical computer interface with pointer and keyboard actions.",
                ),
                (
                    "other_programmatic_interfaces",
                    "Other Programmatic Interfaces",
                    "Uses APIs, SDKs, backend services, and other non-graphical interfaces.",
                ),
            ],
        ),
        (
            "operational",
            [
                ("code_execution", "Code Execution", "Writes, runs, and debugs code."),
                (
                    "file_data_management",
                    "File & Data Management",
                    "Creates, reads, changes, organises, and queries files or data stores.",
                ),
                (
                    "system_management",
                    "System Management",
                    "Manages and configures technical systems, infrastructure, resources, and access.",
                ),
            ],
        ),
    ]
    actual = [
        (
            category.id.value,
            [
                (item.id.value, item.name, item.description)
                for item in category.capabilities
            ],
        )
        for category in loaded.capability_categories
    ]
    assert actual == expected
    assert [category.name for category in loaded.capability_categories] == [
        "Cognitive",
        "Interaction",
        "Operational",
    ]
    assert loaded.capability_source == (
        "https://github.com/govtech-responsibleai/agentic-risk-capability-framework"
    )
    assert loaded.capability_attribution == (
        "GovTech Singapore, Agentic Risk & Capability Framework"
    )
    assert loaded.capability_license == "Apache-2.0"

    broken = _capability_document()
    broken["categories"][0]["capabilities"].pop()
    _install_capability_document(monkeypatch, broken)
    with pytest.raises(config.ConfigError, match=config.CAPABILITIES_FILE):
        config.load_config()


def test_public_client_configuration_exposes_the_opening_copy_and_perspectives() -> (
    None
):
    client_config = config.interview_client_config()

    assert client_config.opening_question
    assert client_config.working_status == _EXPECTED_WORKING_STATUS
    assert {item.id for item in client_config.perspectives} == {
        Perspective(item) for item in _EXPECTED_PERSPECTIVES
    }


def test_a_perspective_label_edit_affects_the_next_client_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _document()
    _install_document(monkeypatch, document)

    document["perspectives"][0]["label"] = "People who use it"

    assert config.interview_client_config().perspectives[0].label == "People who use it"
