"""Load and validate non-model interview settings and status copy."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources

import yaml

from metis.wizard.contracts.capabilities import (
    CapabilityCategory,
    CapabilityCategoryDefinition,
    CapabilityDefinition,
    CapabilityId,
)
from metis.wizard.contracts.config import InterviewConfig, PerspectiveDefinition
from metis.wizard.contracts.interview_state import Perspective
from metis.wizard.domain.permissions import InterviewStep

CONFIG_FILE = "config.yaml"
CAPABILITIES_FILE = "capabilities.yaml"

_CAPABILITY_COUNTS = (3, 6, 3)


class ConfigError(RuntimeError):
    """The package-owned interview configuration cannot be used."""


@dataclass(frozen=True)
class Config:
    """A complete, validated snapshot of the wizard's package-owned settings."""

    clarify_turn_cap: int
    opening_question: str
    working_status: str
    statuses: Mapping[InterviewStep, str]
    perspectives: tuple[PerspectiveDefinition, ...]
    capability_categories: tuple[CapabilityCategoryDefinition, ...]
    capability_source: str
    capability_attribution: str
    capability_license: str


def _error(key: str, detail: str, *, filename: str = CONFIG_FILE) -> ConfigError:
    return ConfigError(f"{filename} key '{key}' {detail}")


def _mapping(
    value: object, key: str, *, filename: str = CONFIG_FILE
) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise _error(key, "must be a mapping.", filename=filename)
    return value


def _required(
    mapping: Mapping[object, object], key: str, *, filename: str = CONFIG_FILE
) -> object:
    name = key.rsplit(".", maxsplit=1)[-1]
    if name not in mapping:
        raise _error(key, "is missing.", filename=filename)
    return mapping[name]


def _sequence(value: object, key: str, *, filename: str = CONFIG_FILE) -> list[object]:
    if not isinstance(value, list):
        raise _error(key, "must be a list.", filename=filename)
    return value


def _read_config_text() -> str:
    try:
        return (
            resources.files("metis.wizard")
            .joinpath(CONFIG_FILE)
            .read_text(encoding="utf-8")
        )
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        raise _error("<file>", "is missing.") from exc


def _read_capabilities_text() -> str:
    try:
        return (
            resources.files("metis.wizard")
            .joinpath(CAPABILITIES_FILE)
            .read_text(encoding="utf-8")
        )
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        raise _error("<file>", "is missing.", filename=CAPABILITIES_FILE) from exc


def _capability_text(mapping: Mapping[object, object], key: str) -> str:
    name = key.rsplit(".", maxsplit=1)[-1]
    if name not in mapping:
        raise _error(key, "is missing.", filename=CAPABILITIES_FILE)
    value = mapping[name]
    if not isinstance(value, str) or not value.strip():
        raise _error(key, "must be a non-empty string.", filename=CAPABILITIES_FILE)
    return value.strip()


def _load_capabilities() -> tuple[
    tuple[CapabilityCategoryDefinition, ...], str, str, str
]:
    """Read and validate the final, package-owned ARC capability catalogue."""
    try:
        raw = yaml.safe_load(_read_capabilities_text())
    except yaml.YAMLError as exc:
        raise _error(
            "<document>", f"is not valid YAML: {exc}.", filename=CAPABILITIES_FILE
        ) from exc

    document = _mapping(raw, "<document>", filename=CAPABILITIES_FILE)
    source = _capability_text(document, "source")
    attribution = _capability_text(document, "attribution")
    license_name = _capability_text(document, "license")
    categories_value = _sequence(
        _required(document, "categories", filename=CAPABILITIES_FILE),
        "categories",
        filename=CAPABILITIES_FILE,
    )
    expected_categories = tuple(CapabilityCategory)
    expected_capabilities = tuple(CapabilityId)
    if len(categories_value) != len(expected_categories):
        raise _error(
            "categories",
            f"must contain {len(expected_categories)} categories in the final catalogue.",
            filename=CAPABILITIES_FILE,
        )
    categories: list[CapabilityCategoryDefinition] = []
    seen_categories: set[CapabilityCategory] = set()
    capability_offset = 0

    for index, raw_category in enumerate(categories_value):
        key = f"categories[{index}]"
        entry = _mapping(raw_category, key, filename=CAPABILITIES_FILE)
        raw_id = _required(entry, f"{key}.id", filename=CAPABILITIES_FILE)
        if not isinstance(raw_id, str) or not raw_id.strip():
            raise _error(
                f"{key}.id", "must be a non-empty string.", filename=CAPABILITIES_FILE
            )
        try:
            category = CapabilityCategory(raw_id)
        except ValueError as exc:
            supported = ", ".join(item.value for item in CapabilityCategory)
            raise _error(
                f"{key}.id", f"must be one of: {supported}.", filename=CAPABILITIES_FILE
            ) from exc
        if category in seen_categories:
            raise _error(f"{key}.id", "is duplicated.", filename=CAPABILITIES_FILE)
        expected_category = expected_categories[index]
        if category is not expected_category:
            raise _error(
                f"{key}.id",
                f"must be '{expected_category.value}' at this position.",
                filename=CAPABILITIES_FILE,
            )
        seen_categories.add(category)
        name = _capability_text(entry, f"{key}.name")
        items = _sequence(
            _required(entry, f"{key}.capabilities", filename=CAPABILITIES_FILE),
            f"{key}.capabilities",
            filename=CAPABILITIES_FILE,
        )
        expected_count = _CAPABILITY_COUNTS[index]
        if len(items) != expected_count:
            raise _error(
                f"{key}.capabilities",
                f"must contain {expected_count} capabilities in the final catalogue.",
                filename=CAPABILITIES_FILE,
            )
        capabilities: list[CapabilityDefinition] = []
        seen_ids: set[CapabilityId] = set()
        for item_index, raw_item in enumerate(items):
            item_key = f"{key}.capabilities[{item_index}]"
            item = _mapping(raw_item, item_key, filename=CAPABILITIES_FILE)
            item_id = _required(item, f"{item_key}.id", filename=CAPABILITIES_FILE)
            if not isinstance(item_id, str) or not item_id.strip():
                raise _error(
                    f"{item_key}.id",
                    "must be a non-empty string.",
                    filename=CAPABILITIES_FILE,
                )
            try:
                capability_id = CapabilityId(item_id)
            except ValueError as exc:
                supported = ", ".join(item.value for item in CapabilityId)
                raise _error(
                    f"{item_key}.id",
                    f"must be one of: {supported}.",
                    filename=CAPABILITIES_FILE,
                ) from exc
            if capability_id in seen_ids:
                raise _error(
                    f"{item_key}.id", "is duplicated.", filename=CAPABILITIES_FILE
                )
            expected_id = expected_capabilities[capability_offset + item_index]
            if capability_id is not expected_id:
                raise _error(
                    f"{item_key}.id",
                    f"must be '{expected_id.value}' at this position.",
                    filename=CAPABILITIES_FILE,
                )
            seen_ids.add(capability_id)
            capabilities.append(
                CapabilityDefinition(
                    id=capability_id,
                    name=_capability_text(item, f"{item_key}.name"),
                    description=_capability_text(item, f"{item_key}.description"),
                )
            )
        categories.append(
            CapabilityCategoryDefinition(
                id=category,
                name=name,
                capabilities=capabilities,
            )
        )
        capability_offset += len(items)

    return tuple(categories), source, attribution, license_name


def load_config() -> Config:
    """Read and validate a fresh interview-configuration snapshot."""
    try:
        raw = yaml.safe_load(_read_config_text())
    except yaml.YAMLError as exc:
        raise _error("<document>", f"is not valid YAML: {exc}.") from exc

    document = _mapping(raw, "<document>")
    settings = _mapping(_required(document, "settings"), "settings")
    statuses = _mapping(_required(document, "statuses"), "statuses")

    turn_cap = _required(settings, "settings.clarify_turn_cap")
    if isinstance(turn_cap, bool) or not isinstance(turn_cap, int) or turn_cap <= 0:
        raise _error("settings.clarify_turn_cap", "must be a positive integer.")

    opening_question = _required(document, "opening_question")
    if not isinstance(opening_question, str) or not opening_question.strip():
        raise _error("opening_question", "must be a non-empty string.")

    perspective_values = _sequence(_required(document, "perspectives"), "perspectives")
    perspectives: list[PerspectiveDefinition] = []
    seen: set[Perspective] = set()
    for index, raw_perspective in enumerate(perspective_values):
        key = f"perspectives[{index}]"
        entry = _mapping(raw_perspective, key)
        raw_id = _required(entry, f"{key}.id")
        if not isinstance(raw_id, str) or not raw_id.strip():
            raise _error(f"{key}.id", "must be a non-empty string.")
        try:
            perspective = Perspective(raw_id)
        except ValueError as exc:
            supported = ", ".join(item.value for item in Perspective)
            raise _error(f"{key}.id", f"must be one of: {supported}.") from exc
        if perspective in seen:
            raise _error(f"{key}.id", "is duplicated.")
        seen.add(perspective)
        label = _required(entry, f"{key}.label")
        if not isinstance(label, str) or not label.strip():
            raise _error(f"{key}.label", "must be a non-empty string.")
        question = _required(entry, f"{key}.question")
        if (
            not isinstance(question, str)
            or not question.strip()
            or "\n" in question
            or "\r" in question
        ):
            raise _error(f"{key}.question", "must be a non-empty one-line string.")
        perspectives.append(
            PerspectiveDefinition(id=perspective, label=label, question=question)
        )

    missing = [item.value for item in Perspective if item not in seen]
    if missing:
        raise _error(
            "perspectives",
            f"is missing supported id(s): {', '.join(missing)}.",
        )

    if "prioritise" in statuses:
        raise _error("statuses.prioritise", "was removed and must not be present.")

    working_status = _required(statuses, "statuses.working")
    if not isinstance(working_status, str) or not working_status.strip():
        raise _error("statuses.working", "must be a non-empty string.")

    checked: dict[InterviewStep, str] = {}
    for step in InterviewStep:
        key = f"statuses.{step.value}"
        value = _required(statuses, key)
        if not isinstance(value, str) or not value.strip():
            raise _error(key, "must be a non-empty string.")
        checked[step] = value

    (
        capability_categories,
        capability_source,
        capability_attribution,
        capability_license,
    ) = _load_capabilities()

    return Config(
        clarify_turn_cap=turn_cap,
        opening_question=opening_question,
        working_status=working_status,
        statuses=checked,
        perspectives=tuple(perspectives),
        capability_categories=capability_categories,
        capability_source=capability_source,
        capability_attribution=capability_attribution,
        capability_license=capability_license,
    )


def clarify_turn_cap() -> int:
    """Return the current maximum number of clarify questions."""
    return load_config().clarify_turn_cap


def status_for(step: InterviewStep) -> str:
    """Return the current package-owned status for an interview step."""
    return load_config().statuses[step]


def working_status() -> str:
    """Return the package-owned general status for active interview work."""
    return load_config().working_status


def opening_question() -> str:
    """Return the package-owned question shown before the first model call."""
    return load_config().opening_question


def interview_client_config() -> InterviewConfig:
    """Return the complete package-owned configuration for a wizard door."""
    current = load_config()
    return InterviewConfig(
        opening_question=current.opening_question,
        working_status=current.working_status,
        perspectives=list(current.perspectives),
        capability_categories=[
            category.model_copy(deep=True) for category in current.capability_categories
        ],
    )


__all__ = [
    "CONFIG_FILE",
    "CAPABILITIES_FILE",
    "Config",
    "ConfigError",
    "clarify_turn_cap",
    "interview_client_config",
    "load_config",
    "opening_question",
    "status_for",
    "working_status",
]
