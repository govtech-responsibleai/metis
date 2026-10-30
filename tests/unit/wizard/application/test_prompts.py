"""The prompt catalogue, its validation, and its composition contracts."""

from __future__ import annotations

import json
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import Any, get_args

import pytest
import yaml

from metis.library.taxonomy import (
    Aggregation,
    GraderTaxonomy,
    GraderType,
    JudgmentForm,
    Measure,
    ReferenceType,
    Scope,
)
from metis.wizard.application import prompts
from metis.wizard.application.config import opening_question
from metis.wizard.contracts import (
    InterviewDocument,
    Specification,
    Target,
)
from metis.wizard.contracts.grader_spec import GraderSpec
from metis.wizard.contracts.interview_state import InterviewMessage, Perspective
from tests.fixtures.wizard.context import interview_context
from tests.fixtures.wizard.specifications import desk_handover, research_assistant

# `matching` exports the `library_catalogue` function under the module's own name.
catalogue_module = import_module("metis.wizard.application.matching.library_catalogue")

PERSPECTIVES = Path("packages/wizard/src/metis/wizard/application/perspectives")


def _document() -> dict[str, Any]:
    value = yaml.safe_load(prompts._read_catalog_text())
    assert isinstance(value, dict)
    return value


def _install_document(
    monkeypatch: pytest.MonkeyPatch, document: dict[str, Any]
) -> None:
    monkeypatch.setattr(
        prompts,
        "_read_catalog_text",
        lambda: yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
    )


def _perspective_text(name: str) -> str:
    """The on-disk perspective body, exactly as composition embeds it."""
    return (PERSPECTIVES / f"{name}.md").read_text(encoding="utf-8").strip()


def _xml_content(message: str, tag: str) -> str:
    """Read the payload after any tag names mentioned in prompt instructions."""
    opening = f"<{tag}>"
    closing = f"</{tag}>"
    start = message.rfind(opening)
    assert start >= 0
    start += len(opening)
    end = message.index(closing, start)
    return message[start:end]


# --- substitution mechanics ------------------------------------------------


def test_substitution_only_expands_placeholders() -> None:
    template = '  before\n$specification\n$$literal\nvalue: {"name": "x"}\n  after  '

    result = prompts._substitute(template, "test", {"specification": "VALUE"})

    # placeholders expand; every other byte — braces, escaped `$`, whitespace — is literal
    assert result == '  before\nVALUE\n$literal\nvalue: {"name": "x"}\n  after  '


def test_an_unsupplied_placeholder_is_rejected() -> None:
    with pytest.raises(prompts.PromptCatalogError, match="model_calls.criteria"):
        prompts._substitute("$specification", "model_calls.criteria", {})


# --- catalogue validation --------------------------------------------------


def _assert_complete_catalogue_is_validated(
    monkeypatch: pytest.MonkeyPatch,
    change: Callable[[dict[str, Any]], None],
    broken_key: str,
) -> None:
    document = _document()
    change(document)
    _install_document(monkeypatch, document)

    with pytest.raises(prompts.PromptCatalogError) as caught:
        prompts.criteria(research_assistant())

    message = str(caught.value)
    assert prompts.PROMPTS_FILE in message
    assert broken_key in message


def _set_system_to_list(document: dict[str, Any]) -> None:
    document["system"] = []


def _remove_criteria(document: dict[str, Any]) -> None:
    del document["model_calls"]["criteria"]


def _blank_scenarios(document: dict[str, Any]) -> None:
    document["model_calls"]["scenarios"] = "  "


def _remove_match_graders(document: dict[str, Any]) -> None:
    del document["match_graders"]


def _invalid_template(document: dict[str, Any]) -> None:
    document["model_calls"]["criteria"] = "bad $"


def _unsupported_placeholder(document: dict[str, Any]) -> None:
    document["model_calls"]["criteria"] = "$specification $unknown"


@pytest.mark.parametrize(
    ("change", "broken_key"),
    [
        (_set_system_to_list, "system"),
        (_remove_criteria, "model_calls.criteria"),
        (_blank_scenarios, "model_calls.scenarios"),
        (_remove_match_graders, "match_graders"),
        (_invalid_template, "model_calls.criteria"),
        (_unsupported_placeholder, "model_calls.criteria"),
    ],
)
def test_catalogue_validation_cases(
    monkeypatch: pytest.MonkeyPatch,
    change: Callable[[dict[str, Any]], None],
    broken_key: str,
) -> None:
    _assert_complete_catalogue_is_validated(monkeypatch, change, broken_key)


def test_a_missing_catalogue_file_is_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(prompts.resources, "files", lambda _package: tmp_path)

    with pytest.raises(prompts.PromptCatalogError) as caught:
        prompts.load_prompt_catalog()

    assert prompts.PROMPTS_FILE in str(caught.value)
    assert "missing" in str(caught.value)


def test_a_wrong_catalogue_root_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prompts, "_read_catalog_text", lambda: "[]")

    with pytest.raises(prompts.PromptCatalogError, match="<document>"):
        prompts.load_prompt_catalog()


def test_prompt_catalogue_is_a_package_resource() -> None:
    catalog = prompts.load_prompt_catalog()

    assert catalog.patch_rules
    assert set(catalog.model_calls) == {
        "clarify",
        "behaviours",
        "criteria",
        "personas",
        "scenarios",
        "test_cases",
        "chat",
    }


# --- freshness: no resource is cached across composes ----------------------


def test_composition_reads_every_resource_fresh(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The catalogue, primer, and perspective files are re-read on every compose,
    so an edit to any of them reaches the next prompt without a restart."""
    from metis.wizard.application import config as config_module

    document = _document()
    (tmp_path / config_module.CONFIG_FILE).write_text(
        config_module._read_config_text(), encoding="utf-8"
    )
    (tmp_path / config_module.CAPABILITIES_FILE).write_text(
        config_module._read_capabilities_text(), encoding="utf-8"
    )
    prompts_path = tmp_path / prompts.PROMPTS_FILE
    prompts_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False)
    )
    primer_path = tmp_path / prompts.PRIMER_FILE
    primer_path.write_text("FIRST PRIMER", encoding="utf-8")
    perspective_dir = tmp_path / prompts.PERSPECTIVES_DIR
    perspective_dir.mkdir()
    for name in ("end_user", "engineer", "compliance", "security"):
        (perspective_dir / f"{name}.md").write_text("FIRST LENS", encoding="utf-8")
    monkeypatch.setattr(prompts.resources, "files", lambda _package: tmp_path)

    first = prompts.clarify(research_assistant(), [], context=interview_context())

    document["model_calls"]["clarify"] += "\nEDITED TEMPLATE"
    prompts_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False)
    )
    primer_path.write_text("SECOND PRIMER", encoding="utf-8")
    (perspective_dir / "end_user.md").write_text("SECOND LENS", encoding="utf-8")

    second = prompts.clarify(research_assistant(), [], context=interview_context())

    assert "FIRST PRIMER" in first.system
    assert "SECOND PRIMER" in second.system
    assert "FIRST LENS" in first.user
    assert "SECOND LENS" in second.user
    assert not first.user.endswith("EDITED TEMPLATE")
    assert second.user.endswith("EDITED TEMPLATE")


def test_the_system_and_user_messages_share_one_catalogue_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _document()
    _install_document(monkeypatch, document)
    reads = 0
    original = prompts._read_catalog_text

    def read_once() -> str:
        nonlocal reads
        reads += 1
        return original()

    monkeypatch.setattr(prompts, "_read_catalog_text", read_once)
    prompt = prompts.criteria(research_assistant())

    assert reads == 1
    assert prompt.system
    assert prompt.user


# --- composition contracts -------------------------------------------------


def test_clarify_uses_one_shared_catalogue_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _document()
    document["model_calls"]["clarify"] += "\nSHARED CLARIFY MARKER"
    _install_document(monkeypatch, document)
    empty = Specification(target=Target(name="", users="", description=""))

    prompt = prompts.clarify(empty, [], context=interview_context())

    assert prompt.name == "clarify"
    assert prompt.user.endswith("SHARED CLARIFY MARKER")


def test_clarify_progress_values_are_substituted_into_the_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _document()
    document["model_calls"]["clarify"] = (
        "<progress>$questions_asked/$question_cap/$questions_remaining</progress>"
    )
    _install_document(monkeypatch, document)

    history = [
        InterviewMessage(role="assistant", text=opening_question()),
        InterviewMessage(role="user", text="The opening answer."),
        InterviewMessage(role="assistant", text="Question one?"),
        InterviewMessage(role="user", text="Answer one."),
        InterviewMessage(role="assistant", text="Question two?"),
        InterviewMessage(role="user", text="Answer two."),
        InterviewMessage(role="assistant", text="Question three?"),
        InterviewMessage(role="user", text="Answer three."),
    ]

    assert prompts._clarify_progress(history) == (3, 5, 2)
    prompt = prompts.clarify(research_assistant(), history, context=interview_context())
    assert prompt.user == "<progress>3/5/2</progress>"

    at_cap = [
        *history,
        InterviewMessage(role="assistant", text="Question four?"),
        InterviewMessage(role="user", text="Answer four."),
        InterviewMessage(role="assistant", text="Question five?"),
        InterviewMessage(role="user", text="Answer five."),
    ]
    assert prompts._clarify_progress(at_cap) == (5, 5, 0)

    final_prompt = prompts.clarify(desk_handover(), at_cap, context=interview_context())
    assert final_prompt.user == "<progress>5/5/0</progress>"


# --- model-call input contracts --------------------------------------------


@pytest.mark.parametrize("perspective", [Perspective.END_USER, Perspective.SECURITY])
@pytest.mark.parametrize(
    "call",
    [
        "clarify",
        "behaviours",
        "criteria",
        "personas",
        "scenarios",
        "scenario_chat",
        "criterion_chat",
    ],
)
def test_model_calls_receive_their_required_context(
    call: str,
    perspective: Perspective,
) -> None:
    specification = desk_handover()
    context = interview_context(
        perspective=perspective, known_capability_ids=["tool_use"], confidence="high"
    )
    context.opening_description = "OPENING_SENTINEL"
    context.documents = [
        InterviewDocument(name="policy.md", text="DOCUMENT_SENTINEL"),
        InterviewDocument(name="sample.csv"),
    ]
    # The current history need not contain the original opening message.
    history = [InterviewMessage(role="user", text="RECENT_ANSWER_SENTINEL")]
    if call in {"clarify", "behaviours"}:
        prompt = getattr(prompts, call)(specification, history, context=context)
    elif call.endswith("_chat"):
        step = "scenarios" if call == "scenario_chat" else "criteria"
        prompt = prompts.chat(
            specification, step, "CHAT_SENTINEL", None, context=context
        )
    else:
        prompt = getattr(prompts, call)(specification, context=context)

    assert json.loads(
        _xml_content(prompt.user, "specification")
    ) == specification.model_dump(mode="json")
    assert prompts.primer() in _xml_content(prompt.system, "primer")
    assert prompts.arc_catalogue() in _xml_content(prompt.system, "arc_catalogue")
    assert _xml_content(prompt.system, "perspective").strip() == perspective.value
    assert (
        json.loads(_xml_content(prompt.system, "opening_description"))
        == "OPENING_SENTINEL"
    )
    assert json.loads(_xml_content(prompt.system, "interview_documents")) == [
        {"name": "policy.md", "text": "DOCUMENT_SENTINEL"},
        {"name": "sample.csv", "text": None},
    ]
    expected_files = (
        ["policy.md", "sample.csv"]
        if call in {"scenarios", "scenario_chat", "criterion_chat"}
        else []
    )
    assert (
        json.loads(_xml_content(prompt.system, "available_fixture_names"))
        == expected_files
    )

    if call in {"clarify", "behaviours"}:
        assert "RECENT_ANSWER_SENTINEL" in _xml_content(prompt.user, "transcript")
        assert _perspective_text(perspective.value) in _xml_content(
            prompt.user, "perspective"
        )
        evidence = _xml_content(prompt.user, "capability_evidence")
        assert "tool_use" in evidence
        assert context.capability_evidence.confidence.value in evidence
        other = (
            Perspective.SECURITY
            if perspective == Perspective.END_USER
            else Perspective.END_USER
        )
        assert _perspective_text(other.value) not in _xml_content(
            prompt.user, "perspective"
        )
    assert _perspective_text(perspective.value) in _xml_content(
        prompt.system, "perspective_guidance"
    )
    assert "tool_use" in _xml_content(prompt.system, "capability_evidence")
    if call.endswith("_chat"):
        assert _xml_content(prompt.user, "user_message").strip() == "CHAT_SENTINEL"


def test_unspecified_capability_context_is_available_to_all_calls() -> None:
    prompt = prompts.clarify(research_assistant(), [])
    assert "unspecified" in _xml_content(prompt.system, "capability_evidence").lower()


# --- the grader library, by disclosure level -------------------------------


def _test_grader(measure: Measure) -> GraderSpec:
    return GraderSpec(
        fqn=f"tests.graders.{measure.value.upper()}_SENTINEL_GRADER",
        name=f"{measure.value} sentinel name",
        description=f"{measure.value} SENTINEL SUMMARY",
        taxonomy=GraderTaxonomy(
            measure=measure,
            scopes=(Scope.SESSION,),
            grader_types=(GraderType.LLM,),
            reference_types=(ReferenceType.RUBRIC_BASED,),
            judgment_forms=(JudgmentForm.BINARY,),
            aggregations=(Aggregation.NONE_SINGLE_SCORE,),
        ),
    )


@pytest.fixture
def test_graders(monkeypatch: pytest.MonkeyPatch) -> list[GraderSpec]:
    specs = [_test_grader(Measure.ERROR_RECOVERY), _test_grader(Measure.TOKEN_USAGE)]
    monkeypatch.setattr(catalogue_module, "library_catalogue", lambda: specs)
    return specs


def test_each_level_shows_only_its_detail(test_graders: list[GraderSpec]) -> None:
    overview, measures, graders = (
        catalogue_module.display_library_catalogue(level)
        for level in (
            prompts.CatalogueDisclosure.OVERVIEW,
            prompts.CatalogueDisclosure.MEASURES,
            prompts.CatalogueDisclosure.GRADERS,
        )
    )
    measure_names = [
        measure.value.replace("_", " ").capitalize() for measure in Measure
    ]

    for spec in test_graders:
        assert spec.name not in overview + measures
        assert spec.description not in overview + measures
        assert f"- {spec.name} [{spec.fqn}]: {spec.description}" in graders
    assert not any(name in overview + graders for name in measure_names)
    assert all(name in measures for name in measure_names)


def test_the_grouping_keeps_measures_without_a_grader_and_leaves_out_the_judge() -> (
    None
):
    judge = _test_grader(Measure.ERROR_RECOVERY).model_copy(
        update={"taxonomy": None, "fqn": "tests.graders.Judge"}
    )
    recovery = _test_grader(Measure.ERROR_RECOVERY)

    dimensions = catalogue_module.group_by_taxonomy([judge, recovery])

    entries = {
        entry.measure: entry.graders
        for dimension in dimensions
        for entry in dimension.measures
    }
    assert set(entries) == set(Measure)
    assert entries[Measure.ERROR_RECOVERY] == (recovery,)
    assert all(
        not graders for m, graders in entries.items() if m is not Measure.ERROR_RECOVERY
    )


@pytest.mark.parametrize(
    ("call", "level"),
    [
        ("clarify", prompts.CatalogueDisclosure.MEASURES),
        ("behaviours", prompts.CatalogueDisclosure.MEASURES),
        ("criteria", prompts.CatalogueDisclosure.GRADERS),
        ("personas", prompts.CatalogueDisclosure.OVERVIEW),
        ("scenarios", prompts.CatalogueDisclosure.OVERVIEW),
        ("test_cases", prompts.CatalogueDisclosure.OVERVIEW),
        ("chat:clarify", prompts.CatalogueDisclosure.MEASURES),
        ("chat:behaviours", prompts.CatalogueDisclosure.MEASURES),
        ("chat:criteria", prompts.CatalogueDisclosure.GRADERS),
        ("chat:scenarios", prompts.CatalogueDisclosure.GRADERS),
    ],
)
def test_each_model_call_receives_the_library_at_its_level(
    test_graders: list[GraderSpec], call: str, level: prompts.CatalogueDisclosure
) -> None:
    specification = desk_handover()
    context = interview_context()
    if call.startswith("chat:"):
        prompt = prompts.chat(
            specification, call.removeprefix("chat:"), "text", None, context=context
        )
    elif call in {"clarify", "behaviours"}:
        prompt = getattr(prompts, call)(specification, [], context=context)
    else:
        prompt = getattr(prompts, call)(specification, context=context)

    assert _xml_content(prompt.system, "grader_library").strip() == (
        catalogue_module.display_library_catalogue(level)
    )


def test_every_model_call_chooses_a_disclosure_level() -> None:
    assert set(prompts.DISCLOSURE) == set(get_args(prompts.ModelCall))
