"""Load and compose the package-owned prompts for each model call.

The catalogue is model-facing text. This module owns its validation and substitution, so the
gateway receives a complete value and never needs to know the YAML shape.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from string import Template
from typing import TYPE_CHECKING, Literal, TypeAlias, cast

import yaml

from metis.wizard.application.config import (
    clarify_turn_cap,
    load_config,
    opening_question,
)
from metis.wizard.application.matching.library_catalogue import (
    CatalogueDisclosure,
    display_library_catalogue,
)
from metis.wizard.contracts.interview_state import (
    CapabilityConfidence,
    InterviewContext,
    Perspective,
)
from metis.wizard.domain.permissions import InterviewStep

if TYPE_CHECKING:
    from collections.abc import Iterable

    from metis.wizard.contracts.grader_spec import GraderSpec
    from metis.wizard.contracts.interview_state import InterviewMessage
    from metis.wizard.domain.specification import Specification

PROMPTS_FILE = "prompts.yaml"
PRIMER_FILE = "agentic-primer.md"
PERSPECTIVES_DIR = "perspectives"

ModelCall: TypeAlias = Literal[
    "clarify",
    "behaviours",
    "criteria",
    "personas",
    "scenarios",
    "test_cases",
    "chat",
    "match_graders",
]

_MODEL_CALL_PLACEHOLDERS: dict[str, frozenset[str]] = {
    "clarify": frozenset(
        {
            "specification",
            "history",
            "perspective",
            "capability_evidence",
            "questions_asked",
            "question_cap",
            "questions_remaining",
        }
    ),
    "behaviours": frozenset(
        {"specification", "history", "perspective", "capability_evidence"}
    ),
    "criteria": frozenset({"specification"}),
    "personas": frozenset({"specification"}),
    "scenarios": frozenset({"specification"}),
    "test_cases": frozenset({"specification"}),
    "chat": frozenset({"specification", "step", "text", "scope"}),
}
_MATCH_GRADERS_PLACEHOLDERS = frozenset({"grader_library", "criteria"})
_SYSTEM_PLACEHOLDERS = frozenset(
    {
        "patch_rules",
        "primer",
        "arc_catalogue",
        "grader_library",
        "perspective",
        "opening_description",
        "documents",
        "available_fixtures",
        "perspective_guidance",
        "capability_evidence",
    }
)


# Each call gets only the detail it needs. A new call must choose a level here.
DISCLOSURE: dict[ModelCall, CatalogueDisclosure] = {
    "clarify": CatalogueDisclosure.MEASURES,
    "behaviours": CatalogueDisclosure.MEASURES,
    "criteria": CatalogueDisclosure.GRADERS,
    "personas": CatalogueDisclosure.OVERVIEW,
    "scenarios": CatalogueDisclosure.OVERVIEW,
    "test_cases": CatalogueDisclosure.OVERVIEW,
    "chat": CatalogueDisclosure.MEASURES,
    "match_graders": CatalogueDisclosure.GRADERS,
}

# From the Criteria step on, the user can ask chat about the grader of a Criterion.
_CHAT_GRADERS_STEPS = frozenset(
    step
    for step in InterviewStep
    if step not in {InterviewStep.CLARIFY, InterviewStep.BEHAVIOURS}
)


def _disclosure(call_name: ModelCall, step: str | None = None) -> CatalogueDisclosure:
    if call_name == "chat" and step in _CHAT_GRADERS_STEPS:
        return CatalogueDisclosure.GRADERS
    return DISCLOSURE[call_name]


class PromptCatalogError(RuntimeError):
    """The package-owned prompt catalogue cannot be used."""


@dataclass(frozen=True)
class ModelPrompt:
    """One complete, immutable model call composed from one catalogue snapshot."""

    name: str
    system: str
    user: str


@dataclass(frozen=True)
class PromptCatalog:
    """A complete, validated snapshot of ``prompts.yaml``."""

    system_template: str
    patch_rules: str
    model_calls: Mapping[str, str]
    match_graders_system: str
    match_graders_user: str


def _error(key: str, detail: str) -> PromptCatalogError:
    return PromptCatalogError(f"{PROMPTS_FILE} key '{key}' {detail}")


def _mapping(value: object, key: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise _error(key, "must be a mapping.")
    return value


def _required(mapping: Mapping[object, object], key: str) -> object:
    name = key.rsplit(".", maxsplit=1)[-1]
    if name not in mapping:
        raise _error(key, "is missing.")
    return mapping[name]


def _text(mapping: Mapping[object, object], key: str) -> str:
    value = _required(mapping, key)
    if not isinstance(value, str) or not value.strip():
        raise _error(key, "must be a non-empty string.")
    return value


def _validate_template(value: str, key: str, allowed: frozenset[str]) -> None:
    template = Template(value)
    if not template.is_valid():
        raise _error(key, "is not a valid $name template.")
    unsupported = sorted(
        identifier
        for identifier in template.get_identifiers()
        if identifier not in allowed
    )
    if unsupported:
        names = ", ".join(unsupported)
        raise _error(key, f"uses unsupported placeholder(s): {names}.")


def _read_catalog_text() -> str:
    try:
        return (
            resources.files("metis.wizard")
            .joinpath(PROMPTS_FILE)
            .read_text(encoding="utf-8")
        )
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        raise _error("<file>", "is missing.") from exc


def load_prompt_catalog() -> PromptCatalog:
    """Read and validate a fresh prompt-catalogue snapshot."""
    try:
        raw = yaml.safe_load(_read_catalog_text())
    except yaml.YAMLError as exc:
        raise _error("<document>", f"is not valid YAML: {exc}.") from exc

    document = _mapping(raw, "<document>")
    system = _mapping(_required(document, "system"), "system")
    model_calls = _mapping(_required(document, "model_calls"), "model_calls")

    system_template = _text(system, "system.template")
    patch_rules = _text(system, "system.patch_rules")
    _validate_template(system_template, "system.template", _SYSTEM_PLACEHOLDERS)

    calls: dict[str, str] = {}
    for name, allowed in _MODEL_CALL_PLACEHOLDERS.items():
        value = _text(model_calls, f"model_calls.{name}")
        _validate_template(value, f"model_calls.{name}", allowed)
        calls[name] = value

    match = _mapping(_required(document, "match_graders"), "match_graders")
    match_system = _text(match, "match_graders.system")
    match_user = _text(match, "match_graders.user")
    _validate_template(match_user, "match_graders.user", _MATCH_GRADERS_PLACEHOLDERS)

    return PromptCatalog(
        system_template=system_template,
        patch_rules=patch_rules,
        model_calls=calls,
        match_graders_system=match_system,
        match_graders_user=match_user,
    )


def _substitute(template: str, key: str, values: Mapping[str, str]) -> str:
    try:
        return Template(template).substitute(values)
    except (KeyError, ValueError) as exc:
        missing = exc.args[0] if isinstance(exc, KeyError) else "<template>"
        raise _error(key, f"could not substitute '{missing}'.") from exc


def primer() -> str:
    """Read the agentic background guide without a process-lifetime cache."""
    try:
        return (
            resources.files("metis.wizard.application")
            .joinpath(PRIMER_FILE)
            .read_text(encoding="utf-8")
        )
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        raise PromptCatalogError(f"{PRIMER_FILE} is missing.") from exc


def _perspective_id(context: InterviewContext | None) -> str:
    selected = context.perspective if context is not None else Perspective.END_USER
    return selected.value


def _system_message(
    catalog: PromptCatalog,
    context: InterviewContext | None = None,
    *,
    disclosure: CatalogueDisclosure,
    available_fixtures: list[str] | None = None,
) -> str:
    return _substitute(
        catalog.system_template,
        "system.template",
        {
            "patch_rules": catalog.patch_rules,
            "primer": primer(),
            "arc_catalogue": arc_catalogue(),
            "grader_library": display_library_catalogue(disclosure),
            "perspective": _perspective_id(context),
            "perspective_guidance": _perspective(context),
            "capability_evidence": _capability_evidence(context),
            "opening_description": json.dumps(
                context.opening_description if context else "",
                ensure_ascii=False,
            ),
            "documents": json.dumps(
                [document.model_dump(mode="json") for document in context.documents]
                if context
                else [],
                ensure_ascii=False,
                indent=2,
            ),
            "available_fixtures": json.dumps(available_fixtures or []),
        },
    )


def _specification(specification: Specification) -> str:
    return json.dumps(specification.model_dump(mode="json"), indent=2)


def _transcript(history: list[InterviewMessage]) -> str:
    return "\n".join(f"{t.role}: {t.text}" for t in history)


def _perspective(context: InterviewContext | None) -> str:
    """Read all supported perspective files and return the selected one, without caching."""
    selected = context.perspective if context is not None else Perspective.END_USER
    try:
        directory = resources.files("metis.wizard.application").joinpath(
            PERSPECTIVES_DIR
        )
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        raise PromptCatalogError(f"{PERSPECTIVES_DIR} is missing.") from exc
    content: dict[Perspective, str] = {}
    for perspective in Perspective:
        path = directory.joinpath(f"{perspective.value}.md")
        try:
            text = path.read_text(encoding="utf-8")
        except (FileNotFoundError, ModuleNotFoundError) as exc:
            raise PromptCatalogError(
                f"{PERSPECTIVES_DIR}/{perspective.value}.md is missing."
            ) from exc
        if not text.strip():
            raise PromptCatalogError(
                f"{PERSPECTIVES_DIR}/{perspective.value}.md is empty."
            )
        content[perspective] = text.strip()
    return f"{selected.value}\n{content[selected]}"


def arc_catalogue() -> str:
    """Render the fixed ARC catalogue for the general model context."""
    current = load_config()
    lines = ["The ARC capability catalogue:"]
    for category in current.capability_categories:
        lines.append(f"{category.name} ({category.id.value}):")
        for capability in category.capabilities:
            lines.append(
                f"- {capability.name} [{capability.id.value}]: {capability.description}"
            )
    return "\n".join(lines)


def _capability_evidence(context: InterviewContext | None) -> str:
    """Describe the user's capability evidence without treating omissions as negatives."""
    if context is None or context.capability_evidence is None:
        return "Capability evidence: unspecified. Infer abilities only from target evidence. Do not infer absence or invent confidence."
    evidence = context.capability_evidence
    selected = ", ".join(item.value for item in evidence.known_capability_ids) or "none"
    guidance = {
        CapabilityConfidence.LOW: (
            "Treat the selection as possibly incomplete while you infer the provisional "
            "evaluation map. Consider plausible omitted capabilities across the Clarify "
            "sequence, but ask about one only when its presence or operation could "
            "materially change that map."
        ),
        CapabilityConfidence.MEDIUM: (
            "Consider an unselected capability only when it relates to the target "
            "description or later answers and could materially change the provisional "
            "evaluation map."
        ),
        CapabilityConfidence.HIGH: (
            "Rely on the selection unless other target evidence suggests an omitted "
            "capability that could materially change the provisional evaluation map."
        ),
    }[evidence.confidence]
    return (
        f"Known capability ids selected by the user: {selected}.\n"
        f"Selection confidence: {evidence.confidence.value}.\n"
        "Selected capabilities are known present. Unselected capabilities are not known "
        "absent.\n"
        f"Guidance: {guidance}"
    )


def _clarify_progress(history: list[InterviewMessage]) -> tuple[int, int, int]:
    """Return questions asked, the package cap, and questions remaining."""
    asked = sum(1 for message in history if message.role == "assistant")
    if (
        history
        and history[0].role == "assistant"
        and history[0].text == opening_question()
    ):
        asked -= 1
    cap = clarify_turn_cap()
    asked = max(0, asked)
    return asked, cap, max(0, cap - asked)


def _compose(
    template_name: str,
    values: Mapping[str, str],
    *,
    call_name: ModelCall | None = None,
    context: InterviewContext | None = None,
    available_fixtures: list[str] | None = None,
    step: str | None = None,
) -> ModelPrompt:
    """Compose system and user messages from one fresh catalogue snapshot."""
    catalog = load_prompt_catalog()
    user = _substitute(
        catalog.model_calls[template_name],
        f"model_calls.{template_name}",
        values,
    )
    name = cast("ModelCall", call_name or template_name)
    return ModelPrompt(
        name=name,
        system=_system_message(
            catalog,
            context,
            disclosure=_disclosure(name, step),
            available_fixtures=available_fixtures,
        ),
        user=user,
    )


def clarify(
    specification: Specification,
    history: list[InterviewMessage],
    context: InterviewContext | None = None,
) -> ModelPrompt:
    questions_asked, question_cap, questions_remaining = _clarify_progress(history)
    return _compose(
        "clarify",
        {
            "specification": _specification(specification),
            "history": _transcript(history),
            "perspective": _perspective(context),
            "capability_evidence": _capability_evidence(context),
            "questions_asked": str(questions_asked),
            "question_cap": str(question_cap),
            "questions_remaining": str(questions_remaining),
        },
        call_name="clarify",
        context=context,
    )


def behaviours(
    specification: Specification,
    history: list[InterviewMessage],
    context: InterviewContext | None = None,
) -> ModelPrompt:
    return _compose(
        "behaviours",
        {
            "specification": _specification(specification),
            "history": _transcript(history),
            "perspective": _perspective(context),
            "capability_evidence": _capability_evidence(context),
        },
        context=context,
    )


def criteria(
    specification: Specification, context: InterviewContext | None = None
) -> ModelPrompt:
    return _compose(
        "criteria", {"specification": _specification(specification)}, context=context
    )


def personas(
    specification: Specification, context: InterviewContext | None = None
) -> ModelPrompt:
    return _compose(
        "personas", {"specification": _specification(specification)}, context=context
    )


def scenarios(
    specification: Specification, context: InterviewContext | None = None
) -> ModelPrompt:
    return _compose(
        "scenarios",
        {"specification": _specification(specification)},
        context=context,
        available_fixtures=context.document_names if context else [],
    )


def test_cases(
    specification: Specification, context: InterviewContext | None = None
) -> ModelPrompt:
    return _compose(
        "test_cases",
        {"specification": _specification(specification)},
        context=context,
    )


def chat(
    specification: Specification,
    step: str,
    text: str,
    target: str | None,
    context: InterviewContext | None = None,
) -> ModelPrompt:
    scope = f"\nThey are talking about {target}." if target else ""
    return _compose(
        "chat",
        {
            "specification": _specification(specification),
            "step": step,
            "text": text,
            "scope": scope,
        },
        context=context,
        available_fixtures=(context.document_names if context is not None else []),
        step=step,
    )


def match_graders(specs: Iterable[GraderSpec], criteria: str) -> ModelPrompt:
    """Ask which of ``specs`` fits each Criterion. ``criteria`` is the Criteria as JSON."""
    catalog = load_prompt_catalog()
    return ModelPrompt(
        name="match_graders",
        system=catalog.match_graders_system,
        user=_substitute(
            catalog.match_graders_user,
            "match_graders.user",
            {
                "grader_library": display_library_catalogue(
                    DISCLOSURE["match_graders"], specs
                ),
                "criteria": criteria,
            },
        ),
    )


__all__ = [
    "DISCLOSURE",
    "CatalogueDisclosure",
    "ModelCall",
    "ModelPrompt",
    "PROMPTS_FILE",
    "PRIMER_FILE",
    "PERSPECTIVES_DIR",
    "PromptCatalog",
    "PromptCatalogError",
    "arc_catalogue",
    "behaviours",
    "chat",
    "clarify",
    "criteria",
    "load_prompt_catalog",
    "match_graders",
    "personas",
    "primer",
    "scenarios",
    "test_cases",
]
