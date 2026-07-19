"""Pydantic schemas for Bot Service — docs/api/bot.md."""
import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)


class BotMessageRequest(CamelModel):
    """
    Request body for POST /bot/message.

    To **start a new conversation** omit ``sessionId`` or send it as ``null``.
    To **continue an existing conversation** supply the ``sessionId`` returned
    by the previous response.
    """

    session_id: Optional[uuid.UUID] = Field(
        default=None,
        description=(
            "Session identifier. "
            "Omit or set to null when starting a new conversation. "
            "Supply an existing sessionId only when continuing a previous chat."
        ),
        examples=[None, "3fa85f64-5717-4562-b3fc-2c963f66afa6"],
    )
    message: str = Field(
        ...,
        max_length=2000,
        description="The citizen's message text (max 2000 characters).",
    )
    channel: str = Field(
        default="WEB",
        description="Originating channel. One of: WEB, WHATSAPP, IVR.",
    )
    user_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Optional authenticated citizen identifier.",
    )

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
    )

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
    """
    Response body for POST /bot/message.

    ``sessionId`` is returned on every response — both for new and existing
    sessions. Clients **must** pass this value back as ``sessionId`` in
    subsequent requests to continue the same conversation.
    """

    session_id: uuid.UUID = Field(
        description=(
            "Session identifier. Store this value and pass it as "
            "``sessionId`` in future requests to continue the conversation."
        )
    )
    response: str = Field(description="Bot's reply text.")
    detected_language: str = Field(description="ISO 639-1 language code detected from the message.")
    intent: str = Field(description="Classified intent of the citizen's message.")
    risk_assessment: Optional[RiskAssessmentPayload] = Field(
        default=None,
        description="Preliminary risk assessment (available after ≥2 turns).",
    )
    suggested_actions: list[str] = Field(
        default=[],
        description="Recommended next actions for the citizen or case officer.",
    )
    turn_count: int = Field(description="Total number of turns in the current session.")
    session_expires_at: datetime = Field(description="UTC timestamp when the session will expire (30-minute TTL).")


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
