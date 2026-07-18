"""
Audit Service — FastAPI Read API (T7)

Port: 8000 (internal) | Exposed: 8007 (host) via docker-compose
Auth: JWT validated by Kong; X-User-Role header forwarded to this service.

Endpoints:
  GET /health/ready                   — readiness probe (checks DB)
  GET /health/live                    — liveness probe (always 200)
  GET /api/v1/audit/case/{case_id}    — full immutable trail for a case
  GET /api/v1/audit/entity/{entity_id} — trail for any entity type

Design notes:
  - No write endpoints. ALL writes come from the Kafka consumer pod.
  - Pagination: cursor-encoded (base64) keyset on (created_at ASC, id ASC).
    Direction is ASCENDING (chronological) — legal logs are read oldest-first.
  - Jurisdiction check deferred to Investigator BFF (T6b) — see plan §Design §3.
  - Response envelope matches _shared_contract.md conventions used by other services.
  - RBAC: minimal check on X-User-Role header (INVESTIGATOR or ADMIN allowed).
    Kong enforces JWT validity; this service trusts the header Kong forwards.

⚠️  Tweaks vs plan:
  - Path prefix is /api/v1/audit/* (not /audit/*) for consistency with all other
    backend services. Kong will route /api/v1/audit → audit:8000.
  - asyncpg rows are converted with dict(row) + str() for UUID/datetime fields
    because asyncpg returns native Python types (uuid.UUID, datetime) that are
    not JSON-serialisable by FastAPI's default encoder without conversion.
"""

import base64
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from config import settings
from database import db

# ── App Setup ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("audit-api")

app = FastAPI(
    title="Audit Service",
    description="Immutable audit ledger — legal admissibility (NFR-6.1). Read-only API; all writes via Kafka consumer.",
    version=settings.SERVICE_VERSION,
)

Instrumentator().instrument(app).expose(app)

# ── Allowed roles for audit reads ──────────────────────────────────────────────

ALLOWED_ROLES = {"INVESTIGATOR", "ADMIN"}

# ── Lifecycle ──────────────────────────────────────────────────────────────────


@app.on_event("startup")
async def startup():
    logger.info("Audit API starting — connecting to PostgreSQL...")
    try:
        await db.connect()
        logger.info("DB pool ready")
    except Exception as e:
        # Don't crash on startup if DB is briefly unavailable; readiness probe will
        # report not-ready until the pool succeeds.
        logger.warning(f"DB connection failed at startup (readiness probe will catch this): {e}")


@app.on_event("shutdown")
async def shutdown():
    await db.close()


# ── Response helpers ───────────────────────────────────────────────────────────

def _envelope(request: Request, data: Any) -> Dict[str, Any]:
    """Standard platform response envelope — matches _shared_contract.md."""
    corr_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    return {
        "requestId": str(uuid.uuid4()),
        "correlationId": corr_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "success",
        "data": data,
    }


def _error(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    corr_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    return JSONResponse(
        status_code=status_code,
        content={
            "requestId": str(uuid.uuid4()),
            "correlationId": corr_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "error",
            "errorCode": code,
            "message": message,
        },
    )


# ── RBAC helper ───────────────────────────────────────────────────────────────

def _check_role(request: Request) -> Optional[JSONResponse]:
    """
    Validate X-User-Role header forwarded by Kong after JWT verification.
    Returns a 403 JSONResponse if role is not allowed, else None.
    """
    role = request.headers.get("X-User-Role", "")
    if role not in ALLOWED_ROLES:
        return _error(
            request, 403, "FORBIDDEN_ROLE",
            f"Role '{role}' is not permitted to access audit records. "
            f"Required: {sorted(ALLOWED_ROLES)}"
        )
    return None


# ── Cursor pagination helpers ──────────────────────────────────────────────────

def _encode_cursor(created_at: str, row_id: str) -> str:
    """Encode keyset position as an opaque base64 cursor."""
    payload = json.dumps({"createdAt": created_at, "id": row_id})
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_cursor(cursor: str) -> Optional[Dict[str, str]]:
    """Decode cursor; returns dict with createdAt and id, or None on failure."""
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        return {"createdAt": payload["createdAt"], "id": payload["id"]}
    except Exception:
        return None


# ── Row serialisation ──────────────────────────────────────────────────────────

def _serialise_row(row) -> Dict[str, Any]:
    """
    Convert an asyncpg Record to a JSON-safe dict.

    asyncpg returns native Python types (uuid.UUID, datetime.datetime, dict for JSONB).
    We normalise them to strings / plain dicts for FastAPI's JSON encoder.

    ⚠️  Tweak: payload comes back as a dict from asyncpg (JSONB auto-decoded);
        we pass it through as-is so the API response embeds the full payload object.
    """
    payload_raw = row["payload"]
    # asyncpg may return JSONB as str or dict depending on codec registration
    if isinstance(payload_raw, str):
        try:
            payload_raw = json.loads(payload_raw)
        except json.JSONDecodeError:
            pass  # leave as string if malformed

    return {
        "auditId": str(row["id"]),
        "eventType": row["event_type"],
        "entityType": row["entity_type"],
        "entityId": str(row["entity_id"]),
        "actorId": str(row["actor_id"]) if row["actor_id"] else None,
        "actorRole": row["actor_role"],
        "payload": payload_raw,
        "correlationId": str(row["correlation_id"]) if row["correlation_id"] else None,
        "createdAt": row["created_at"].isoformat().replace("+00:00", "Z"),
    }


# ── Health Endpoints ───────────────────────────────────────────────────────────

@app.get("/health/ready", tags=["Health"])
async def health_ready():
    """
    Readiness probe: checks that the asyncpg pool can reach PostgreSQL.
    Returns 503 if DB is not yet available.
    """
    if db.pool is None:
        return JSONResponse(status_code=503, content={"status": "not_ready", "reason": "pool_not_initialised"})
    ok = await db.ping()
    if ok:
        return {"status": "ready", "db": "ok"}
    return JSONResponse(status_code=503, content={"status": "not_ready", "db": "unreachable"})


@app.get("/health/live", tags=["Health"])
async def health_live():
    """Liveness probe — always 200 as long as the process is running."""
    return {"status": "alive"}


# ── Audit Endpoints ────────────────────────────────────────────────────────────

@app.get("/api/v1/audit/case/{case_id}", tags=["Audit"])
async def get_case_audit_trail(
    request: Request,
    case_id: str = Path(..., description="Case UUID"),
    cursor: Optional[str] = Query(None, description="Pagination cursor (opaque)"),
    limit: int = Query(20, ge=1, le=100, description="Max results (default 20, max 100)"),
):
    """
    GET /api/v1/audit/case/{caseId}

    Returns the full immutable audit trail for a case in chronological order.
    Covers ALL entity types whose events reference this caseId — Case state
    changes, Evidence uploads, Prediction overrides, etc.

    Auth: X-User-Role must be INVESTIGATOR or ADMIN (forwarded by Kong).

    Pagination: cursor-based keyset on (created_at ASC, id ASC).
    Follow nextCursor until hasMore is false.

    Note on 404 (see plan §Design §3): existence is NOT validated against the
    Case Service to keep this service fully decoupled. An empty items array is
    returned if no audit events exist yet for the given caseId. The Investigator
    BFF (T6b) is responsible for the 404 CASE_NOT_FOUND surface.
    """
    # RBAC check
    role_err = _check_role(request)
    if role_err:
        return role_err

    # Validate UUID
    try:
        case_uuid = uuid.UUID(case_id)
    except ValueError:
        return _error(request, 400, "INVALID_UUID", f"'{case_id}' is not a valid UUID")

    # Decode cursor
    cursor_ts = cursor_id = None
    if cursor:
        decoded = _decode_cursor(cursor)
        if decoded is None:
            return _error(request, 400, "INVALID_CURSOR", "Cursor is malformed or expired")
        cursor_ts = decoded["createdAt"]
        cursor_id = decoded["id"]

    try:
        rows, total = await db.fetch_by_case(case_uuid, limit, cursor_ts, cursor_id)
    except Exception as e:
        logger.error(f"DB error fetching audit trail for case {case_id}: {e}")
        return _error(request, 503, "DB_UNAVAILABLE", "Audit database is temporarily unavailable")

    items = [_serialise_row(r) for r in rows]
    has_more = len(rows) == limit
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = _encode_cursor(
            created_at=last["created_at"].isoformat().replace("+00:00", "Z"),
            row_id=str(last["id"]),
        )

    return _envelope(request, {
        "items": items,
        "nextCursor": next_cursor,
        "hasMore": has_more,
        "total": total,
    })


@app.get("/api/v1/audit/entity/{entity_id}", tags=["Audit"])
async def get_entity_audit_trail(
    request: Request,
    entity_id: str = Path(..., description="Entity UUID (case, prediction, evidence, etc.)"),
    entityType: Optional[str] = Query(None, description="Filter by entity type (e.g. Case, Prediction, Evidence)"),
    from_ts: Optional[str] = Query(None, alias="from", description="Filter from timestamp (ISO8601)"),
    to_ts: Optional[str] = Query(None, alias="to", description="Filter to timestamp (ISO8601)"),
    cursor: Optional[str] = Query(None, description="Pagination cursor"),
    limit: int = Query(20, ge=1, le=100),
):
    """
    GET /api/v1/audit/entity/{entityId}

    Get audit events for any entity type — case, prediction, evidence, etc.
    Useful for the Investigator BFF to pull narrowly-scoped audit views.

    Auth: X-User-Role must be INVESTIGATOR or ADMIN.
    """
    role_err = _check_role(request)
    if role_err:
        return role_err

    try:
        entity_uuid = uuid.UUID(entity_id)
    except ValueError:
        return _error(request, 400, "INVALID_UUID", f"'{entity_id}' is not a valid UUID")

    cursor_ts = cursor_id = None
    if cursor:
        decoded = _decode_cursor(cursor)
        if decoded is None:
            return _error(request, 400, "INVALID_CURSOR", "Cursor is malformed or expired")
        cursor_ts = decoded["createdAt"]
        cursor_id = decoded["id"]

    try:
        rows, total = await db.fetch_by_entity(entity_uuid, entityType, from_ts, to_ts, limit, cursor_ts, cursor_id)
    except Exception as e:
        logger.error(f"DB error fetching audit trail for entity {entity_id}: {e}")
        return _error(request, 503, "DB_UNAVAILABLE", "Audit database is temporarily unavailable")

    items = [_serialise_row(r) for r in rows]
    has_more = len(rows) == limit
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = _encode_cursor(
            created_at=last["created_at"].isoformat().replace("+00:00", "Z"),
            row_id=str(last["id"]),
        )

    return _envelope(request, {
        "items": items,
        "nextCursor": next_cursor,
        "hasMore": has_more,
        "total": total,
    })
