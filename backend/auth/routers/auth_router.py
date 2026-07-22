"""
Auth Service Router — implements all endpoints from docs/api/auth.md.
Routes: POST /auth/register, /auth/login, /auth/mfa/verify, /auth/refresh, /auth/logout, GET /auth/me
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from db import get_db
from models.schemas import (
    LoginRequest, MFAVerifyRequest,
    RefreshRequest, RegisterRequest, CurrentUser,
)
from redis_client import get_redis
from response_helpers import error_response, success_response
from security.jwt import get_current_user
from services.auth_service import (
    AuthService,
    AccountLockedError, DuplicateEmailError,
    InvalidCredentialsError, InvalidRefreshTokenError,
)

router = APIRouter(prefix="/auth", tags=["Auth"])


def _get_correlation_id(request: Request) -> str:
    return request.headers.get("X-Correlation-ID", str(uuid.uuid4()))


# ── Register ──────────────────────────────────────────────────────────────────

@router.post("/register", status_code=201)
async def register(
    request: Request,
    body: RegisterRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db=Depends(get_db),
    redis=Depends(get_redis),
):
    """Register a new user account. Requires Idempotency-Key header."""
    correlation_id = _get_correlation_id(request)

    if not idempotency_key:
        raise HTTPException(
            status_code=400,
            detail=error_response("MISSING_IDEMPOTENCY_KEY", "Idempotency-Key header is required", correlation_id)
        )

    try:
        idem_uuid = uuid.UUID(idempotency_key)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=error_response("INVALID_IDEMPOTENCY_KEY", "Idempotency-Key must be a valid UUID", correlation_id)
        )

    svc = AuthService(db, redis)
    try:
        result = await svc.register(body, idem_uuid)
        return success_response(result.model_dump(), correlation_id)
    except DuplicateEmailError:
        raise HTTPException(
            status_code=409,
            detail=error_response("DUPLICATE_EMAIL", f"Email is already registered", correlation_id),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=error_response("INVALID_ROLE", str(e), correlation_id),
        )


# ── Login ─────────────────────────────────────────────────────────────────────

@router.post("/login", status_code=200)
async def login(
    request: Request,
    body: LoginRequest,
    db=Depends(get_db),
    redis=Depends(get_redis),
):
    """Authenticate. Returns JWT pair or MFA session token."""
    correlation_id = _get_correlation_id(request)
    svc = AuthService(db, redis)
    try:
        result = await svc.login(body)
        return success_response(result.model_dump(), correlation_id)
    except AccountLockedError:
        raise HTTPException(
            status_code=429,
            detail=error_response("ACCOUNT_LOCKED", "Account temporarily locked. Try again in 15 minutes.", correlation_id),
        )
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=401,
            detail=error_response("INVALID_CREDENTIALS", "Invalid email or password", correlation_id),
        )


# ── MFA Verify ────────────────────────────────────────────────────────────────

@router.post("/mfa/verify", status_code=200)
async def mfa_verify(
    request: Request,
    body: MFAVerifyRequest,
    db=Depends(get_db),
    redis=Depends(get_redis),
):
    """Complete MFA with TOTP code. Returns full JWT pair."""
    correlation_id = _get_correlation_id(request)
    from services.mfa_service import MFAService
    svc_mfa = MFAService(db, redis)
    try:
        result = await svc_mfa.verify_mfa(body.mfa_session_token, body.totp_code)
        return success_response(result.model_dump(), correlation_id)
    except MFAService.MFASessionExpiredError:
        raise HTTPException(
            status_code=401,
            detail=error_response("MFA_SESSION_EXPIRED", "MFA session expired. Please log in again.", correlation_id),
        )
    except MFAService.InvalidTOTPError:
        raise HTTPException(
            status_code=401,
            detail=error_response("INVALID_TOTP", "TOTP code is incorrect", correlation_id),
        )


# ── Refresh ───────────────────────────────────────────────────────────────────

@router.post("/refresh", status_code=200)
async def refresh(
    request: Request,
    body: RefreshRequest,
    db=Depends(get_db),
    redis=Depends(get_redis),
):
    """Exchange refresh token for new access token."""
    correlation_id = _get_correlation_id(request)
    svc = AuthService(db, redis)
    try:
        result = await svc.refresh(body)
        return success_response(result.model_dump(), correlation_id)
    except InvalidRefreshTokenError:
        raise HTTPException(
            status_code=401,
            detail=error_response("REFRESH_TOKEN_INVALID", "Refresh token is invalid or expired", correlation_id),
        )


# ── Logout ────────────────────────────────────────────────────────────────────

@router.post("/logout", status_code=200)
async def logout(
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db=Depends(get_db),
    redis=Depends(get_redis),
):
    """Revoke access token (add JTI to Redis denylist) and invalidate refresh session."""
    correlation_id = _get_correlation_id(request)

    # Extract token expiry for denylist TTL
    credentials = request.headers.get("Authorization", "").replace("Bearer ", "")
    from jose import jwt as jose_jwt
    from config import settings
    payload = jose_jwt.decode(credentials, settings.JWT_PUBLIC_KEY, algorithms=[settings.JWT_ALGORITHM])
    
    svc = AuthService(db, redis)
    import hashlib
    refresh_token = request.headers.get("X-Refresh-Token", "")
    refresh_hash = hashlib.sha256(refresh_token.encode()).hexdigest() if refresh_token else ""
    
    await svc.logout(
        jti=current_user.jti,
        token_exp=payload.get("exp", 0),
        token_hash=refresh_hash,
    )
    return success_response({"message": "Logged out"}, correlation_id)


# ── Me ────────────────────────────────────────────────────────────────────────

@router.get("/me", status_code=200)
async def me(
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Return current user profile from JWT claims. No DB call."""
    correlation_id = _get_correlation_id(request)
    return success_response(
        {
            "userId": str(current_user.user_id),
            "email": current_user.email,
            "role": current_user.role,
            "orgId": str(current_user.org_id) if current_user.org_id else None,
            "jurisdictionId": current_user.jurisdiction_id,
        },
        correlation_id,
    )
