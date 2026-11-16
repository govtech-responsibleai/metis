"""Paths shared by directory and ZIP exports, relative to the experiment root."""

import secrets
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


_RANDOM_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
"""Lower-case letters and digits, without `i`, `l`, `o`, `0`, and `1`, which look alike."""
_RANDOM_LENGTH = 5


def random_part() -> str:
    """Five random characters for the end of a Target folder name.

    With it, two Interviews that start in the same second get different folder names.
    """
    return "".join(secrets.choice(_RANDOM_ALPHABET) for _ in range(_RANDOM_LENGTH))
