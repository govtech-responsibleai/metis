"""The fixed ARC capability catalogue and its public value types."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CapabilityCategory(StrEnum):
    """The three categories in the final ARC capability catalogue."""

    COGNITIVE = "cognitive"
    INTERACTION = "interaction"
    OPERATIONAL = "operational"


class CapabilityId(StrEnum):
    """A METIS id for one ARC capability."""

    PLANNING_GOAL_MANAGEMENT = "planning_goal_management"
    AGENT_DELEGATION = "agent_delegation"
    TOOL_USE = "tool_use"
    MULTIMODAL_UNDERSTANDING_GENERATION = "multimodal_understanding_generation"
    OFFICIAL_COMMUNICATION = "official_communication"
    BUSINESS_TRANSACTIONS = "business_transactions"
    INTERNET_SEARCH_ACCESS = "internet_search_access"
    COMPUTER_USE = "computer_use"
    OTHER_PROGRAMMATIC_INTERFACES = "other_programmatic_interfaces"
    CODE_EXECUTION = "code_execution"
    FILE_DATA_MANAGEMENT = "file_data_management"
    SYSTEM_MANAGEMENT = "system_management"


class CapabilityDefinition(BaseModel):
    """The public display definition for one capability."""

    model_config = ConfigDict(extra="forbid")

    id: CapabilityId
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)


class CapabilityCategoryDefinition(BaseModel):
    """An ordered category and its ordered capability definitions."""

    model_config = ConfigDict(extra="forbid")

    id: CapabilityCategory
    name: str = Field(min_length=1)
    capabilities: list[CapabilityDefinition]


__all__ = [
    "CapabilityCategory",
    "CapabilityCategoryDefinition",
    "CapabilityDefinition",
    "CapabilityId",
]
