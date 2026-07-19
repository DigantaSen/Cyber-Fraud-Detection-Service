"""
SQLAlchemy ORM model for investigation.cases.
Maps exactly to the DDL in docs/db/postgres.sql.
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    UUID, CheckConstraint, DateTime, ForeignKey,
    Numeric, String, Text, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (
        CheckConstraint(
            "complaint_type IN ('UPI_FRAUD','CALL_FRAUD','COUNTERFEIT_CURRENCY','CYBER_CRIME','OTHER')",
            name="cases_complaint_type_check",
        ),
        CheckConstraint(
            "status IN ('New','Assigned','Investigating','Pending_AI','Action_Taken','Closed')",
            name="cases_status_check",
        ),
        CheckConstraint(
            "priority IN ('LOW','NORMAL','HIGH','CRITICAL')",
            name="cases_priority_check",
        ),
        CheckConstraint(
            "suspect_phone IS NULL OR suspect_phone ~ '^\\+[1-9][0-9]{7,14}$'",
            name="cases_suspect_phone_check",
        ),
        CheckConstraint(
            "reporter_phone IS NULL OR reporter_phone ~ '^\\+[1-9][0-9]{7,14}$'",
            name="cases_reporter_phone_check",
        ),
        CheckConstraint(
            "complaint_lat IS NULL OR complaint_lat BETWEEN -90 AND 90",
            name="cases_lat_check",
        ),
        CheckConstraint(
            "complaint_lon IS NULL OR complaint_lon BETWEEN -180 AND 180",
            name="cases_lon_check",
        ),
        {"schema": "investigation"},
    )

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    complaint_type: Mapped[str] = mapped_column(String(32), nullable=False)
    suspect_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    suspect_account: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    complaint_lat: Mapped[Optional[Decimal]] = mapped_column(Numeric(9, 6), nullable=True)
    complaint_lon: Mapped[Optional[Decimal]] = mapped_column(Numeric(9, 6), nullable=True)
    reporter_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    reporter_entity_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    reporter_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    language_code: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    jurisdiction_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="New")
    assigned_investigator: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="NORMAL")
    disposition: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
