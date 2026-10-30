"""Domain models for the METIS evaluation suite."""

from pydantic import BaseModel


class Status(BaseModel):
    """Demo model — proves Pydantic + namespace imports work. Replace with real domain models."""

    message: str
