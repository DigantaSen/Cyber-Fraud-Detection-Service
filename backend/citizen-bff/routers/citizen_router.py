"""
Citizen BFF Router — docs/api/citizen-bff.md
Pure proxy: forwards requests to downstream services.
No business logic. Normalizes response envelope.
"""
import uuid
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request

from clients.case_client import get_case_client
from clients.bot_client import get_bot_client
from clients.evidence_client import get_evidence_client
from response_helpers import error_response, success_response
from security.jwt import get_current_user, get_optional_user

router = APIRouter(prefix="/citizen", tags=["Citizen"])


def _corr(request: Request) -> str:
    return request.headers.get("X-Correlation-ID", str(uuid.uuid4()))


def _forward_headers(request: Request, current_user=None) -> dict:
    """Headers to forward to downstream services."""
    headers = {"X-Correlation-ID": _corr(request)}
    auth = request.headers.get("Authorization")
    if auth:
        headers["Authorization"] = auth
    if current_user:
        import json
        headers["X-User-Context"] = json.dumps({
            "userId": str(current_user.user_id) if current_user.user_id else None,
            "role": current_user.role,
            "jti": getattr(current_user, "jti", None)
        })
    return headers


async def _proxy(client: httpx.AsyncClient, method: str, path: str, **kwargs) -> dict:
    """
    Generic proxy helper. Raises HTTPException on downstream error.
    Handles: ConnectionError → 503, 4xx → re-raised, 5xx → 502.
    """
    try:
        response = await client.request(method, path, **kwargs)
        if response.status_code in (200, 201):
            return response.json()
        # Pass through 4xx errors from downstream
        if 400 <= response.status_code < 500:
            raise HTTPException(status_code=response.status_code, detail=response.json())
        raise HTTPException(status_code=502, detail={"errorCode": "UPSTREAM_ERROR", "message": "Upstream service error"})
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail={"errorCode": "SERVICE_UNAVAILABLE", "message": "Downstream service unavailable"})


# ── POST /citizen/report ──────────────────────────────────────────────────────

@router.post("/report", status_code=201)
async def submit_report(
    request: Request,
    body: dict,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user=Depends(get_optional_user),
    case_client: httpx.AsyncClient = Depends(get_case_client),
):
    """Submit fraud report. Proxies to Case Service POST /api/v1/cases."""
    headers = _forward_headers(request, current_user)
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    else:
        import uuid
        headers["Idempotency-Key"] = str(uuid.uuid4())

    result = await _proxy(case_client, "POST", "/api/v1/cases", json=body, headers=headers)
    
    # Map to BFF response format (docs/api/citizen-bff.md)
    if "data" in result:
        case_id = result["data"].get("caseId")
        return success_response({
            "caseId": case_id,
            "caseNumber": result["data"].get("caseNumber"),
            "message": "Your report has been registered. AI analysis is in progress.",
            "trackingUrl": f"/citizen/cases/{case_id}"
        }, _corr(request))
    return result


# ── GET /citizen/cases/:caseId ────────────────────────────────────────────────

@router.get("/cases/{case_id}")
async def get_case_status(
    request: Request,
    case_id: uuid.UUID,
    current_user=Depends(get_current_user),
    case_client: httpx.AsyncClient = Depends(get_case_client),
):
    """Get case status. Proxies to Case Service GET /api/v1/cases/:id."""
    result = await _proxy(case_client, "GET", f"/api/v1/cases/{case_id}", headers=_forward_headers(request, current_user))
    return result


# ── POST /citizen/bot/message ─────────────────────────────────────────────────

@router.post("/bot/message")
async def bot_message(
    request: Request,
    body: dict,
    current_user=Depends(get_current_user),
    bot_client: httpx.AsyncClient = Depends(get_bot_client),
):
    """Send bot message. Proxies to Bot Service POST /api/v1/bot/message."""
    result = await _proxy(bot_client, "POST", "/api/v1/bot/message", json=body, headers=_forward_headers(request, current_user))
    return result


# ── GET /citizen/bot/session/:sessionId ───────────────────────────────────────

@router.get("/bot/session/{session_id}")
async def get_bot_session(
    request: Request,
    session_id: uuid.UUID,
    current_user=Depends(get_current_user),
    bot_client: httpx.AsyncClient = Depends(get_bot_client),
):
    """Get bot session. Proxies to Bot Service GET /api/v1/bot/session/:id."""
    result = await _proxy(bot_client, "GET", f"/api/v1/bot/session/{session_id}", headers=_forward_headers(request, current_user))
    return result


# ── POST /citizen/cases/:caseId/evidence ──────────────────────────────────────

@router.post("/cases/{case_id}/evidence", status_code=201)
async def upload_evidence(
    request: Request,
    case_id: uuid.UUID,
    current_user=Depends(get_current_user),
    evidence_client: httpx.AsyncClient = Depends(get_evidence_client),
):
    """
    Upload evidence. Proxies to Evidence Service (Nilkanta's service).
    Degrades gracefully to 503 if Evidence Service is offline.
    """
    body = await request.body()
    content_type = request.headers.get("Content-Type", "application/json")
    result = await _proxy(
        evidence_client, "POST", f"/api/v1/evidence/{case_id}",
        content=body,
        headers={**_forward_headers(request, current_user), "Content-Type": content_type},
    )
    return result


# ── POST /citizen/evidence/:evidenceId/confirm ────────────────────────────────

@router.post("/evidence/{evidence_id}/confirm")
async def confirm_evidence(
    request: Request,
    evidence_id: uuid.UUID,
    current_user=Depends(get_current_user),
    evidence_client: httpx.AsyncClient = Depends(get_evidence_client),
):
    """Confirm evidence. Proxies to Evidence Service."""
    result = await _proxy(
        evidence_client, "POST", f"/api/v1/evidence/{evidence_id}/confirm",
        headers=_forward_headers(request, current_user),
    )
    return result
