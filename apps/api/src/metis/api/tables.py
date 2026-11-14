"""The tables of the store. They use only portable SQL types, so any SQLAlchemy database works."""

from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, ForeignKey, MetaData, String, Table, Text

metadata = MetaData()

targets = Table(
    "targets",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("name", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

interviews = Table(
    "interviews",
    metadata,
    Column("target_id", String(64), ForeignKey("targets.id"), primary_key=True),
    Column("record", JSON, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

specifications = Table(
    "specifications",
    metadata,
    Column("target_id", String(64), ForeignKey("targets.id"), primary_key=True),
    Column("specification_yaml", Text, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

experiments = Table(
    "experiments",
    metadata,
    Column("experiment_id", String(200), primary_key=True),
    Column("target_id", String(64), ForeignKey("targets.id"), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("step", String(16), nullable=False),
)


__all__ = ["interviews", "experiments", "metadata", "specifications", "targets"]
