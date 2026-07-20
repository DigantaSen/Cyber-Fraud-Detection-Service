from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
import httpx
from sse_starlette.sse import EventSourceResponse
import os
from datetime import datetime, timezone
from auth import get_current_user

router = APIRouter(prefix="/api/v1/bank")

NOTIFY_URL = os.environ.get("NOTIFY_URL", "http://notification:8000/api/v1/notify")

# ── In-process mock transaction store ────────────────────────────────────────
# Keyed by transactionId. In a real implementation this would be the
# downstream Event Processing / Case service.
_TRANSACTIONS: dict[str, dict] = {
    "TXN-987654321": {
        "transactionId": "TXN-987654321",
        "amount": 50000.0,
        "currency": "INR",
        "senderAccount": "1234567890",
        "receiverAccount": "0987654321",
        "senderName": "John Doe",
        "receiverName": "Scammer Inc",
        "riskScore": 95.5,
        "riskTier": "CRITICAL",
        "blockReasons": ["High Risk Pattern", "Known Scammer Account"],
        "status": "FLAGGED",
        "flaggedAt": "2026-07-20T10:00:00Z",
        "caseId": "CASE-12345",
    },
    "TXN-111222333": {
        "transactionId": "TXN-111222333",
        "amount": 18750.0,
        "currency": "INR",
        "senderAccount": "9988776655",
        "receiverAccount": "1122334455",
        "senderName": "Ramesh Kumar",
        "receiverName": "Unknown Shell Co.",
        "riskScore": 78.0,
        "riskTier": "HIGH",
        "blockReasons": ["Velocity spike", "New payee within 10 min"],
        "status": "FLAGGED",
        "flaggedAt": "2026-07-20T11:30:00Z",
        "caseId": None,
    },
    "TXN-444555666": {
        "transactionId": "TXN-444555666",
        "amount": 3200.0,
        "currency": "INR",
        "senderAccount": "5544332211",
        "receiverAccount": "6677889900",
        "senderName": "Priya Sharma",
        "receiverName": "Online Store XYZ",
        "riskScore": 42.0,
        "riskTier": "MEDIUM",
        "blockReasons": ["Unusual time of day"],
        "status": "UNDER_REVIEW",
        "flaggedAt": "2026-07-20T13:00:00Z",
        "caseId": None,
    },
}

_RISK_TIER_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


# ── GET /transactions/flagged ─────────────────────────────────────────────────

@router.get("/transactions/flagged")
async def get_flagged_transactions(
    request: Request,
    cursor: str = None,
    limit: int = 20,
    riskTier: str = None,
    status: str = None,
    from_date: str = None,
    to_date: str = None,
    user=Depends(get_current_user("BANK_OFFICIAL")),
):
    items = list(_TRANSACTIONS.values())

    # Apply filters
    if riskTier:
        items = [t for t in items if t["riskTier"] == riskTier]
    if status:
        items = [t for t in items if t["status"] == status]

    # Sort by risk tier descending, then by flaggedAt
    items.sort(key=lambda t: (_RISK_TIER_ORDER.get(t["riskTier"], 99), t["flaggedAt"]))

    # Paginate
    items = items[:limit]

    return {
        "data": {
            "items": items,
            "nextCursor": None,
            "hasMore": False,
            "total": len(items),
        }
    }


# ── POST /transactions/{transaction_id}/block ─────────────────────────────────

class BlockRequest(BaseModel):
    reason: str = Field(..., min_length=10, description="Reason for blocking (min 10 chars)")


@router.post("/transactions/{transaction_id}/block", status_code=200)
async def block_transaction(
    transaction_id: str,
    body: BlockRequest,
    request: Request,
    user=Depends(get_current_user("BANK_OFFICIAL")),
):
    tx = _TRANSACTIONS.get(transaction_id)
    if tx is None:
        raise HTTPException(status_code=404, detail=f"Transaction '{transaction_id}' not found")

    if tx["status"] == "BLOCKED":
        raise HTTPException(status_code=409, detail="Transaction is already blocked")

    # Update in-process state
    tx["status"] = "BLOCKED"
    tx["blockReasons"] = list(set(tx.get("blockReasons", [])) | {body.reason})
    tx["blockedAt"] = datetime.now(timezone.utc).isoformat()
    tx["blockedBy"] = user.get("email", "unknown")

    return {
        "data": {
            "transactionId": transaction_id,
            "status": "BLOCKED",
            "blockedAt": tx["blockedAt"],
            "blockedBy": tx["blockedBy"],
            "reason": body.reason,
            "message": f"Transaction {transaction_id} has been successfully blocked.",
        }
    }


# ── GET /stream ───────────────────────────────────────────────────────────────

@router.get("/stream")
async def stream_bank_events(request: Request, user=Depends(get_current_user("BANK_OFFICIAL"))):
    """Proxy real-time bank fraud alerts from the Notification service via SSE."""
    async def sse_generator():
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                headers = {"X-User-Role": "BANK_OFFICIAL"}
                if "jurisdictionId" in user:
                    headers["X-Jurisdiction-Id"] = user["jurisdictionId"]

                async with client.stream("GET", f"{NOTIFY_URL}/stream", headers=headers) as response:
                    async for line in response.aiter_lines():
                        if line:
                            yield line
        except httpx.RequestError:
            yield "event: error\ndata: downstream notification service unavailable\n\n"

    return EventSourceResponse(sse_generator())
