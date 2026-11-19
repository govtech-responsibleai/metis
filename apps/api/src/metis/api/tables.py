"""The tables of the store. They use only portable SQL types, so any SQLAlchemy database works."""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    MetaData,
    String,
    Table,
    Text,
)

metadata = MetaData()

targets = Table(
    "targets",
    metadata,
    # The name of the Interview folder and the Specification folder of the Target. The client
    # makes it.
    Column("id", String(64), primary_key=True),
    # The one column that names the user account. Each other record belongs to a user account
    # through its Target.
    Column("user_id", String(32), ForeignKey("users.id"), nullable=False),
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
    # Two user accounts can have an Experiment folder with the same name, so the folder name
    # is a key only together with the Target.
    Column("target_id", String(64), ForeignKey("targets.id"), primary_key=True),
    Column("experiment_id", String(200), primary_key=True),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("step", String(16), nullable=False),
)

users = Table(
    "users",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("username", String(64), nullable=False, unique=True),
    # A user account of a later login method has no password, so this column can be empty.
    Column("password_hash", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

# A user account with a row here is an admin. The flag is a table of its own, because
# `create_all` makes a missing table in an existing database but never adds a column.
admins = Table(
    "admins",
    metadata,
    Column("user_id", String(32), ForeignKey("users.id"), primary_key=True),
)

login_sessions = Table(
    "login_sessions",
    metadata,
    # The SHA-256 of the cookie value. The store never keeps the cookie value.
    Column("token_hash", String(64), primary_key=True),
    Column("user_id", String(32), ForeignKey("users.id"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
)


__all__ = [
    "admins",
    "experiments",
    "interviews",
    "login_sessions",
    "metadata",
    "specifications",
    "targets",
    "users",
]
