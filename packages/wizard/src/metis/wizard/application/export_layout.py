"""Paths shared by directory and ZIP exports, relative to the experiment root."""

from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal

INPUTS = PurePosixPath("inputs")
OUTPUTS = PurePosixPath("outputs")
INTERVIEW_STATE = INPUTS / "interview_state.json"
DOCUMENTS = INPUTS / "documents"
SPECIFICATION = OUTPUTS / "specification.yaml"
TARGET_BINDING = OUTPUTS / "target-binding.yaml"
FIXTURES = OUTPUTS / "fixtures"
REVIEW = OUTPUTS / "review.md"


def experiment_name(source: Literal["interview", "manual"]) -> str:
    """Name an export using the local date and time at the start of the operation."""
    return f"{datetime.now():%Y%m%d-%H%M%S}-{source}"
