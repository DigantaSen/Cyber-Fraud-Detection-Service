"""
SQLAlchemy ORM model for investigation.case_timeline.
Maps exactly to the DDL in docs/db/postgres.sql.
"""
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import UUID, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CaseTimeline(Base):
    __tablename__ = "case_timeline"
    __table_args__ = {"schema": "investigation"}

    timeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_role: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # 'metadata' is reserved by SQLAlchemy DeclarativeBase — use explicit column name
    event_metadata: Mapped[Any] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    correlation_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
