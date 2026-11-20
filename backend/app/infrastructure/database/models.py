"""
SQLAlchemy 2 Async Models for Cloud-Native AI Coding Harness.
Adheres strictly to Spec §3.2, §3.3, §3.5, §7.
Tables: runs, events, artifacts.
Cross-dialect compatibility with PostgreSQL and SQLite.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    """Base declarative class for harness models."""


# Dialect-agnostic JSON type that uses JSONB on Postgres and JSON on SQLite
JSONType = JSON().with_variant(JSONB(), "postgresql")


class RunModel(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    repo_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    task: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="QUEUED", index=True)
    options: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    is_pausing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    baseline_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    events: Mapped[list[EventModel]] = relationship(
        "EventModel",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="EventModel.seq",
    )
    artifacts: Mapped[list[ArtifactModel]] = relationship(
        "ArtifactModel",
        back_populates="run",
        cascade="all, delete-orphan",
    )


class EventModel(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)

    run: Mapped[RunModel] = relationship("RunModel", back_populates="events")

    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="uq_events_run_id_seq"),
        Index("ix_events_run_id_seq", "run_id", "seq"),
    )


class ArtifactModel(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)  # patch, logs, transcript, baseline
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False, default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        nullable=False,
        default=0,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    run: Mapped[RunModel] = relationship("RunModel", back_populates="artifacts")

    __table_args__ = (
        UniqueConstraint("run_id", "artifact_type", name="uq_artifacts_run_id_type"),
    )

