"""
Bot Service Router — docs/api/bot.md
Routes:
  POST /bot/message              — multi-turn conversation
  GET  /bot/session/:sessionId   — get session state
  POST /bot/whatsapp             — WhatsApp webhook [STUB]
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from http_client import get_http_client
from models.schemas import BotMessageRequest, BotMessageResponse, RiskAssessmentPayload
from redis_client import get_redis
from response_helpers import error_response, success_response
from services.language_service import detect_language
from services.orchestrator_client import get_risk_assessment
from services.session_service import SessionService, SessionNotFoundError

router = APIRouter(prefix="/bot", tags=["Bot"])


def _corr(request: Request) -> str:
    return request.headers.get("X-Correlation-ID", str(uuid.uuid4()))


# ── Intent classification (simple rule-based for hackathon) ───────────────────

_INTENT_MAP = {
    "fraud": "FRAUD_REPORT_INITIATION",
    "scam": "FRAUD_REPORT_INITIATION",
    "upi": "FRAUD_REPORT_INITIATION",
    "report": "REPORT_STATUS_INQUIRY",
    "status": "REPORT_STATUS_INQUIRY",
    "help": "GENERAL_INQUIRY",
}

def _classify_intent(message: str) -> str:
    """Simple keyword-based intent classification."""
    lower = message.lower()
    for keyword, intent in _INTENT_MAP.items():
        if keyword in lower:
            return intent
    return "GENERAL_INQUIRY"

def _get_suggested_actions(intent: str, turn_count: int) -> list[str]:
    if intent == "FRAUD_REPORT_INITIATION":
        if turn_count <= 2:
            return ["PROVIDE_SUSPECT_PHONE", "DESCRIBE_INCIDENT"]
        return ["SUBMIT_FORMAL_REPORT", "PROVIDE_SCREENSHOT"]
    return ["CONTACT_SUPPORT"]

def _generate_bot_response(intent: str, lang_code: str, turn_count: int) -> str:
    """
    Generate a language-appropriate bot response.
    Hackathon: hardcoded templates. Production: NLP model via Orchestrator.
    """
    responses = {
        "FRAUD_REPORT_INITIATION": {
            "en": "Thank you for reporting. Please provide the suspect's phone number and describe the incident.",
            "hi": "आपकी रिपोर्ट के लिए धन्यवाद। कृपया संदिग्ध का फ़ोन नंबर और घटना का विवरण प्रदान करें।",
        },
        "REPORT_STATUS_INQUIRY": {
            "en": "Please provide your case ID to check the status.",
            "hi": "स्थिति जांचने के लिए कृपया अपना केस आईडी प्रदान करें।",
        },
        "GENERAL_INQUIRY": {
            "en": "I can help you report cyber fraud. What happened?",
            "hi": "मैं साइबर धोखाधड़ी की रिपोर्ट करने में आपकी सहायता कर सकता हूं। क्या हुआ?",
        },
    }
    intent_responses = responses.get(intent, responses["GENERAL_INQUIRY"])
    return intent_responses.get(lang_code, intent_responses.get("en", "I understand. Please continue."))


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/message", status_code=200)
async def send_message(
    request: Request,
    body: BotMessageRequest,
    redis=Depends(get_redis),
    http_client=Depends(get_http_client),
):
    """Process a citizen message. Creates or continues a bot session."""
    correlation_id = _corr(request)
    session_svc = SessionService(redis)

    # Detect language
    lang_code = detect_language(body.message)

    # Determine intent
    intent = _classify_intent(body.message)

    # Load or create session
    if body.session_id:
        session = await session_svc.get_session(str(body.session_id))
        if not session:
            raise HTTPException(
                status_code=404,
                detail=error_response("SESSION_NOT_FOUND", "Session expired or not found", correlation_id),
            )
        is_new_session = False
    else:
        session = await session_svc.create_session(
            lang_code=lang_code,
            channel=body.channel,
            user_id=str(body.user_id) if body.user_id else None,
            first_message=body.message,
        )
        is_new_session = True

    # Generate bot response
    bot_response_text = _generate_bot_response(intent, lang_code, session.get("turnCount", 1))

    # Update session (add bot response, refresh TTL)
    if not is_new_session:
        session = await session_svc.update_session(
            session_id=str(body.session_id),
            lang_code=lang_code,
            user_message=body.message,
            bot_response=bot_response_text,
        )

    turn_count = session["turnCount"]

    # Call Orchestrator for risk assessment (after ≥2 turns)
    risk_assessment = None
    if turn_count >= 2:
        raw_assessment = await get_risk_assessment(
            http_client=http_client,
            session_id=session["sessionId"],
            message=body.message,
            lang_code=lang_code,
            correlation_id=correlation_id,
        )
        if raw_assessment:
            risk_assessment = RiskAssessmentPayload(
                preliminary_score=raw_assessment["preliminary_score"],
                risk_tier=raw_assessment["risk_tier"],
                requires_format_report=raw_assessment["requires_format_report"],
            )

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=1800)

    result = BotMessageResponse(
        session_id=uuid.UUID(session["sessionId"]),
        response=bot_response_text,
        detected_language=lang_code,
        intent=intent,
        risk_assessment=risk_assessment,
        suggested_actions=_get_suggested_actions(intent, turn_count),
        turn_count=turn_count,
        session_expires_at=expires_at,
    )
    return success_response(result.model_dump(by_alias=True, mode="json"), correlation_id)


@router.get("/session/{session_id}", status_code=200)
async def get_session(
    request: Request,
    session_id: uuid.UUID,
    redis=Depends(get_redis),
):
    """Get current bot session state."""
    correlation_id = _corr(request)
    session_svc = SessionService(redis)
    session = await session_svc.get_session(str(session_id))
    if not session:
        raise HTTPException(
            status_code=404,
            detail=error_response("SESSION_NOT_FOUND", "Session not found or expired", correlation_id),
        )
    return success_response(
        {
            "sessionId": session["sessionId"],
            "turnCount": session["turnCount"],
            "detectedLanguage": session["detectedLanguage"],
            "collectedData": session.get("collectedData", {}),
            "status": session.get("status", "ACTIVE"),
            "expiresAt": session.get("expiresAt", ""),
        },
        correlation_id,
    )


@router.post("/whatsapp", status_code=200)
async def whatsapp_webhook(request: Request, body: dict):
    """WhatsApp webhook [STUB] — acknowledges receipt per docs/api/bot.md."""
    return success_response(
        {"acknowledged": True, "message": "Report received. A case officer will contact you shortly."},
        _corr(request),
    )
