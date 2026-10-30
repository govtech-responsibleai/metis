"""Small semantic enums shared by the document and conversation contracts."""

from enum import StrEnum


class InteractionType(StrEnum):
    """How text was authored or how the wizard exchanges a response."""

    CHAT = "chat"
    CHOICE = "choice"
    FORM = "form"
