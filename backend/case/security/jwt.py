"""
JWT Security — RS256 sign/verify for Case Service.
All other services only VERIFY using the public key (they trust Kong to pre-validate).

Key patterns from docs/db/redis.md:
  auth:denylist:{jti}    → revoked access tokens (TTL = remaining expiry)
"""
import logging
import uuid
from typing import Optional

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from config import settings
from models.schemas import CurrentUser

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


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
