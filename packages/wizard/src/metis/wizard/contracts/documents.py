"""Wire contracts for documents attached to an Interview."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from metis.wizard.domain.documents import (
    EXTRACTION_DOCUMENT_EXTENSIONS,
    FIXTURE_DOCUMENT_EXTENSIONS,
    MAX_DOCUMENT_BYTES,
    MAX_DOCUMENT_TEXT_CHARACTERS,
    MAX_DOCUMENTS,
    MAX_DOCX_ARCHIVE_ENTRIES,
    MAX_DOCX_EXPANDED_BYTES,
    MAX_EXTRACTION_FILE_BYTES,
    MAX_EXTRACTION_REQUEST_BYTES,
    MAX_INTERVIEW_TEXT_CHARACTERS,
    MAX_PDF_EXPANDED_BYTES,
    fixture_name_identity,
    normalize_fixture_name,
)


class DocumentExtractionErrorCode(StrEnum):
    """Stable causes returned when an uploaded Interview document cannot be read."""

    TOO_MANY_DOCUMENTS = "too_many_documents"
    INVALID_FILENAME = "invalid_filename"
    UNSUPPORTED_FILE_TYPE = "unsupported_file_type"
    FILE_TOO_LARGE = "file_too_large"
    REQUEST_TOO_LARGE = "request_too_large"
    MALFORMED_FILE = "malformed_file"
    ENCRYPTED_PDF = "encrypted_pdf"
    EMPTY_DOCUMENT = "empty_document"
    TEXT_TOO_LARGE = "text_too_large"


class ExtractedDocument(BaseModel):
    """One extracted file returned to the caller that owns the original bytes."""

    model_config = ConfigDict(extra="forbid")

    name: str
    text: str = Field(min_length=1, max_length=MAX_DOCUMENT_TEXT_CHARACTERS)


class DocumentExtractionResult(BaseModel):
    """An all-or-nothing extraction response in upload order."""

    model_config = ConfigDict(extra="forbid")

    documents: list[ExtractedDocument]


class InterviewDocument(BaseModel):
    """One opening file, with extracted text when a reader supplied it."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    text: str | None = Field(default=None, max_length=MAX_DOCUMENT_TEXT_CHARACTERS)

    @field_validator("name")
    @classmethod
    def _canonical_basename(cls, value: str) -> str:
        normalized = normalize_fixture_name(value)
        if normalized != value:
            raise ValueError("Document names must be normalized basenames.")
        return normalized

    @field_validator("text")
    @classmethod
    def _require_nonblank_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Extracted document text must not be blank.")
        return value

    @field_validator("name")
    @classmethod
    def _require_accepted_file_type(cls, value: str) -> str:
        extension = Path(value).suffix.lower().removeprefix(".")
        if extension not in FIXTURE_DOCUMENT_EXTENSIONS:
            raise ValueError("Unsupported document file type.")
        return value

    @model_validator(mode="after")
    def _validate_text_format(self) -> Self:
        extension = Path(self.name).suffix.lower().removeprefix(".")
        if self.text is not None and extension not in EXTRACTION_DOCUMENT_EXTENSIONS:
            raise ValueError("Extracted text requires a supported document format.")
        return self


class InterviewConfigDocumentLimits(BaseModel):
    """File and text limits a wizard door needs before it accepts uploads."""

    model_config = ConfigDict(extra="forbid")

    max_documents: int = MAX_DOCUMENTS
    max_initial_bytes: int = MAX_DOCUMENT_BYTES
    max_extraction_file_bytes: int = MAX_EXTRACTION_FILE_BYTES
    max_extraction_request_bytes: int = MAX_EXTRACTION_REQUEST_BYTES
    max_text_characters_per_document: int = MAX_DOCUMENT_TEXT_CHARACTERS
    max_text_characters_total: int = MAX_INTERVIEW_TEXT_CHARACTERS
    max_docx_expanded_bytes: int = MAX_DOCX_EXPANDED_BYTES
    max_docx_archive_entries: int = MAX_DOCX_ARCHIVE_ENTRIES
    max_pdf_expanded_bytes: int = MAX_PDF_EXPANDED_BYTES
    fixture_extensions: list[str] = Field(
        default_factory=lambda: sorted(FIXTURE_DOCUMENT_EXTENSIONS)
    )
    extraction_extensions: list[str] = Field(
        default_factory=lambda: sorted(EXTRACTION_DOCUMENT_EXTENSIONS)
    )


def validate_interview_documents(
    documents: list[InterviewDocument],
) -> list[InterviewDocument]:
    """Reject duplicate names and document sets above the shared context limits."""
    if len(documents) > MAX_DOCUMENTS:
        raise ValueError(f"An Interview can contain at most {MAX_DOCUMENTS} documents.")
    identities: set[str] = set()
    text_size = 0
    for document in documents:
        identity = fixture_name_identity(document.name)
        if identity in identities:
            raise ValueError(f"A document named '{document.name}' already exists.")
        identities.add(identity)
        if document.text is not None:
            text_size += len(document.text)
        if text_size > MAX_INTERVIEW_TEXT_CHARACTERS:
            raise ValueError(
                f"Interview document text cannot exceed {MAX_INTERVIEW_TEXT_CHARACTERS:,} characters in total."
            )
    # Original bytes are checked at upload and again by the browser before start. They are not
    # present in the stateless Interview contract and cannot be measured here.
    return documents


__all__ = [
    "DocumentExtractionErrorCode",
    "DocumentExtractionResult",
    "ExtractedDocument",
    "InterviewDocument",
    "InterviewConfigDocumentLimits",
    "validate_interview_documents",
]
