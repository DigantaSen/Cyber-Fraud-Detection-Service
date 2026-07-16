"""
Pydantic schemas for Case Service API.
Field names match docs/api/case.md (camelCase) exactly via alias_generator.
"""
import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

# ── Shared config ─────────────────────────────────────────────────────────────

_VALID_COMPLAINT_TYPES = {"UPI_FRAUD", "CALL_FRAUD", "COUNTERFEIT_CURRENCY", "CYBER_CRIME", "OTHER"}
_VALID_STATUSES = {"New", "Assigned", "Investigating", "Pending_AI", "Action_Taken", "Closed"}
_VALID_DECISIONS = {"APPROVE", "REJECT"}
_VALID_LANGUAGE_CODES = {"hi", "bn", "te", "ta", "mr", "gu", "kn", "ml", "pa", "ur", "or", "as", "en", "other"}
_E164_RE = re.compile(r"^\+[1-9][0-9]{7,14}$")


class CurrentUser(BaseModel):
    user_id: uuid.UUID
    email: str
    role: str
    org_id: Optional[uuid.UUID] = None
    jurisdiction_id: Optional[str] = None
    jti: str



class CamelModel(BaseModel):
    """Base model that accepts and produces camelCase field names."""
    model_config = {
        "alias_generator": to_camel,
        "populate_by_name": True,       # also accept snake_case in code
        "protected_namespaces": (),     # allow 'model_breakdown' field names
    }


# ── Request Schemas ───────────────────────────────────────────────────────────

class CreateCaseRequest(CamelModel):
    title: str = Field(..., max_length=200)
    description: str
    complaint_type: str
    suspect_phone: Optional[str] = None
    suspect_account: Optional[str] = None
    complaint_lat: Optional[float] = None
    complaint_lon: Optional[float] = None
    reporter_entity_name: Optional[str] = None
    reporter_phone: Optional[str] = None
    language_code: str = Field("en")

    @field_validator("complaint_type")
    @classmethod
    def validate_complaint_type(cls, v: str) -> str:
        if v not in _VALID_COMPLAINT_TYPES:
            raise ValueError(f"complaintType must be one of {sorted(_VALID_COMPLAINT_TYPES)}")
        return v

    @field_validator("suspect_phone", "reporter_phone", mode="before")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        if not _E164_RE.match(v):
            raise ValueError("Phone must be in E.164 format (e.g. +919876543210)")
        return v

    @field_validator("language_code")
    @classmethod
    def validate_language_code(cls, v: str) -> str:
        if v not in _VALID_LANGUAGE_CODES:
            raise ValueError(f"languageCode must be a supported BCP-47 code: {sorted(_VALID_LANGUAGE_CODES)}")
        return v

    @model_validator(mode="after")
    def validate_coordinates(self) -> "CreateCaseRequest":
        if self.complaint_lat is not None and not (-90 <= self.complaint_lat <= 90):
            raise ValueError("complaintLat must be between -90 and 90")
        if self.complaint_lon is not None and not (-180 <= self.complaint_lon <= 180):
            raise ValueError("complaintLon must be between -180 and 180")
        return self


class UpdateCaseStateRequest(CamelModel):
    state: str
    reason: str
    assigned_to: Optional[uuid.UUID] = None

    @field_validator("state")
    @classmethod
    def validate_state(cls, v: str) -> str:
        if v not in _VALID_STATUSES:
            raise ValueError(f"state must be one of {sorted(_VALID_STATUSES)}")
        return v


class VerdictOverrideRequest(CamelModel):
    decision: str
    justification: str = Field(..., min_length=20)   # NFR-8.4 legal requirement
    original_verdict_id: uuid.UUID

    @field_validator("decision")
    @classmethod
    def validate_decision(cls, v: str) -> str:
        if v not in _VALID_DECISIONS:
            raise ValueError(f"decision must be one of {sorted(_VALID_DECISIONS)}")
        return v


# ── Response Schemas ──────────────────────────────────────────────────────────

class PredictionSummary(CamelModel):
    prediction_id: uuid.UUID
    fused_score: Decimal
    risk_tier: str
    confidence: Decimal
    status: str
    model_breakdown: List[Any] = []
    explanation: str
    created_at: datetime


class CreateCaseResponse(CamelModel):
    case_id: uuid.UUID
    case_number: str
    status: str
    created_at: datetime
    assigned_to: Optional[uuid.UUID] = None
    prediction_status: str = "PENDING"


class CaseSummaryResponse(CamelModel):
    case_id: uuid.UUID
    case_number: str
    title: str
    complaint_type: str
    status: str
    priority: str
    jurisdiction_id: str
    assigned_to: Optional[uuid.UUID] = None
    risk_tier: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class CaseDetailResponse(CamelModel):
    case_id: uuid.UUID
    case_number: str
    status: str
    title: str
    description: str
    complaint_type: str
    suspect_phone: Optional[str] = None
    complaint_lat: Optional[Decimal] = None
    complaint_lon: Optional[Decimal] = None
    reporter_entity_name: Optional[str] = None
    reporter_phone: Optional[str] = None
    language_code: str
    assigned_to: Optional[uuid.UUID] = None
    jurisdiction_id: str
    priority: str
    prediction: Optional[PredictionSummary] = None
    evidence_count: int = 0
    created_at: datetime
    updated_at: datetime


class PaginatedCasesResponse(CamelModel):
    items: List[CaseSummaryResponse]
    next_cursor: Optional[str] = None
    has_more: bool
    total: int


class TimelineEventResponse(CamelModel):
    timeline_id: uuid.UUID
    event_type: str
    actor: Optional[str] = None
    actor_role: Optional[str] = None
    description: str
    metadata: Any = {}
    timestamp: datetime   # maps to created_at


class PaginatedTimelineResponse(CamelModel):
    items: List[TimelineEventResponse]
    next_cursor: Optional[str] = None
    has_more: bool
    total: int


class VerdictOverrideResponse(CamelModel):
    override_id: uuid.UUID
    decision: str
    case_id: uuid.UUID
    investigator_id: uuid.UUID
    original_verdict_id: uuid.UUID
    timestamp: datetime
