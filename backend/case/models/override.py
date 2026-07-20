"""
SQLAlchemy ORM model for inference.override_records.
Maps exactly to the DDL in docs/db/postgres.sql.

# APPEND-ONLY: never UPDATE or DELETE — DB trigger override_records_append_only enforces this.
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import UUID, CheckConstraint, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class OverrideRecord(Base):
    __tablename__ = "override_records"
    __table_args__ = (
        CheckConstraint("decision IN ('APPROVE','REJECT')", name="override_decision_check"),
        CheckConstraint("LENGTH(justification) >= 20", name="override_justification_check"),
        {"schema": "inference"},
    )

    override_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    original_verdict_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    investigator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    original_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    original_confidence: Mapped[Optional[Decimal]] = mapped_column(Numeric(4, 3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    correlation_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
