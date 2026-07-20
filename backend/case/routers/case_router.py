"""
Case Service Router — docs/api/case.md
Routes:
  POST   /cases                          — create case
  GET    /cases/:caseId                  — get case detail
  GET    /cases                          — list cases (paginated, RBAC-scoped)
  PATCH  /cases/:caseId/state            — state transition
  PATCH  /cases/:caseId/verdict/override — HITL override
  GET    /cases/:caseId/timeline         — paginated timeline
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from db import get_db
from models.schemas import (
    CreateCaseRequest, UpdateCaseStateRequest, VerdictOverrideRequest, CurrentUser,
    CaseSummaryResponse,
)
from response_helpers import success_response, error_response
from security.jwt import get_current_user, require_role
from services.case_service import (
    CaseService,
    CaseNotFoundError, InvalidTransitionError,
    CasePermissionError, DuplicateCaseError,
)

router = APIRouter(prefix="/cases", tags=["Cases"])


def _corr(request: Request) -> str:
    return request.headers.get("X-Correlation-ID", str(uuid.uuid4()))


# ── Create Case ───────────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_case(
    request: Request,
    body: CreateCaseRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: CurrentUser = Depends(get_current_user),
    db=Depends(get_db),
):
    if not idempotency_key:
        raise HTTPException(
            status_code=400,
            detail=error_response("MISSING_IDEMPOTENCY_KEY", "Idempotency-Key header is required", _corr(request))
        )
    try:
        idem_uuid = uuid.UUID(idempotency_key)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=error_response("INVALID_IDEMPOTENCY_KEY", "Idempotency-Key must be a UUID", _corr(request))
        )

    try:
        corr_uuid = uuid.UUID(_corr(request))
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=error_response("INVALID_CORRELATION_ID", "X-Correlation-ID must be a valid UUID", _corr(request))
        )

    svc = CaseService(db)
    try:
        result = await svc.create_case(
            req=body,
            reporter_user_id=current_user.user_id,
            jurisdiction_id=current_user.jurisdiction_id or "",
            correlation_id=corr_uuid,
            idempotency_key=idem_uuid,
        )
        return success_response(result.model_dump(mode="json", by_alias=True), _corr(request))
    except DuplicateCaseError:
        raise HTTPException(
            status_code=409,
            detail=error_response("DUPLICATE_CASE", "Idempotency key already used", _corr(request)),
        )


# ── Get Case ──────────────────────────────────────────────────────────────────

@router.get("/{case_id}")
async def get_case(
    request: Request,
    case_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db=Depends(get_db),
):
    svc = CaseService(db)
    try:
        result = await svc.get_case(
            case_id=case_id,
            jurisdiction_id=current_user.jurisdiction_id or "",
        )
        return success_response(result.model_dump(mode="json", by_alias=True), _corr(request))
    except CaseNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=error_response("CASE_NOT_FOUND", f"Case {case_id} not found", _corr(request)),
        )
    except CasePermissionError:
        raise HTTPException(
            status_code=403,
            detail=error_response("FORBIDDEN", "Case not accessible in your jurisdiction", _corr(request)),
        )


# ── List Cases ────────────────────────────────────────────────────────────────

@router.get("/my")
async def list_my_cases(
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db=Depends(get_db),
):
    """Get all cases reported by the current citizen user."""
    from sqlalchemy import select
    from models.case import Case
    
    result = await db.execute(
        select(Case).where(Case.reporter_user_id == current_user.user_id).order_by(Case.created_at.desc())
    )
    items = result.scalars().all()
    
    return success_response({
        "items": [
            CaseSummaryResponse(
                case_id=i.case_id,
                case_number=i.case_number,
                title=i.title,
                complaint_type=i.complaint_type,
                status=i.status,
                priority=i.priority,
                jurisdiction_id=i.jurisdiction_id,
                assigned_to=i.assigned_investigator,
                risk_tier=None,
                created_at=i.created_at,
                updated_at=i.updated_at,
            ).model_dump(mode="json", by_alias=True)
            for i in items
        ]
    }, _corr(request))


@router.get("")
async def list_cases(
    request: Request,
    status: Optional[str] = None,
    risk_tier: Optional[str] = None,
    assigned_to: Optional[uuid.UUID] = None,
    cursor: Optional[str] = None,
    limit: int = 20,
    current_user: CurrentUser = Depends(get_current_user),
    db=Depends(get_db),
):
    from repositories.case_repository import CaseRepository
    repo = CaseRepository(db)
    items, next_cursor, has_more, total = await repo.list(
        jurisdiction_id=current_user.jurisdiction_id or "",
        status=status,
        risk_tier=risk_tier,
        assigned_to=assigned_to,
        cursor=cursor,
        limit=min(limit, 100),
    )
    return success_response({
        "items": [
            CaseSummaryResponse(
                case_id=i.case_id,
                case_number=i.case_number,
                title=i.title,
                complaint_type=i.complaint_type,
                status=i.status,
                priority=i.priority,
                jurisdiction_id=i.jurisdiction_id,
                assigned_to=i.assigned_investigator,
                risk_tier=None,   # populated by Inference Orchestrator (T13)
                created_at=i.created_at,
                updated_at=i.updated_at,
            ).model_dump(mode="json", by_alias=True)
            for i in items
        ],
        "nextCursor": next_cursor,
        "hasMore": has_more,
        "total": total,
    }, _corr(request))


# ── State Transition ──────────────────────────────────────────────────────────

@router.patch("/{case_id}/state")
async def update_case_state(
    request: Request,
    case_id: uuid.UUID,
    body: UpdateCaseStateRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: CurrentUser = Depends(get_current_user),
    db=Depends(get_db),
):
    svc = CaseService(db)
    try:
        result = await svc.update_state(
            case_id=case_id,
            req=body,
            caller_role=current_user.role,
            caller_id=current_user.user_id,
            correlation_id=uuid.uuid4(),
        )
        return success_response(result.model_dump(mode="json", by_alias=True), _corr(request))
    except CaseNotFoundError:
        raise HTTPException(status_code=404, detail=error_response("CASE_NOT_FOUND", "Not found", _corr(request)))
    except InvalidTransitionError as e:
        raise HTTPException(status_code=422, detail=error_response("INVALID_STATE_TRANSITION", str(e), _corr(request)))
    except CasePermissionError as e:
        raise HTTPException(status_code=403, detail=error_response("FORBIDDEN", str(e), _corr(request)))


# ── Verdict Override ──────────────────────────────────────────────────────────

@router.post("/{case_id}/verdict/pending-review", status_code=200, include_in_schema=False)
async def set_pending_review(
    request: Request,
    case_id: uuid.UUID,
    body: dict,   # {predictionPayload: dict, correlationId: str}
    db=Depends(get_db),
):
    """
    Internal endpoint — called by Inference Orchestrator only.
    Not exposed in Kong (include_in_schema=False).
    Sets case to Pending_AI state when confidence < 0.60.
    """
    svc = CaseService(db)
    try:
        await svc.set_pending_review(
            case_id=case_id,
            prediction_payload=body.get("predictionPayload", {}),
            correlation_id=uuid.UUID(body.get("correlationId", str(uuid.uuid4()))),
        )
        return {"status": "ok"}
    except CaseNotFoundError:
        raise HTTPException(status_code=404, detail={"errorCode": "CASE_NOT_FOUND"})


@router.patch("/{case_id}/verdict/override")
async def override_verdict(
    request: Request,
    case_id: uuid.UUID,
    body: VerdictOverrideRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: CurrentUser = Depends(require_role("INVESTIGATOR", "ADMIN")),
    db=Depends(get_db),
):
    svc = CaseService(db)
    try:
        result = await svc.override_verdict(
            case_id=case_id,
            req=body,
            investigator_id=current_user.user_id,
            correlation_id=uuid.uuid4(),
        )
        # Note: returning dump of response schema
        return success_response(result.model_dump(mode="json", by_alias=True) if hasattr(result, "model_dump") else result, _corr(request))
    except CaseNotFoundError:
        raise HTTPException(status_code=404, detail=error_response("CASE_NOT_FOUND", "Not found", _corr(request)))
    except InvalidTransitionError as e:
        raise HTTPException(status_code=422, detail=error_response("INVALID_STATE_TRANSITION", str(e), _corr(request)))


# ── Timeline ──────────────────────────────────────────────────────────────────

@router.get("/{case_id}/timeline")
async def get_timeline(
    request: Request,
    case_id: uuid.UUID,
    cursor: Optional[str] = None,
    limit: int = 20,
    current_user: CurrentUser = Depends(get_current_user),
    db=Depends(get_db),
):
    from repositories.timeline_repository import TimelineRepository
    repo = TimelineRepository(db)
    items, next_cursor, has_more, total = await repo.paginate(
        case_id=case_id,
        cursor=cursor,
        limit=min(limit, 100),
    )
    return success_response({
        "items": [
            {
                "eventType": e.event_type,
                "actor": str(e.actor_id) if e.actor_id else "system",
                "actorRole": e.actor_role or "system",
                "description": e.description,
                "metadata": getattr(e, "event_metadata", {}) or getattr(e, "metadata", {}) or {},
                "timestamp": e.created_at.isoformat().replace("+00:00", "Z"),
            }
            for e in items
        ],
        "nextCursor": next_cursor,
        "hasMore": has_more,
        "total": total,
    }, _corr(request))
