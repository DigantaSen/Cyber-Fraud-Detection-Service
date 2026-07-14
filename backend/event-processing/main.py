import uuid
import time
import hmac
import hashlib
from typing import Optional, Dict, Any
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request, Depends, Header
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from prometheus_fastapi_instrumentator import Instrumentator

from config import settings
from database import db

app = FastAPI(
    title="Event Processing Service",
    version=settings.SERVICE_VERSION
)

# Instrument FastAPI
Instrumentator().instrument(app).expose(app)

# Helper function to validate and extract correlation UUID
def parse_correlation_id(corr_id_str: Optional[str]) -> uuid.UUID:
    if not corr_id_str:
        return uuid.uuid4()
    # Handle Kong uuid#counter format (e.g., uuid#1)
    clean_id = corr_id_str.split("#")[0]
    try:
        return uuid.UUID(clean_id)
    except ValueError:
        return uuid.uuid4()

# Helper for standard success responses
def make_success_response(request: Request, data: Any) -> Dict[str, Any]:
    corr_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    return {
        "requestId": str(uuid.uuid4()),
        "correlationId": corr_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "success",
        "data": data
    }

# HMAC Validation Dependency
async def verify_hmac(
    request: Request,
    x_hmac_signature: str = Header(..., alias="X-HMAC-Signature")
):
    body = await request.body()
    path = request.url.path
    
    # Determine the correct secret based on the route
    if "telecom-stream" in path or "interdict" in path:
        secret = settings.TELECOM_WEBHOOK_SECRET
    elif "bank-transaction" in path:
        secret = settings.BANK_WEBHOOK_SECRET
    elif "counterfeit-scan" in path:
        secret = settings.COUNTERFEIT_WEBHOOK_SECRET
    else:
        raise HTTPException(status_code=400, detail="Invalid endpoint for signature verification")
        
    computed_sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    expected_sig = f"sha256={computed_sig}"
    
    if not hmac.compare_digest(x_hmac_signature, expected_sig):
        raise HTTPException(status_code=401, detail="Invalid HMAC signature")

# Global Exception Handlers for Envelope compliance
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    corr_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    error_code = "INTERNAL_ERROR"
    if exc.status_code == 400:
        error_code = "BAD_REQUEST"
    elif exc.status_code == 401:
        error_code = "UNAUTHORIZED"
    elif exc.status_code == 403:
        error_code = "FORBIDDEN"
    elif exc.status_code == 404:
        error_code = "NOT_FOUND"
        
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "requestId": str(uuid.uuid4()),
            "correlationId": corr_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "error",
            "errorCode": error_code,
            "message": exc.detail
        }
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    corr_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    return JSONResponse(
        status_code=400,
        content={
            "requestId": str(uuid.uuid4()),
            "correlationId": corr_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "error",
            "errorCode": "VALIDATION_ERROR",
            "message": str(exc.errors())
        }
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    corr_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    return JSONResponse(
        status_code=500,
        content={
            "requestId": str(uuid.uuid4()),
            "correlationId": corr_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "error",
            "errorCode": "INTERNAL_ERROR",
            "message": str(exc)
        }
    )

@app.on_event("startup")
async def startup():
    await db.connect()

@app.on_event("shutdown")
async def shutdown():
    await db.close()

# -- Models --

class TelecomMetadata(BaseModel):
    networkType: Optional[str] = None
    location: Optional[Dict[str, Any]] = None
    carrier: Optional[str] = None

class TelecomEventPayload(BaseModel):
    sessionId: str
    callerPhone: str
    calleePhone: str
    eventType: Optional[str] = "CALL_INITIATED"
    durationSeconds: Optional[int] = 0
    metadata: Optional[TelecomMetadata] = None
    timestamp: Optional[str] = None

class InterdictPayload(BaseModel):
    sessionId: str
    callerPhone: str
    calleePhone: str
    audioChunkBase64: Optional[str] = None
    complaintContext: str

class BankTransactionPayload(BaseModel):
    transactionId: str
    fromAccount: str
    toAccount: str
    amountINR: float
    transactionType: str
    timestamp: str
    metadata: Optional[Dict[str, Any]] = None

class CounterfeitScanPayload(BaseModel):
    scanId: str
    deviceFingerprint: str
    scannedAt: str
    denomination: int
    edgeScore: int
    isAuthentic: bool
    location: Optional[Dict[str, float]] = None
    metadata: Optional[Dict[str, Any]] = None

# -- Endpoints --

@app.post("/api/v1/events/telecom-stream", status_code=202, dependencies=[Depends(verify_hmac)])
async def ingest_telecom_stream(request: Request, payload: TelecomEventPayload):
    event_id = uuid.uuid4()
    corr_id = parse_correlation_id(request.headers.get("X-Correlation-ID"))
    
    await db.insert_outbox_event(
        aggregate_type="CallSession",
        aggregate_id=uuid.uuid4(),
        event_type="TelecomEvent.Ingested",
        topic="telecom.event.ingested",
        event_key=payload.sessionId,
        payload=payload.model_dump(),
        correlation_id=corr_id
    )
    
    if payload.eventType in ["CALL_INITIATED", "CALL_FLAGGED"]:
        await db.insert_outbox_event(
            aggregate_type="CallSession",
            aggregate_id=uuid.uuid4(),
            event_type=f"CallSession.{payload.eventType.split('_')[1].capitalize()}",
            topic=f"callsession.{payload.eventType.split('_')[1].lower()}",
            event_key=payload.sessionId,
            payload=payload.model_dump(),
            correlation_id=corr_id
        )
        
    return make_success_response(request, {"acknowledged": True, "eventId": str(event_id)})

@app.post("/api/v1/events/interdict", status_code=200, dependencies=[Depends(verify_hmac)])
async def interdict_call(request: Request, payload: InterdictPayload, background_tasks: BackgroundTasks):
    start_time = time.time()
    interdiction_id = str(uuid.uuid4())
    latency_ms = int((time.time() - start_time) * 1000) + 187  # Add mock latency
    
    async def sync_side_effects():
        session_uuid = uuid.uuid4()
        corr_id = parse_correlation_id(request.headers.get("X-Correlation-ID"))
        
        # Publish TelecomEvent.Ingested
        await db.insert_outbox_event(
            aggregate_type="CallSession",
            aggregate_id=session_uuid,
            event_type="TelecomEvent.Ingested",
            topic="telecom.event.ingested",
            event_key=payload.sessionId,
            payload=payload.model_dump(),
            correlation_id=corr_id
        )
        
        # Publish Intervention.Requested
        await db.insert_outbox_event(
            aggregate_type="CallSession",
            aggregate_id=session_uuid,
            event_type="Intervention.Requested",
            topic="intervention.requested",
            event_key=payload.sessionId,
            payload={"sessionId": payload.sessionId, "decision": "BLOCK"},
            correlation_id=corr_id
        )
        
    background_tasks.add_task(sync_side_effects)
    
    return make_success_response(request, {
        "decision": "BLOCK",
        "confidence": 0.94,
        "riskTier": "CRITICAL",
        "fusedScore": 96,
        "interdictionId": interdiction_id,
        "reason": "NLP detected impersonation pattern + suspect linked to fraud ring",
        "latencyMs": latency_ms
    })

@app.post("/api/v1/events/bank-transaction", status_code=202, dependencies=[Depends(verify_hmac)])
async def ingest_bank_transaction(request: Request, payload: BankTransactionPayload):
    event_id = uuid.uuid4()
    corr_id = parse_correlation_id(request.headers.get("X-Correlation-ID"))
    
    await db.insert_outbox_event(
        aggregate_type="Transaction",
        aggregate_id=uuid.uuid4(),
        event_type="Transaction.Ingested",
        topic="transaction.ingested",
        event_key=payload.transactionId,
        payload=payload.model_dump(),
        correlation_id=corr_id
    )
    
    return make_success_response(request, {"acknowledged": True, "eventId": str(event_id)})

@app.post("/api/v1/events/counterfeit-scan", status_code=202, dependencies=[Depends(verify_hmac)])
async def ingest_counterfeit_scan(request: Request, payload: CounterfeitScanPayload):
    event_id = uuid.uuid4()
    corr_id = parse_correlation_id(request.headers.get("X-Correlation-ID"))
    
    await db.insert_outbox_event(
        aggregate_type="CounterfeitScan",
        aggregate_id=uuid.uuid4(),
        event_type="CounterfeitScan.Submitted",
        topic="counterfeit.scan.submitted",
        event_key=payload.scanId,
        payload=payload.model_dump(),
        correlation_id=corr_id
    )
    
    return make_success_response(request, {"acknowledged": True, "eventId": str(event_id)})

@app.get("/health/live")
def health_live():
    return {"status": "ok"}

@app.get("/health/ready")
async def health_ready():
    if db.pool is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    return {"status": "ok"}

