from fastapi import APIRouter, Depends, Request
import httpx
from sse_starlette.sse import EventSourceResponse
import os
from auth import get_current_user

router = APIRouter(prefix="/api/v1/telecom")

NOTIFY_URL = os.environ.get("NOTIFY_URL", "http://notification:8000/api/v1/notify")

@router.get("/sessions/active")
async def get_active_sessions(
    request: Request,
    cursor: str = None,
    limit: int = 20,
    user=Depends(get_current_user("TELECOM_ADMIN"))
):
    # Mock session so the telecom UI can display something
    return {
        "data": {
            "items": [
                {
                    "sessionId": "SESS-112233",
                    "callerNumber": "+919876543210",
                    "calleeNumber": "+911234567890",
                    "duration": 45,
                    "riskScore": 92.0,
                    "riskTier": "HIGH",
                    "flaggedAt": "2026-07-20T10:00:00Z",
                    "status": "ACTIVE",
                    "flagReasons": ["Suspicious international routing", "Matches known scam template"]
                }
            ],
            "nextCursor": None,
            "hasMore": False,
            "total": 1
        }
    }

@router.get("/stream")
async def stream_telecom_events(request: Request, user=Depends(get_current_user("TELECOM_ADMIN"))):
    # Proxy to Notification Service SSE
    async def sse_generator():
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                headers = {"X-User-Role": "TELECOM_ADMIN"}
                if "jurisdictionId" in user:
                    headers["X-Jurisdiction-Id"] = user["jurisdictionId"]
                
                async with client.stream("GET", f"{NOTIFY_URL}/stream", headers=headers) as response:
                    async for line in response.aiter_lines():
                        if line:
                            yield line
        except httpx.RequestError:
            # Defensive fallback
            yield "event: error\ndata: downstream notification service unavailable\n\n"

    return EventSourceResponse(sse_generator())
