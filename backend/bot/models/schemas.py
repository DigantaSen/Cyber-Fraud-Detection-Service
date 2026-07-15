"""Pydantic schemas for Bot Service — docs/api/bot.md."""
import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)


class BotMessageRequest(CamelModel):
    session_id: Optional[uuid.UUID] = None   # Omit for new session
    message: str = Field(..., max_length=2000)
    channel: str = "WEB"
    user_id: Optional[uuid.UUID] = None

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v: str) -> str:
        if v not in {"WEB", "WHATSAPP", "IVR"}:
            raise ValueError("channel must be WEB, WHATSAPP, or IVR")
        return v


class RiskAssessmentPayload(CamelModel):
    preliminary_score: int
    risk_tier: str
    requires_format_report: bool


class BotMessageResponse(CamelModel):
    session_id: uuid.UUID
    response: str
    detected_language: str
    intent: str
    risk_assessment: Optional[RiskAssessmentPayload] = None
    suggested_actions: list[str] = []
    turn_count: int
    session_expires_at: datetime


class BotSessionState(CamelModel):
    """Stored in Redis as JSON."""
    session_id: str
    turn_count: int
    detected_language: str
    messages: list[dict]           # [{role: user|bot, content: str, ts: str}]
    collected_data: dict           # Accumulated fraud data from conversation
    status: str = "ACTIVE"
    channel: str = "WEB"
    user_id: Optional[str] = None
    expires_at: str


class BotSessionResponse(CamelModel):
    session_id: uuid.UUID
    turn_count: int
    detected_language: str
    collected_data: dict
    status: str
    expires_at: str
