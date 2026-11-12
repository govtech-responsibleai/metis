"""The portable SQL table for complete Interview records."""

from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, MetaData, String, Table

metadata = MetaData()

interviews = Table(
    "interviews",
    metadata,
    Column("target_id", String(64), primary_key=True),
    Column("record", JSON, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

__all__ = ["interviews", "metadata"]
