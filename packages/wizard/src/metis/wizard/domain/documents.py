"""Shared filename rules, accepted formats, and document processing limits."""

from __future__ import annotations

import unicodedata

MAX_DOCUMENTS = 20
MAX_DOCUMENT_BYTES = 100_000_000
MAX_EXTRACTION_FILE_BYTES = 10_000_000
MAX_EXTRACTION_REQUEST_BYTES = 20_000_000
MAX_DOCUMENT_TEXT_CHARACTERS = 500_000
MAX_INTERVIEW_TEXT_CHARACTERS = 1_000_000
MAX_DOCX_EXPANDED_BYTES = 50_000_000
MAX_DOCX_ARCHIVE_ENTRIES = 2_000
MAX_PDF_EXPANDED_BYTES = 50_000_000

FIXTURE_DOCUMENT_EXTENSIONS = frozenset(
    {
        "csv",
        "yaml",
        "yml",
        "pdf",
        "docx",
        "xlsx",
        "pptx",
        "txt",
        "json",
        "png",
        "jpg",
        "gif",
        "webp",
        "md",
        "html",
    }
)
EXTRACTION_DOCUMENT_EXTENSIONS = frozenset(
    {"txt", "md", "yaml", "yml", "json", "csv", "pdf", "docx"}
)

_WINDOWS_PUNCTUATION = set('<>:"/\\|?*')
_WINDOWS_DEVICES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{n}" for n in range(1, 10)),
    *(f"LPT{n}" for n in range(1, 10)),
}


def fixture_name_identity(name: str) -> str:
    """Return the cross-platform collision key for a fixture name."""
    return unicodedata.normalize("NFC", name).casefold()


def normalize_fixture_name(name: str) -> str:
    """Return a safe logical basename or raise ``ValueError``.

    The check is stricter than the host filesystem so a ZIP can move between macOS, Linux and
    Windows without creating a path or filename collision.
    """
    if not isinstance(name, str):
        raise ValueError("Fixture names must be text.")
    normalized = unicodedata.normalize("NFC", name.strip())
    if not normalized or normalized in {".", ".."}:
        raise ValueError("Fixture names cannot be blank, '.' or '..'.")
    if any(separator in normalized for separator in ("/", "\\")):
        raise ValueError("Fixture names must be basenames without path separators.")
    if any(
        char == "\x00" or unicodedata.category(char).startswith("C")
        for char in normalized
    ):
        raise ValueError("Fixture names cannot contain control characters.")
    # A comma separates file names in a multiple-choice form value, so a name cannot hold one.
    if "," in normalized:
        raise ValueError("Fixture names cannot contain a comma. Rename the file.")
    if any(char in _WINDOWS_PUNCTUATION for char in normalized):
        raise ValueError("Fixture names contain characters that are not portable.")
    if normalized.endswith((".", " ")):
        raise ValueError("Fixture names cannot end with a dot or space.")
    stem = normalized.split(".", 1)[0].upper()
    if stem in _WINDOWS_DEVICES:
        raise ValueError("Fixture names cannot use a reserved device name.")
    return normalized
