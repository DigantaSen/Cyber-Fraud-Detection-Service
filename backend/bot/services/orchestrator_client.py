"""
Orchestrator HTTP client — calls POST /inference/analyze.
STUB until T13 (Day 6): returns hardcoded risk assessment.
Replace stub with real httpx call when Orchestrator is live.
"""
import httpx
from typing import Optional


# ── STUB RESPONSE (replaced in T13) ──────────────────────────────────────────
_STUB_RESPONSE = {
    "preliminary_score": 65,
    "risk_tier": "MEDIUM",
    "requires_format_report": True,
}


async def get_risk_assessment(
    http_client: httpx.AsyncClient,
    session_id: str,
    message: str,
    lang_code: str,
    correlation_id: str,
) -> Optional[dict]:
    """
    Call Inference Orchestrator for preliminary risk assessment.
    Returns None before ≥2 turns (not enough context).
    
    [STUB] Returns hardcoded medium risk until T13 integration.
    T13 replacement: uncomment the httpx call below.
    """
    # TODO T13: Replace stub with real call
    # try:
    #     response = await http_client.post(
    #         "/api/v1/inference/analyze",
    #         json={"text": message, "sessionId": session_id, "languageCode": lang_code},
    #         headers={"X-Correlation-ID": correlation_id},
    #         timeout=5.0,
    #     )
    #     response.raise_for_status()
    #     data = response.json()
    #     return {
    #         "preliminary_score": data.get("fusedScore", 0),
    #         "risk_tier": data.get("riskTier", "LOW"),
    #         "requires_format_report": data.get("riskTier") in ("HIGH", "CRITICAL"),
    #     }
    # except (httpx.RequestError, httpx.HTTPStatusError):
    #     return None

    return _STUB_RESPONSE   # [STUB — T13]
