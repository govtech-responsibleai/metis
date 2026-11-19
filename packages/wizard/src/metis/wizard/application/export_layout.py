"""Paths shared by directory and ZIP exports, relative to an ``evaluations/`` folder.

An export has two folders with the same ``<id>``: ``interviews/<id>/`` holds the Interview, and
``specifications/<id>/`` holds the Specification that it makes. A manual-form export has only the
Specification folder. The names inside each folder are relative to that folder.
"""

import secrets
from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal

INTERVIEWS = PurePosixPath("interviews")
SPECIFICATIONS = PurePosixPath("specifications")

INTERVIEW_STATE = PurePosixPath("interview_state.json")
"""In ``interviews/<id>/``."""
DOCUMENTS = PurePosixPath("documents")
"""In ``interviews/<id>/``: the opening documents and the files of the Interview."""

SPECIFICATION = PurePosixPath("specification.yaml")
"""In ``specifications/<id>/``, as are the three names below."""
TARGET_BINDING = PurePosixPath("target-binding.yaml")
FIXTURES = PurePosixPath("fixtures")
REVIEW = PurePosixPath("review.md")


def interview_dir(export_id: str) -> PurePosixPath:
    """The Interview folder of ``export_id``, relative to the ``evaluations/`` folder."""
    return INTERVIEWS / export_id


def specification_dir(export_id: str) -> PurePosixPath:
    """The Specification folder of ``export_id``, relative to the ``evaluations/`` folder."""
    return SPECIFICATIONS / export_id


def new_id(source: Literal["interview", "manual"]) -> str:
    """Make a new ``<id>``: ``YYYYMMDD-HHMMSS-<source>-<random>``, at the local time now.

    The random part gives two exports that start in the same second different ids.
    """
    return f"{datetime.now():%Y%m%d-%H%M%S}-{source}-{random_part()}"


_RANDOM_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
"""Lower-case letters and digits, without `i`, `l`, `o`, `0`, and `1`, which look alike."""
_RANDOM_LENGTH = 5


def random_part() -> str:
    """Five random characters for the end of an ``<id>``.

    With it, two Interviews that start in the same second get different ids.
    """
    return "".join(secrets.choice(_RANDOM_ALPHABET) for _ in range(_RANDOM_LENGTH))
