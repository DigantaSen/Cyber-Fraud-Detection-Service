"""
MHA Webhook Mock Server
=======================
Simulates the Government/MHA portal webhook that receives HIGH-priority fraud alerts
from the Notification Service.

Endpoints:
  POST /alert          — Accept an MHA alert payload, log it, return 200 ACK
  GET  /alerts         — Return all received alerts (for test verification)
  GET  /alerts/count   — Return alert count (SLO health check)
  DELETE /alerts       — Clear alert store (test teardown)
  GET  /health/live    — Liveness probe
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [mha-mock] %(message)s",
)
logger = logging.getLogger("mha-mock")

app = FastAPI(
    title="MHA Webhook Mock",
    description="Simulated Government/MHA Portal webhook for fraud alert acceptance.",
    version="1.0.0",
)

# In-memory alert store (sufficient for hackathon demo)
_alert_store: List[Dict[str, Any]] = []


class MHAAlertPayload(BaseModel):
    caseId: str
    alertType: str
    riskTier: str
    summary: str
    suspects: List[str] = []
    jurisdictionId: str
    triggeredBy: str


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.post("/alert", status_code=200)
async def receive_alert(request: Request, payload: MHAAlertPayload):
    """
    Accept an MHA alert from the Notification Service.
    Mimics the real MHA government portal webhook endpoint.
    """
    received_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    correlation_id = request.headers.get("X-Correlation-ID", "")

    record = {
        "mockAlertId": str(uuid.uuid4()),
        "receivedAt": received_at,
        "correlationId": correlation_id,
        **payload.model_dump(),
    }
    _alert_store.append(record)

    logger.info(
        f"[MHA ALERT RECEIVED] caseId={payload.caseId} riskTier={payload.riskTier} "
        f"alertType={payload.alertType} jurisdictionId={payload.jurisdictionId} "
        f"suspects={payload.suspects} correlationId={correlation_id}"
    )

    return {
        "status": "acknowledged",
        "mockAlertId": record["mockAlertId"],
        "receivedAt": received_at,
        "message": "MHA portal has received and acknowledged the alert.",
    }


@app.get("/alerts")
async def list_alerts(riskTier: Optional[str] = None, caseId: Optional[str] = None):
    """Return all received alerts, optionally filtered."""
    results = list(_alert_store)
    if riskTier:
        results = [a for a in results if a.get("riskTier") == riskTier]
    if caseId:
        results = [a for a in results if a.get("caseId") == caseId]
    return {"total": len(results), "alerts": results}


@app.get("/alerts/count")
async def alert_count():
    """Quick count endpoint for SLO verification scripts."""
    return {"total": len(_alert_store)}


@app.delete("/alerts", status_code=200)
async def clear_alerts():
    """Clear all stored alerts (test teardown)."""
    count = len(_alert_store)
    _alert_store.clear()
    logger.info(f"Alert store cleared ({count} alerts removed)")
    return {"cleared": count}


@app.get("/health/live")
def health_live():
    return {"status": "alive", "service": "mha-webhook-mock"}
@app.post("/bank/block-transfer", status_code=200)
async def block_bank_transfer(request: Request, payload: Dict[str, Any]):
    """
    Simulated Bank Core API for immediate transfer block.
    """
    logger.info(f"[BANK BLOCK STUB] Account transfer blocked for session {payload.get('sessionId')}")
    return {
        "status": "blocked",
        "referenceId": f"BLK-{str(uuid.uuid4())[:8]}",
        "sessionId": payload.get("sessionId"),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }
