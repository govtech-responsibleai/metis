"""metis.wizard — Evaluation config generator.

The names exported here are the headless package facade. Doors and providers live behind
internal modules so moving them does not change the imports used by callers.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING

from metis.core import Status
from metis.core import __version__ as core_version
from metis.library.taxonomy import MEASURE_DIMENSIONS
from metis.wizard.application import (
    DocumentExtractionError,
    InterviewState,
    compile_specification,
    derive_stage,
    extract_documents,
    handle_interview,
    package_specification,
)
from metis.wizard.application.compile import (
    CompilationError,
    SpecificationArchive,
    SpecificationError,
    SpecificationFixture,
    compile_experiment,
    render_review,
    write_experiment,
    write_review,
)
from metis.wizard.application.config import (
    interview_client_config,
    working_status,
)
from metis.wizard.application.connection import (
    check_connection,
    set_connection,
    validate_binding,
)
from metis.wizard.application.interviewer import InterviewerUnavailable
from metis.wizard.application.matching.library_catalogue import (
    library_catalogue as _library_catalogue,
)
from metis.wizard.contracts import (
    AnyRequest,
    AnyResponse,
    CapabilityCategory,
    CapabilityCategoryDefinition,
    CapabilityConfidence,
    CapabilityDefinition,
    CapabilityEvidence,
    CapabilityId,
    ChatRequest,
    ChatResponse,
    ChoiceRequest,
    ChoiceResponse,
    CompileResult,
    ConnectionCheckRequest,
    ConnectionCheckResult,
    ConnectionFieldError,
    ConnectionProbe,
    ConnectionStatus,
    ConnectionTransport,
    DocumentExtractionErrorCode,
    DocumentExtractionResult,
    ExtractedDocument,
    FormRequest,
    FormResponse,
    InterviewConfig,
    InterviewConfigDocumentLimits,
    InterviewConnectionRequest,
    InterviewContext,
    InterviewDocument,
    InterviewEndRequest,
    InterviewErrorCode,
    InterviewFailure,
    InterviewOutcome,
    InterviewRequest,
    InterviewResult,
    InterviewStartRequest,
    InterviewSuccess,
    InterviewTurnRequest,
    MissingData,
    MissingDataCode,
    Perspective,
    PerspectiveDefinition,
    Specification,
    TargetConnection,
    UserResponse,
    WizardRequest,
)
from metis.wizard.contracts.grader_spec import GraderSummary
from metis.wizard.domain.permissions import InterviewStep

if TYPE_CHECKING:
    from metis.core.model_settings import RoleSettings


def configure_interview_runtime(*, interview: RoleSettings) -> None:
    """Configure the production collaborators used by :func:`handle_interview`."""
    from metis.wizard.bootstrap import configure_interview_runtime

    configure_interview_runtime(interview=interview)


def grader_catalogue() -> list[GraderSummary]:
    """Return installed grader display metadata without exposing matcher internals."""
    return [
        GraderSummary(
            fqn=spec.fqn,
            name=spec.name,
            description=spec.description,
            uses_criterion_description=spec.uses_criterion_description,
            settings=spec.settings,
            taxonomy=spec.taxonomy,
            dimension=MEASURE_DIMENSIONS[spec.taxonomy.measure]
            if spec.taxonomy and spec.taxonomy.measure
            else None,
        )
        for spec in _library_catalogue()
    ]


try:
    __version__ = version("metis-wizard")
except PackageNotFoundError:
    __version__ = "0.0.0.dev0"

__all__ = [
    "AnyRequest",
    "AnyResponse",
    "ChatRequest",
    "ChatResponse",
    "CapabilityCategory",
    "CapabilityCategoryDefinition",
    "CapabilityConfidence",
    "CapabilityDefinition",
    "CapabilityEvidence",
    "CapabilityId",
    "CompilationError",
    "CompileResult",
    "ConnectionCheckRequest",
    "ConnectionCheckResult",
    "ConnectionFieldError",
    "ConnectionProbe",
    "ConnectionStatus",
    "ConnectionTransport",
    "ChoiceRequest",
    "ChoiceResponse",
    "FormRequest",
    "FormResponse",
    "InterviewConnectionRequest",
    "InterviewEndRequest",
    "InterviewContext",
    "InterviewDocument",
    "DocumentExtractionError",
    "DocumentExtractionErrorCode",
    "DocumentExtractionResult",
    "ExtractedDocument",
    "InterviewConfig",
    "InterviewConfigDocumentLimits",
    "InterviewErrorCode",
    "InterviewFailure",
    "InterviewOutcome",
    "InterviewRequest",
    "InterviewResult",
    "InterviewStartRequest",
    "InterviewState",
    "InterviewSuccess",
    "InterviewTurnRequest",
    "InterviewStep",
    "InterviewerUnavailable",
    "MissingData",
    "MissingDataCode",
    "GraderSummary",
    "Specification",
    "Perspective",
    "PerspectiveDefinition",
    "SpecificationArchive",
    "SpecificationFixture",
    "SpecificationError",
    "Status",
    "TargetConnection",
    "UserResponse",
    "WizardRequest",
    "__version__",
    "check_connection",
    "compile_experiment",
    "compile_specification",
    "configure_interview_runtime",
    "core_version",
    "derive_stage",
    "extract_documents",
    "handle_interview",
    "interview_client_config",
    "grader_catalogue",
    "package_specification",
    "render_review",
    "set_connection",
    "validate_binding",
    "write_experiment",
    "write_review",
    "working_status",
]
