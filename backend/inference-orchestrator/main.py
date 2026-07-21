"""
Inference Orchestrator — FastAPI Application (T8)

Port: 8000 (internal) | Exposed: 8014 (host) via docker-compose
Internal only — NOT routed through Kong. Called by:
  - Case Service (via Kafka consumer in this pod, Mode A)
  - Event Processing Service POST /inference/analyze sync=True (Mode B, T15)

Endpoints:
  POST /inference/analyze                      — trigger fusion (async 202 or sync 200)
  GET  /inference/predictions/{predictionId}   — retrieve stored verdict
  GET  /inference/cases/{caseId}/latest        — most recent verdict for a case
  GET  /health/ready                           — readiness (DB + Redis + Kafka)
  GET  /health/live                            — liveness (always 200)
  GET  /metrics                                — Prometheus

Design notes:
  - Kafka consumer runs as a background asyncio.Task (lifespan).
  - Shared httpx.AsyncClient with connection pool (max_connections=50).
  - No JWT middleware — internal service on platform-net Docker network.
  - asyncpg UUIDs and datetimes are serialized to str before JSON response.
"""

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, field_validator

from config import settings
from database import db
from kafka_consumer import run_consumer
from orchestrator import (
    AnalyzeRequest,
    ComplaintPayload,
    EvidenceRef,
    analyze,
)
from publisher import publisher
from redis_client import redis_client

# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("orch-api")

# ── Shared HTTP client (created once, not per-request) ─────────────────────────
_http_client: Optional[httpx.AsyncClient] = None


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _http_client

    logger.info("Inference Orchestrator starting up…")

    # Connect DB
    await db.connect()

    # Connect Redis
    await redis_client.connect(settings.REDIS_URL)

    # Connect Kafka publisher
    publisher.connect()

    # Create shared HTTP client (never recreated per-request)
    _http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(3.0),  # outer timeout; per-model timeout handled by asyncio.wait_for
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
    )

    # Start Kafka consumer as background task
    consumer_task = asyncio.create_task(run_consumer(_http_client))
    logger.info("Kafka consumer task started")

    yield

    # Shutdown
    logger.info("Inference Orchestrator shutting down…")
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass

    await _http_client.aclose()
    publisher.close()
    await redis_client.close()
    await db.close()
    logger.info("Shutdown complete")


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Inference Orchestrator",
    description="Parallel multi-source AI dispatch, score fusion, HITL routing (T8).",
    version=settings.SERVICE_VERSION,
    lifespan=lifespan,
)

Instrumentator().instrument(app).expose(app)


# ── Request / Response schemas ─────────────────────────────────────────────────

class EvidenceRefSchema(BaseModel):
    evidenceId: str
    mimeType: str


class ComplaintSchema(BaseModel):
    title: str
    description: str
    complaintType: str
    suspectPhone: Optional[str] = None
    suspectAccount: Optional[str] = None
    languageCode: str = "en"


class AnalyzeRequestSchema(BaseModel):
    caseId: str
    triggerType: str
    complaint: ComplaintSchema
    evidenceRefs: List[EvidenceRefSchema] = []
    sync: bool = False
    onlyModels: Optional[List[str]] = None

    @field_validator("triggerType")
    @classmethod
    def validate_trigger(cls, v):
        valid = {"CASE_CREATED", "EVIDENCE_UPLOADED", "TELECOM_EVENT", "BANK_TRANSACTION"}
        if v not in valid:
            raise ValueError(f"triggerType must be one of {valid}")
        return v

    @field_validator("caseId")
    @classmethod
    def validate_case_id(cls, v):
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError("caseId must be a valid UUID")
        return v


# ── Response helpers ───────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _ok(data: Any, request: Request, status: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "requestId": str(uuid.uuid4()),
            "correlationId": request.headers.get("X-Correlation-ID", str(uuid.uuid4())),
            "timestamp": _ts(),
            "status": "success",
            "data": data,
        },
    )


def _error(request: Request, status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "requestId": str(uuid.uuid4()),
            "correlationId": request.headers.get("X-Correlation-ID", str(uuid.uuid4())),
            "timestamp": _ts(),
            "status": "error",
            "errorCode": code,
            "message": message,
        },
    )


def _verdict_to_dict(v) -> dict:
    """Serialize FusedVerdict dataclass to JSON-safe dict."""
    return {
        "predictionId": str(v.prediction_id),
        "caseId": str(v.case_id),
        "fusedScore": v.fused_score,
        "riskTier": v.risk_tier,
        "confidence": v.confidence,
        "status": v.status,
        "modelBreakdown": v.model_breakdown,
        "explanation": v.explanation,
        "fusionWeights": v.fusion_weights,
        "pendingReview": v.pending_review,
        "fusionTimestamp": v.fusion_timestamp,
        "correlationId": str(v.correlation_id) if v.correlation_id else None,
    }


def _db_row_to_dict(row: dict) -> dict:
    """Convert a stored verdict into the public, camelCase API contract."""
    import json as _json

    field_names = {
        "prediction_id": "predictionId",
        "case_id": "caseId",
        "trigger_type": "triggerType",
        "requested_at": "requestedAt",
        "fused_score": "fusedScore",
        "risk_tier": "riskTier",
        "model_breakdown": "modelBreakdown",
        "fusion_weights": "fusionWeights",
        "pending_review": "pendingReview",
        "fusion_timestamp": "fusionTimestamp",
        "correlation_id": "correlationId",
    }
    result = {}
    for k, v in row.items():
        public_name = field_names.get(k, k)
        if isinstance(v, uuid.UUID):
            result[public_name] = str(v)
        elif isinstance(v, datetime):
            result[public_name] = v.isoformat().replace("+00:00", "Z")
        elif isinstance(v, (str, int, float, bool, type(None))):
            result[public_name] = v
        else:
            result[public_name] = str(v)
    # Deserialize JSONB fields
    for jsonb_field in ("modelBreakdown", "fusionWeights"):
        if jsonb_field in result and isinstance(result[jsonb_field], str):
            try:
                result[jsonb_field] = _json.loads(result[jsonb_field])
            except Exception:
                pass
    return result


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.post("/inference/analyze")
async def analyze_endpoint(body: AnalyzeRequestSchema, request: Request):
    """
    Trigger multi-source AI fusion for a case.

    sync=False (default): returns 202 PROCESSING immediately.
                          Result published to prediction.completed Kafka topic.
    sync=True:            runs fusion inline, returns 200 with full FusedVerdict.
                          Used by Event Processing for <300ms interdiction path (T15).
                          Retry is skipped in sync mode to protect the SLA.
    """
    try:
        case_id = uuid.UUID(body.caseId)
    except ValueError:
        return _error(request, 400, "INVALID_UUID", "caseId is not a valid UUID")

    corr_raw = request.headers.get("X-Correlation-ID")
    correlation_id = uuid.UUID(corr_raw) if corr_raw else uuid.uuid4()

    orch_request = AnalyzeRequest(
        case_id=case_id,
        trigger_type=body.triggerType,
        complaint=ComplaintPayload(
            title=body.complaint.title,
            description=body.complaint.description,
            complaint_type=body.complaint.complaintType,
            suspect_phone=body.complaint.suspectPhone,
            suspect_account=body.complaint.suspectAccount,
            language_code=body.complaint.languageCode,
        ),
        evidence_refs=[
            EvidenceRef(evidence_id=e.evidenceId, mime_type=e.mimeType)
            for e in body.evidenceRefs
        ],
        sync=body.sync,
        only_models=body.onlyModels,
        correlation_id=correlation_id,
    )

    if body.sync:
        # Mode B: synchronous — full verdict inline
        try:
            verdict = await analyze(orch_request, _http_client)
            return _ok(_verdict_to_dict(verdict), request, status=200)
        except Exception as e:
            logger.error(f"Sync analyze error for case {body.caseId}: {e}")
            return _error(request, 503, "ANALYSIS_FAILED", "Inference engine temporarily unavailable")
    else:
        # Mode A: async — fire-and-forget, return 202 immediately
        prediction_id = uuid.uuid4()
        asyncio.create_task(_run_async_analysis(orch_request))
        return _ok(
            {
                "predictionId": str(prediction_id),
                "status": "PROCESSING",
                "estimatedCompletionMs": 2000,
            },
            request,
            status=202,
        )


async def _run_async_analysis(request: AnalyzeRequest) -> None:
    """Background task for Mode A (async path). Errors are logged, not raised."""
    try:
        await analyze(request, _http_client)
    except Exception as e:
        logger.error(f"Async analysis failed for case {request.case_id}: {e}")


@app.get("/inference/predictions/{prediction_id}")
async def get_prediction(prediction_id: str, request: Request):
    """Retrieve a stored FusedVerdict by prediction_id."""
    try:
        pred_uuid = uuid.UUID(prediction_id)
    except ValueError:
        return _error(request, 400, "INVALID_UUID", "prediction_id is not a valid UUID")

    row = await db.fetch_verdict(pred_uuid)
    if row is None:
        return _error(request, 404, "PREDICTION_NOT_FOUND", f"No prediction found for id={prediction_id}")

    return _ok(_db_row_to_dict(row), request)


@app.get("/inference/cases/{case_id}/latest")
async def get_latest_for_case(case_id: str, request: Request):
    """Get the most recent FusedVerdict for a case."""
    try:
        case_uuid = uuid.UUID(case_id)
    except ValueError:
        return _error(request, 400, "INVALID_UUID", "case_id is not a valid UUID")

    row = await db.fetch_latest_for_case(case_uuid)
    if row is None:
        return _error(request, 404, "NO_PREDICTION_YET", f"No predictions found for caseId={case_id}")

    return _ok(_db_row_to_dict(row), request)


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health/ready")
async def health_ready(request: Request):
    db_ok = await db.ping()
    redis_ok = await redis_client.ping()
    kafka_ok = await publisher.ping()
    all_ok = db_ok and redis_ok and kafka_ok
    payload = {
        "status": "ready" if all_ok else "degraded",
        "db": "ok" if db_ok else "error",
        "redis": "ok" if redis_ok else "error",
        "kafka": "ok" if kafka_ok else "error",
    }
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={
            "requestId": str(uuid.uuid4()),
            "timestamp": _ts(),
            "status": "success" if all_ok else "error",
            "data": payload,
        },
    )


@app.get("/health/live")
async def health_live():
    return JSONResponse(content={"status": "alive"})
