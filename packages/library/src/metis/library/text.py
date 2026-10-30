"""Text field types shared by grader args and the shared definitions."""

from typing import Annotated

from pydantic import StringConstraints

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
"""A string that is not empty after its surrounding whitespace is stripped."""
