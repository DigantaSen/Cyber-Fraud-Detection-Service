"""
SQLAlchemy ORM model for inference.fused_verdicts.
Maps exactly to the DDL in docs/db/postgres.sql.

# APPEND-ONLY: never UPDATE or DELETE — DB trigger fused_verdicts_append_only enforces this.
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import UUID, Boolean, CheckConstraint, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class FusedVerdict(Base):
    __tablename__ = "fused_verdicts"
    __table_args__ = (
        CheckConstraint("fused_score BETWEEN 0 AND 100", name="fused_verdicts_score_check"),
        CheckConstraint("risk_tier IN ('LOW','MEDIUM','HIGH','CRITICAL')", name="fused_verdicts_risk_tier_check"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="fused_verdicts_confidence_check"),
        CheckConstraint("status IN ('COMPLETE','INCOMPLETE','PENDING_REVIEW')", name="fused_verdicts_status_check"),
        {"schema": "inference"},
    )

    # PK is also a FK to inference.predictions — same UUID
    prediction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    fused_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    risk_tier: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    model_breakdown: Mapped[Any] = mapped_column(JSONB, nullable=False, default=list)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    fusion_weights: Mapped[Any] = mapped_column(JSONB, nullable=False)
    pending_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pending_notification: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fusion_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    correlation_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
