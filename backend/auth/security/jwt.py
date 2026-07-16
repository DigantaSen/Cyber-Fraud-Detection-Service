"""
JWT Security — RS256 sign/verify for Auth Service.
Auth Service is the ISSUER — it signs tokens with the private key.
All other services only VERIFY using the public key (they trust Kong to pre-validate).

Key patterns from docs/db/redis.md:
  auth:denylist:{jti}    → revoked access tokens (TTL = remaining expiry)
"""
import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from config import settings
from models.schemas import CurrentUser
from repositories.session_repository import SessionRepository

logger = logging.getLogger(__name__)

if not settings.JWT_PRIVATE_KEY:
    logger.warning("JWT_PRIVATE_KEY is empty. Token signing will fail at runtime.")

_bearer_scheme = HTTPBearer(auto_error=False)


# ── Token Signing (Auth Service only) ─────────────────────────────────────────

def sign_access_token(user) -> str:
    """
    Sign a new RS256 access token for the given user.
    Claims: sub, role, orgId, jurisdictionId, jti, exp, iat, kid.
    """
    now = datetime.now(timezone.utc)
    jti = str(uuid.uuid4())
    payload = {
        "sub": str(user.user_id),
        "email": user.email,
        "role": user.role,
        "orgId": str(user.org_id) if user.org_id else None,
        "jurisdictionId": user.jurisdiction_id,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)).timestamp()),
        "kid": "v1",   # Key version for rotation support
    }
    return jwt.encode(payload, settings.JWT_PRIVATE_KEY, algorithm=settings.JWT_ALGORITHM)


def _create_refresh_token() -> tuple[str, str]:
    """
    Generate an opaque refresh token.
    Returns (plaintext_token, sha256_hash).
    Plaintext is sent to client; hash is stored in DB.
    """
    token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    return token, token_hash


async def create_token_pair(user, db, session_repo: SessionRepository) -> tuple[str, str]:
    """
    Create access + refresh token pair.
    Stores refresh token hash in identity.sessions.
    Returns (access_token_jwt, refresh_token_plaintext).
    """
    from datetime import timezone
    access_token = sign_access_token(user)
    refresh_token, token_hash = _create_refresh_token()

    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    await session_repo.create(
        user_id=user.user_id,
        refresh_token_hash=token_hash,
        expires_at=expires_at,
    )
    return access_token, refresh_token


# ── Token Verification (used by all services) ─────────────────────────────────

def decode_token(token: str) -> dict:
    """
    Decode and validate JWT.
    Uses the PUBLIC key only — does not sign.
    Raises JWTError on invalid/expired token.
    """
    return jwt.decode(
        token,
        settings.JWT_PUBLIC_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        options={"require": ["sub", "role", "jti", "exp"]},
    )


# ── FastAPI Dependency ─────────────────────────────────────────────────────────

async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> CurrentUser:
    """
    FastAPI dependency injected into protected endpoints.
    1. Extracts Bearer token from Authorization header.
    2. Decodes JWT (signature already validated by Kong upstream).
    3. Checks Redis denylist to catch logged-out tokens.
    4. Returns CurrentUser with all RBAC claims.

    NOTE: In internal service-to-service calls that bypass Kong,
    full JWT signature verification is performed here.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"errorCode": "MISSING_TOKEN", "message": "Authorization header required"},
        )

    token = credentials.credentials
    try:
        payload = decode_token(token)
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"errorCode": "INVALID_TOKEN", "message": str(e)},
        )

    jti = payload.get("jti")
    if not jti:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"errorCode": "INVALID_TOKEN", "message": "Token missing jti claim"},
        )

    # Denylist check
    redis_client: aioredis.Redis = request.app.state.redis
    if await redis_client.exists(f"auth:denylist:{jti}"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"errorCode": "TOKEN_REVOKED", "message": "Token has been revoked"},
        )

    return CurrentUser(
        user_id=uuid.UUID(payload["sub"]),
        email=payload.get("email", ""),
        role=payload["role"],
        org_id=uuid.UUID(payload["orgId"]) if payload.get("orgId") else None,
        jurisdiction_id=payload.get("jurisdictionId"),
        jti=jti,
    )


def require_role(*roles: str):
    """
    Role-based access control decorator factory.
    Usage: current_user: CurrentUser = Depends(require_role("INVESTIGATOR", "ADMIN"))
    """
    async def _check_role(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"errorCode": "FORBIDDEN", "message": f"Role {current_user.role} is not permitted"},
            )
        return current_user
    return _check_role
