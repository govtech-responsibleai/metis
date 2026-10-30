"""Factories for the required client-held Interview context in tests."""

from collections.abc import Iterable

from metis.wizard.contracts import (
    CapabilityConfidence,
    CapabilityEvidence,
    CapabilityId,
    InterviewContext,
    Perspective,
)


def interview_context(
    perspective: Perspective = Perspective.END_USER,
    known_capability_ids: Iterable[CapabilityId] = (),
    confidence: CapabilityConfidence = CapabilityConfidence.LOW,
) -> InterviewContext:
    """Build explicit opening evidence for a client-held state fixture."""
    return InterviewContext(
        perspective=perspective,
        capability_evidence=CapabilityEvidence(
            known_capability_ids=list(known_capability_ids),
            confidence=confidence,
        ),
    )
