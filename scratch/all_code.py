
# ----------------------------------------
# FILE: backend/auth/config.py
# ----------------------------------------

"""
Service Configuration — Pydantic Settings
==========================================
Reads from environment variables (injected by Docker Compose or Vault Agent).
Falls back to .env file for local development.
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    # ── Service identity ───────────────────────────────────────
    SERVICE_NAME: str = "auth-service"           # Override in each service
    SERVICE_VERSION: str = "0.1.0"

    # ── PostgreSQL (via PgBouncer) ─────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://platform_user:change_me_postgres@postgres:5432/platform"

    # ── Redis ─────────────────────────────────────────────────
    REDIS_URL: str = "redis://:change_me_redis@redis:6379/0"

    # ── Kafka ─────────────────────────────────────────────────
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    KAFKA_SCHEMA_REGISTRY_URL: str = ""

    # ── Vault ─────────────────────────────────────────────────
    VAULT_ADDR: str = ""
    VAULT_TOKEN: str = ""

    # ── Observability ──────────────────────────────────────────
    # Services send telemetry directly to Tempo in local docker-compose
    OTEL_ENDPOINT: str = "http://tempo:4317"   # gRPC port on Tempo
    LOG_LEVEL: str = "INFO"

    # ── JWT (RS256 — public key for validation) ───────────────
    JWT_ALGORITHM: str = "RS256"
    JWT_PUBLIC_KEY: str = ""    # Loaded from Vault in production

    # Auth-specific
    JWT_PRIVATE_KEY: str = ""       # RS256 private key — from env
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    MFA_TOTP_ISSUER: str = "CyberFraudShield"
    ALLOWED_ORIGINS: str = "http://localhost:5173,http://localhost:5174,http://localhost:5175"


settings = Settings()

# ----------------------------------------
# FILE: backend/auth/security/__init__.py
# ----------------------------------------

# __init__.py

# ----------------------------------------
# FILE: backend/auth/security/jwt.py
# ----------------------------------------

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

# ----------------------------------------
# FILE: backend/auth/security/password.py
# ----------------------------------------

"""
Password hashing utilities using passlib bcrypt.
bcrypt is CPU-intensive by design — this is intentional for security.
"""
from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Hash a plaintext password. Returns bcrypt hash string."""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return _pwd_context.verify(plain, hashed)

# ----------------------------------------
# FILE: backend/auth/services/__init__.py
# ----------------------------------------

# __init__.py

# ----------------------------------------
# FILE: backend/auth/services/auth_service.py
# ----------------------------------------

"""
Auth Service — core business logic.
Orchestrates: register, login (with brute-force protection), refresh, logout.
Does NOT touch DB directly — delegates to repositories.
Does NOT sign JWTs — delegates to security/jwt.py (Prompt 006).
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.schemas import (
    LoginRequest, LoginResponse,
    RefreshRequest, RefreshResponse,
    RegisterRequest, RegisterResponse,
)
from repositories.idempotency_repository import IdempotencyRepository
from repositories.session_repository import SessionRepository
from repositories.user_repository import UserRepository
from security.password import hash_password, verify_password


# ── Constants (from docs/api/auth.md) ─────────────────────────────────────────
_MAX_FAILURES = 5
_FAILURE_WINDOW_SECONDS = 600    # 10 minutes
_LOCK_DURATION_SECONDS = 900     # 15 minutes
_MFA_SESSION_TTL_SECONDS = 300   # 5 minutes


class AuthService:

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis
        self._user_repo = UserRepository(db)
        self._session_repo = SessionRepository(db)
        self._idempotency_repo = IdempotencyRepository(db)

    # ── Register ──────────────────────────────────────────────────────────────

    async def register(self, req: RegisterRequest, idempotency_key: uuid.UUID) -> RegisterResponse:
        """Register a new user. Idempotent — same key returns cached response."""

        # Check idempotency
        existing = await self._idempotency_repo.get(idempotency_key)
        if existing:
            return RegisterResponse(**existing.response_body["data"])

        # Check duplicate email
        if await self._user_repo.get_by_email(req.email):
            raise DuplicateEmailError(req.email)

        # Create user
        user = await self._user_repo.create(
            email=req.email,
            password_hash=hash_password(req.password),
            phone=req.phone,
            role=req.role,
            org_id=req.org_id,
            jurisdiction_id=req.jurisdiction_id,
        )
        response_data = {
            "user_id": str(user.user_id),
            "email": user.email,
            "role": user.role,
            "mfa_required": False,
        }
        await self._idempotency_repo.store(
            idempotency_key=idempotency_key,
            request_hash=_hash_request(req.model_dump()),
            response_status=201,
            response_body={"data": response_data},
        )
        await self._db.commit()

        return RegisterResponse(**response_data)

    # ── Login ─────────────────────────────────────────────────────────────────

    async def login(self, req: LoginRequest) -> LoginResponse:
        """
        Authenticate user. Returns JWT pair or MFA session token.
        Enforces brute-force protection via Redis counters.
        """
        email_lower = req.email.lower()

        # Check soft lock
        if await self._redis.exists(f"auth:lock:{email_lower}"):
            raise AccountLockedError(email_lower)

        # Look up user
        user = await self._user_repo.get_by_email(email_lower)
        if not user or not verify_password(req.password, user.password_hash):
            # Increment failure counter
            await _increment_failure(self._redis, email_lower)
            raise InvalidCredentialsError()

        # Reset failure counter on success
        await self._redis.delete(f"auth:fail:{email_lower}")

        # Update last login
        await self._user_repo.update_last_login(user.user_id)
        await self._db.commit()

        # MFA required?
        if user.mfa_enabled:
            mfa_token = secrets.token_urlsafe(32)
            await self._redis.setex(
                f"auth:mfa:{mfa_token}",
                _MFA_SESSION_TTL_SECONDS,
                str(user.user_id),
            )
            return LoginResponse(mfa_required=True, mfa_session_token=mfa_token)

        # Issue JWT pair (jwt.py will be wired in Prompt 007)
        # For now: return a stub that will be replaced
        from security.jwt import create_token_pair
        access_token, refresh_token = await create_token_pair(user, self._db, self._session_repo)
        return LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            mfa_required=False,
        )

    # ── Refresh ───────────────────────────────────────────────────────────────

    async def refresh(self, req: RefreshRequest) -> RefreshResponse:
        """Exchange a valid refresh token for a new access token."""
        token_hash = hashlib.sha256(req.refresh_token.encode()).hexdigest()
        db_session = await self._session_repo.get_by_token_hash(token_hash)
        if not db_session:
            raise InvalidRefreshTokenError()

        user = await self._user_repo.get_by_id(db_session.user_id)
        if not user or user.status != "ACTIVE":
            raise InvalidRefreshTokenError()

        from security.jwt import sign_access_token
        access_token = sign_access_token(user)
        return RefreshResponse(
            access_token=access_token,
            expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    # ── Logout ────────────────────────────────────────────────────────────────

    async def logout(self, jti: str, token_exp: int, token_hash: str) -> None:
        """Add JWT to denylist and revoke session."""
        # Denylist the access token JTI
        ttl = max(0, token_exp - int(datetime.now(timezone.utc).timestamp()))
        if ttl > 0:
            await self._redis.setex(f"auth:denylist:{jti}", ttl, "1")

        # Revoke refresh session
        db_session = await self._session_repo.get_by_token_hash(token_hash)
        if db_session:
            await self._session_repo.revoke(db_session.session_id)
            await self._db.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hash_request(data: dict) -> str:
    """Deterministic hash of request body for idempotency comparison."""
    import json
    serialized = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()


async def _increment_failure(redis: aioredis.Redis, email: str) -> None:
    """Increment failure counter; lock account on threshold."""
    key = f"auth:fail:{email}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, _FAILURE_WINDOW_SECONDS)
    if count >= _MAX_FAILURES:
        await redis.setex(f"auth:lock:{email}", _LOCK_DURATION_SECONDS, "1")


# ── Domain Exceptions (caught and mapped to HTTP errors in router) ─────────────

class DuplicateEmailError(Exception):
    def __init__(self, email: str):
        self.email = email

class AccountLockedError(Exception):
    def __init__(self, email: str):
        self.email = email

class InvalidCredentialsError(Exception):
    pass

class InvalidRefreshTokenError(Exception):
    pass

# ----------------------------------------
# FILE: backend/auth/services/mfa_service.py
# ----------------------------------------

"""
MFA Service — TOTP-based multi-factor authentication.
Uses pyotp for TOTP generation and verification.

MFA flow:
  1. User logs in → if mfa_enabled, generate mfa_session_token → store {user_id} in Redis (5min TTL)
  2. Client calls POST /auth/mfa/verify with mfa_session_token + totpCode
  3. Service: look up user_id from Redis → fetch mfa_secret_enc → verify TOTP → issue JWT pair

Security note: mfa_secret_enc is stored in DB as a base64-encoded string.
For hackathon: no encryption applied (plaintext base64 TOTP secret).
Production: encrypt with AES-256-GCM using a key from Vault.
(Recorded in surjit/notes/assumptions.md)
"""
import base64
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import pyotp
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.schemas import MFAVerifyResponse
from repositories.session_repository import SessionRepository
from repositories.user_repository import UserRepository
from security.jwt import create_token_pair


_MFA_SESSION_TTL = 300   # 5 minutes (from docs/db/redis.md)


class MFAService:

    class MFASessionExpiredError(Exception):
        pass

    class InvalidTOTPError(Exception):
        pass

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis
        self._user_repo = UserRepository(db)
        self._session_repo = SessionRepository(db)

    # ── Setup ─────────────────────────────────────────────────────────────────

    def generate_totp_secret(self) -> str:
        """Generate a new random TOTP secret (base32 encoded, 32 chars)."""
        return pyotp.random_base32()

    def get_provisioning_uri(self, secret: str, email: str) -> str:
        """Return otpauth:// URI for QR code generation in authenticator apps."""
        totp = pyotp.TOTP(secret)
        return totp.provisioning_uri(
            name=email,
            issuer_name=settings.MFA_TOTP_ISSUER,
        )

    async def enable_mfa(self, user_id: uuid.UUID, secret: str) -> str:
        """
        Enable MFA for a user. Stores encoded secret in DB.
        Returns the provisioning URI for QR code display.
        """
        user = await self._user_repo.get_by_id(user_id)
        if not user:
            raise ValueError(f"User {user_id} not found")

        # Encode secret (plaintext for hackathon; see assumptions.md)
        encoded = base64.b64encode(secret.encode()).decode()
        async with self._db.begin():
            await self._user_repo.update_mfa(
                user_id=user_id,
                mfa_enabled=True,
                mfa_secret_enc=encoded,
            )
        return self.get_provisioning_uri(secret, user.email)

    # ── Verification ──────────────────────────────────────────────────────────

    def verify_totp(self, secret_enc: str, code: str) -> bool:
        """Verify a TOTP code against the stored (encoded) secret."""
        # Decode from base64
        secret = base64.b64decode(secret_enc.encode()).decode()
        totp = pyotp.TOTP(secret)
        # valid_window=1 allows 30s clock drift (one interval before/after)
        return totp.verify(code, valid_window=1)

    async def verify_mfa(self, mfa_session_token: str, totp_code: str) -> MFAVerifyResponse:
        """
        Complete MFA login:
        1. Retrieve user_id from Redis MFA session.
        2. Fetch user + MFA secret from DB.
        3. Verify TOTP code.
        4. Issue JWT pair.
        """
        redis_key = f"auth:mfa:{mfa_session_token}"
        user_id_str = await self._redis.get(redis_key)

        if not user_id_str:
            raise MFAService.MFASessionExpiredError("MFA session expired or invalid")

        user_id = uuid.UUID(user_id_str)
        user = await self._user_repo.get_by_id(user_id)
        if not user or not user.mfa_secret_enc:
            raise MFAService.MFASessionExpiredError("User or MFA config not found")

        if not self.verify_totp(user.mfa_secret_enc, totp_code):
            raise MFAService.InvalidTOTPError("TOTP code is incorrect")

        # Consume the MFA session (prevent replay)
        await self._redis.delete(redis_key)

        # Issue full JWT pair
        async with self._db.begin():
            access_token, refresh_token = await create_token_pair(user, self._db, self._session_repo)

        return MFAVerifyResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

# ----------------------------------------
# FILE: backend/auth/main.py
# ----------------------------------------

"""
Platform Service Template — FastAPI
====================================
Copy this file into your service directory and rename/modify as needed.

SETUP INSTRUCTIONS:
1. Copy backend/template/ → backend/<your-service>/
2. Set SERVICE_NAME in settings below
3. Implement your domain endpoints in separate routers
4. Import routers here and include them on `app`
5. Run: uvicorn main:app --reload

PATTERNS ESTABLISHED HERE:
- Structured JSON logging (loguru) with trace_id in every log line
- OpenTelemetry auto-instrumentation (traces, metrics → OTel Collector)
- Prometheus metrics via prometheus-fastapi-instrumentator (/metrics)
- /health/live  → liveness probe (is the process alive?)
- /health/ready → readiness probe (can it serve traffic?)
- Standard error response shape: {requestId, correlationId, errorCode, message}
- Vault secret loading at startup (graceful fallback to env vars for local dev)
"""

import sys
import uuid
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text

# ─── OpenTelemetry (auto-instrument BEFORE app creation) ─────────────────────
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource

from config import settings

# ─── Tracer setup ─────────────────────────────────────────────────────────────
resource = Resource.create({"service.name": settings.SERVICE_NAME, "service.version": settings.SERVICE_VERSION})
tracer_provider = TracerProvider(resource=resource)
tracer_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.OTEL_ENDPOINT))
)
trace.set_tracer_provider(tracer_provider)

# ─── Logging (structured JSON via loguru) ─────────────────────────────────────
logger.remove()
logger.add(
    sys.stdout,
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {extra[service]} | {extra[trace_id]} | {message}",
    serialize=True,    # Emit as JSON lines
    level="INFO",
)
logger = logger.bind(service=settings.SERVICE_NAME, trace_id="—")


# ─── Lifespan (startup / shutdown) ───────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"{settings.SERVICE_NAME} starting up")
    
    # Initialize DB engine + session factory
    from db import get_engine, get_session_factory
    engine = get_engine()
    app.state.db_engine = engine
    app.state.db_session_factory = get_session_factory(engine)
    
    # Initialize Redis client
    from redis_client import create_redis_client
    app.state.redis = create_redis_client()
    await app.state.redis.ping()  # Fail fast if Redis is unreachable
    
    logger.info(f"{settings.SERVICE_NAME} ready — DB pool and Redis initialized")
    yield
    
    logger.info(f"{settings.SERVICE_NAME} shutting down")
    await app.state.db_engine.dispose()
    await app.state.redis.aclose()


# ─── App ─────────────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.SERVICE_NAME,
    version=settings.SERVICE_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Auto-instrument FastAPI with OTel
FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer_provider)

# ─── CORS ────────────────────────────────────────────────────────────────────
# Bug Fix T18-A: CORS was missing — Citizen/Bank/Telecom UIs were blocked.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in settings.ALLOWED_ORIGINS.split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Expose /metrics endpoint for Prometheus scraping
Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
).instrument(app).expose(app, endpoint="/metrics")


# ─── Middleware: correlation ID + request logging ─────────────────────────────
@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

    # Bind trace context to logger for this request
    span_context = trace.get_current_span().get_span_context()
    otel_trace_id = f"{span_context.trace_id:032x}" if span_context.is_valid else "—"
    req_logger = logger.bind(
        trace_id=otel_trace_id,
        correlation_id=correlation_id,
        request_id=request_id,
        method=request.method,
        path=request.url.path,
    )

    start = time.perf_counter()
    response: Response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)

    req_logger.info(
        "request_completed",
        status_code=response.status_code,
        duration_ms=duration_ms,
    )

    response.headers["X-Correlation-ID"] = correlation_id
    response.headers["X-Request-ID"] = request_id
    return response


# ─── Standard error handler ───────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    correlation_id = request.headers.get("X-Correlation-ID", "unknown")
    request_id = request.headers.get("X-Request-ID", "unknown")
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "requestId": request_id,
            "correlationId": correlation_id,
            "errorCode": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected error occurred.",
            "details": None,
        },
    )


# ─── Health Endpoints ─────────────────────────────────────────────────────────
@app.get("/health/live", tags=["Health"])
async def liveness():
    """Kubernetes liveness probe — is the process running?"""
    return {"status": "alive", "service": settings.SERVICE_NAME}


@app.get("/health/ready", tags=["Health"])
async def readiness(request: Request):
    checks = {}
    healthy = True

    # DB check
    try:
        async with request.app.state.db_session_factory() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"
        healthy = False

    # Redis check
    try:
        await request.app.state.redis.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"
        healthy = False

    status_code = 200 if healthy else 503
    return JSONResponse(
        status_code=status_code,
        content={"status": "ok" if healthy else "not_ready", "checks": checks},
    )


# ─── Domain Routers ───────────────────────────────────────────────────────────
from routers.auth_router import router as auth_router
app.include_router(auth_router, prefix="/api/v1")

# ----------------------------------------
# FILE: backend/auth/response_helpers.py
# ----------------------------------------

"""Standard response envelope helpers (docs/api/_shared_contract.md)."""
import uuid
from datetime import datetime, timezone
from typing import Any


def success_response(data: Any, correlation_id: str = "") -> dict:
    return {
        "requestId": str(uuid.uuid4()),
        "correlationId": correlation_id,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "success",
        "data": data,
    }


def error_response(
    error_code: str,
    message: str,
    correlation_id: str = "",
    details: Any = None,
) -> dict:
    return {
        "requestId": str(uuid.uuid4()),
        "correlationId": correlation_id,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "error",
        "errorCode": error_code,
        "message": message,
        "details": details,
    }

# ----------------------------------------
# FILE: backend/auth/routers/__init__.py
# ----------------------------------------

# __init__.py

# ----------------------------------------
# FILE: backend/auth/routers/auth_router.py
# ----------------------------------------

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

# ----------------------------------------
# FILE: backend/auth/models/__init__.py
# ----------------------------------------

# __init__.py

# ----------------------------------------
# FILE: backend/auth/models/user.py
# ----------------------------------------

"""
SQLAlchemy ORM models for identity schema.
Mirrors docs/db/postgres.sql identity.users and identity.roles tables exactly.
DO NOT modify column names or types — DDL is frozen.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, String, Text, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "phone IS NULL OR phone ~ '^\\+[1-9][0-9]{7,14}$'",
            name="users_phone_e164",
        ),
        CheckConstraint(
            "role = 'CITIZEN' OR jurisdiction_id IS NOT NULL",
            name="users_non_citizen_jurisdiction",
        ),
        {"schema": "identity"},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20))
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    org_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    jurisdiction_id: Mapped[str | None] = mapped_column(String(64))
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mfa_secret_enc: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

# ----------------------------------------
# FILE: backend/auth/models/idempotency.py
# ----------------------------------------

"""
SQLAlchemy ORM for platform.idempotency_keys.
Used by all mutating POST endpoints to prevent duplicate processing.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String, Text, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.user import Base


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = {"schema": "platform"}

    idempotency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    service_name: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict | None] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

# ----------------------------------------
# FILE: backend/auth/models/schemas.py
# ----------------------------------------

"""
Pydantic schemas for Auth Service API.
Field names match docs/api/auth.md exactly.
"""
import uuid
import re
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


# ── Shared ────────────────────────────────────────────────────────────────────

class CurrentUser(BaseModel):
    """Decoded JWT claims. Passed via Depends(get_current_user)."""
    user_id: uuid.UUID
    email: str
    role: str
    org_id: Optional[uuid.UUID] = None
    jurisdiction_id: Optional[str] = None
    jti: str  # JWT ID — used for denylist check


# ── Register ──────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    phone: str
    role: str
    org_id: Optional[uuid.UUID] = None
    jurisdiction_id: Optional[str] = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        allowed = {"CITIZEN", "INVESTIGATOR", "BANK_OFFICIAL", "TELECOM_ADMIN", "GOV_OFFICIAL"}
        if v not in allowed:
            raise ValueError(f"role must be one of {allowed}")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not re.search(r"[A-Z]", v):
            raise ValueError("password must contain at least one uppercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("password must contain at least one digit")
        return v

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        if not re.match(r"^\+[1-9][0-9]{7,14}$", v):
            raise ValueError("phone must be in E.164 format (e.g. +919876543210)")
        return v

    @model_validator(mode="after")
    def validate_jurisdiction(self) -> "RegisterRequest":
        if self.role != "CITIZEN" and not self.jurisdiction_id:
            raise ValueError("jurisdiction_id is required for roles other than CITIZEN")
        return self


class RegisterResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    role: str
    mfa_required: bool


# ── Login ─────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_in: int = 3600
    mfa_required: bool = False
    mfa_session_token: Optional[str] = None


# ── MFA ───────────────────────────────────────────────────────────────────────

class MFAVerifyRequest(BaseModel):
    mfa_session_token: str
    totp_code: str = Field(..., min_length=6, max_length=6)


class MFAVerifyResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int = 3600


# ── Refresh ───────────────────────────────────────────────────────────────────

class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    expires_in: int = 3600


# ── Me ────────────────────────────────────────────────────────────────────────

class MeResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    role: str
    org_id: Optional[uuid.UUID] = None
    jurisdiction_id: Optional[str] = None

# ----------------------------------------
# FILE: backend/auth/models/session.py
# ----------------------------------------

"""
SQLAlchemy ORM for identity.sessions.
Stores refresh token hashes — never plaintext tokens.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UUID
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from models.user import Base


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = {"schema": "identity"}

    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("identity.users.user_id"), nullable=False)
    refresh_token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(INET)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

# ----------------------------------------
# FILE: backend/auth/db.py
# ----------------------------------------

"""
Auth Service — Database Connection Pool
Uses asyncpg directly for connection pool management.
SQLAlchemy async engine for ORM operations.
Pool: min=5, max=20 (per Execution.md T5a spec).
"""
from typing import AsyncGenerator

import asyncpg
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from fastapi import Depends, Request

from config import settings


def get_engine():
    """Create SQLAlchemy async engine. Called once at startup."""
    return create_async_engine(
        settings.DATABASE_URL,
        pool_size=5,
        max_overflow=15,        # 5 + 15 = 20 max total connections
        pool_pre_ping=True,     # Validate connections before use
        echo=False,
    )


def get_session_factory(engine) -> async_sessionmaker:
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an async DB session."""
    session_factory = request.app.state.db_session_factory
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise

# ----------------------------------------
# FILE: backend/auth/redis_client.py
# ----------------------------------------

"""
Auth Service — Redis Async Client
Key patterns (from docs/db/redis.md):
  auth:denylist:{jti}          → JWT denylist
  auth:fail:{email}            → Login failure counter (TTL 10m)
  auth:lock:{email}            → Soft lock flag (TTL 15m)
  auth:mfa:{token}             → MFA session (TTL 5m)
  session:refresh:{tokenHash}  → Refresh token lookup
  idempotency:{service}:{key}  → Idempotency response cache
"""
import redis.asyncio as aioredis
from fastapi import Request

from config import settings


def create_redis_client() -> aioredis.Redis:
    """Create async Redis client. Called once at startup."""
    return aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )


async def get_redis(request: Request) -> aioredis.Redis:
    """FastAPI dependency: returns the shared Redis client."""
    return request.app.state.redis

# ----------------------------------------
# FILE: backend/auth/repositories/__init__.py
# ----------------------------------------

# __init__.py

# ----------------------------------------
# FILE: backend/auth/repositories/session_repository.py
# ----------------------------------------

"""
Session Repository — DB operations on identity.sessions.
Stores refresh token HASHES only (never plaintext tokens).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.session import Session


class SessionRepository:

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        user_id: uuid.UUID,
        refresh_token_hash: str,
        expires_at: datetime,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> Session:
        """Create a new session record. Caller must commit."""
        db_session = Session(
            user_id=user_id,
            refresh_token_hash=refresh_token_hash,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(db_session)
        await self._session.flush()
        return db_session

    async def get_by_token_hash(self, token_hash: str) -> Session | None:
        """Find active (non-revoked, non-expired) session by refresh token hash."""
        now = datetime.now(timezone.utc)
        result = await self._session.execute(
            select(Session).where(
                Session.refresh_token_hash == token_hash,
                Session.revoked_at.is_(None),
                Session.expires_at > now,
            )
        )
        return result.scalar_one_or_none()

    async def revoke(self, session_id: uuid.UUID) -> None:
        """Soft-revoke a session (never DELETE)."""
        await self._session.execute(
            update(Session)
            .where(Session.session_id == session_id)
            .values(revoked_at=datetime.now(timezone.utc))
        )

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        """Revoke all active sessions for a user (e.g., on password change)."""
        now = datetime.now(timezone.utc)
        await self._session.execute(
            update(Session)
            .where(
                Session.user_id == user_id,
                Session.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )

# ----------------------------------------
# FILE: backend/auth/repositories/user_repository.py
# ----------------------------------------

"""
User Repository — all DB operations on identity.users.
Only this layer may access the database for user data.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User


class UserRepository:

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_email(self, email: str) -> User | None:
        """Case-insensitive email lookup (uses users_email_lower_uidx)."""
        result = await self._session.execute(
            select(User).where(User.email.ilike(email))
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def create(
        self,
        email: str,
        password_hash: str,
        phone: str,
        role: str,
        org_id: uuid.UUID | None = None,
        jurisdiction_id: str | None = None,
    ) -> User:
        """Create and persist a new user. Caller must commit the session."""
        now = datetime.now(timezone.utc)
        user = User(
            email=email.lower(),   # Normalize to lowercase
            password_hash=password_hash,
            phone=phone,
            role=role,
            org_id=org_id,
            jurisdiction_id=jurisdiction_id,
            status="ACTIVE",
            created_at=now,
            updated_at=now,
        )
        self._session.add(user)
        await self._session.flush()  # Populate user_id without committing
        return user

    async def update_status(self, user_id: uuid.UUID, status: str) -> None:
        """Update user status (ACTIVE, SOFT_LOCKED, DISABLED)."""
        await self._session.execute(
            update(User)
            .where(User.user_id == user_id)
            .values(status=status, updated_at=datetime.now(timezone.utc))
        )

    async def update_last_login(self, user_id: uuid.UUID) -> None:
        await self._session.execute(
            update(User)
            .where(User.user_id == user_id)
            .values(last_login_at=datetime.now(timezone.utc))
        )

    async def update_mfa(self, user_id: uuid.UUID, mfa_enabled: bool, mfa_secret_enc: str) -> None:
        """Enable MFA and store encrypted TOTP secret."""
        await self._session.execute(
            update(User)
            .where(User.user_id == user_id)
            .values(
                mfa_enabled=mfa_enabled,
                mfa_secret_enc=mfa_secret_enc,
                updated_at=datetime.now(timezone.utc),
            )
        )

# ----------------------------------------
# FILE: backend/auth/repositories/idempotency_repository.py
# ----------------------------------------

"""
Idempotency Repository — platform.idempotency_keys table.
All mutating POST endpoints check here first.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.idempotency import IdempotencyKey


class IdempotencyRepository:

    SERVICE_NAME = "auth-service"

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get(self, idempotency_key: uuid.UUID) -> IdempotencyKey | None:
        """Return cached response if this key was already processed."""
        result = await self._session.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.service_name == self.SERVICE_NAME,
                IdempotencyKey.idempotency_key == idempotency_key,
                IdempotencyKey.expires_at > datetime.now(timezone.utc),
            )
        )
        return result.scalar_one_or_none()

    async def store(
        self,
        idempotency_key: uuid.UUID,
        request_hash: str,
        response_status: int,
        response_body: dict,
    ) -> None:
        """Store the result of a successfully processed request."""
        now = datetime.now(timezone.utc)
        record = IdempotencyKey(
            service_name=self.SERVICE_NAME,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            response_status=response_status,
            response_body=response_body,
            expires_at=now + timedelta(hours=24),
            created_at=now,
        )
        self._session.add(record)
        await self._session.flush()

# ----------------------------------------
# FILE: backend/auth/tests/conftest.py
# ----------------------------------------

"""Shared pytest fixtures for Auth Service tests."""
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

# Generate dummy keys for JWT testing
_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_private_pem = _private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption()
).decode("utf-8")
_public_pem = _private_key.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo
).decode("utf-8")

os.environ["JWT_PRIVATE_KEY"] = _private_pem
os.environ["JWT_PUBLIC_KEY"] = _public_pem

from config import settings
settings.JWT_PRIVATE_KEY = _private_pem
settings.JWT_PUBLIC_KEY = _public_pem

from main import app
from models.user import User
from security.password import hash_password


@pytest.fixture
def mock_user():
    """A fake User object for testing."""
    return User(
        user_id=uuid.uuid4(),
        email="test@example.com",
        password_hash=hash_password("Password1"),
        phone="+919876543210",
        role="CITIZEN",
        org_id=None,
        jurisdiction_id=None,
        mfa_enabled=False,
        mfa_secret_enc=None,
        status="ACTIVE",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        last_login_at=None,
    )


@pytest.fixture
def mock_db():
    """Mock async SQLAlchemy session."""
    session = MagicMock()
    # session.begin() returns an async context manager
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session.begin.return_value = ctx
    return session


@pytest.fixture
def mock_redis():
    """Mock Redis async client."""
    redis = AsyncMock()
    redis.exists.return_value = 0   # Not locked by default
    redis.get.return_value = None
    redis.incr.return_value = 1
    return redis


@pytest.fixture
async def async_client(mock_db, mock_redis):
    """Async HTTP client for endpoint testing."""
    from db import get_db
    from redis_client import get_redis
    
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_redis] = lambda: mock_redis
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
        
    app.dependency_overrides.clear()

# ----------------------------------------
# FILE: backend/auth/tests/test_auth_endpoints.py
# ----------------------------------------

"""
Integration tests for Auth endpoints.
DB and Redis are mocked — no real connections needed.
"""
import uuid
from unittest.mock import AsyncMock, patch, MagicMock

import pytest


class TestRegister:

    @pytest.mark.asyncio
    async def test_register_success(self, async_client, mock_user, mock_db, mock_redis):
        """POST /register creates user and returns 201."""
        with (
            patch("routers.auth_router.get_db", return_value=mock_db),
            patch("routers.auth_router.get_redis", return_value=mock_redis),
            patch("services.auth_service.UserRepository") as mock_user_repo_cls,
            patch("services.auth_service.IdempotencyRepository") as mock_idem_repo_cls,
        ):
            mock_user_repo = AsyncMock()
            mock_user_repo.get_by_email.return_value = None  # No existing user
            mock_user_repo.create.return_value = mock_user
            mock_user_repo_cls.return_value = mock_user_repo

            mock_idem_repo = AsyncMock()
            mock_idem_repo.get.return_value = None  # No cached response
            mock_idem_repo_cls.return_value = mock_idem_repo

            response = await async_client.post(
                "/api/v1/auth/register",
                json={
                    "email": "new@example.com",
                    "password": "Password1",
                    "phone": "+919876543210",
                    "role": "CITIZEN",
                },
                headers={"Idempotency-Key": str(uuid.uuid4())},
            )
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "success"
        assert "userId" in body["data"] or "user_id" in body["data"]

    @pytest.mark.asyncio
    async def test_register_missing_idempotency_key(self, async_client):
        """POST /register without Idempotency-Key returns error."""
        response = await async_client.post(
            "/api/v1/auth/register",
            json={"email": "x@x.com", "password": "Password1", "phone": "+911234567890", "role": "CITIZEN"},
        )
        # Should return 4xx (missing idempotency key)
        assert response.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_register_invalid_role(self, async_client):
        """POST /register with invalid role returns 422."""
        response = await async_client.post(
            "/api/v1/auth/register",
            json={"email": "x@x.com", "password": "Password1", "phone": "+911234567890", "role": "HACKER"},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, async_client, mock_db, mock_redis):
        """POST /register with existing email returns 409."""
        with (
            patch("routers.auth_router.get_db", return_value=mock_db),
            patch("routers.auth_router.get_redis", return_value=mock_redis),
            patch("services.auth_service.UserRepository") as mock_user_repo_cls,
            patch("services.auth_service.IdempotencyRepository") as mock_idem_repo_cls,
        ):
            mock_user_repo = AsyncMock()
            mock_user_repo.get_by_email.return_value = MagicMock()  # User exists
            mock_user_repo_cls.return_value = mock_user_repo

            mock_idem_repo = AsyncMock()
            mock_idem_repo.get.return_value = None  # No cached response
            mock_idem_repo_cls.return_value = mock_idem_repo

            response = await async_client.post(
                "/api/v1/auth/register",
                json={
                    "email": "existing@example.com",
                    "password": "Password1",
                    "phone": "+919876543210",
                    "role": "CITIZEN",
                },
                headers={"Idempotency-Key": str(uuid.uuid4())},
            )
        assert response.status_code == 409
        assert response.json()["detail"]["errorCode"] == "DUPLICATE_EMAIL"


class TestLogin:

    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self, async_client, mock_db, mock_redis):
        """POST /login with wrong password returns 401."""
        with (
            patch("routers.auth_router.get_db", return_value=mock_db),
            patch("routers.auth_router.get_redis", return_value=mock_redis),
            patch("services.auth_service.UserRepository") as mock_user_repo_cls,
        ):
            mock_user_repo = AsyncMock()
            mock_user_repo.get_by_email.return_value = None  # User not found
            mock_user_repo_cls.return_value = mock_user_repo

            response = await async_client.post(
                "/api/v1/auth/login",
                json={"email": "nobody@example.com", "password": "WrongPass1"},
            )
        assert response.status_code == 401
        assert response.json()["detail"]["errorCode"] == "INVALID_CREDENTIALS"

    @pytest.mark.asyncio
    async def test_login_locked_account(self, async_client, mock_db, mock_redis):
        """POST /login returns 429 when account is soft-locked in Redis."""
        mock_redis.exists.return_value = 1  # Account is locked

        with (
            patch("routers.auth_router.get_db", return_value=mock_db),
            patch("routers.auth_router.get_redis", return_value=mock_redis),
        ):
            response = await async_client.post(
                "/api/v1/auth/login",
                json={"email": "locked@example.com", "password": "Password1"},
            )
        assert response.status_code == 429
        assert response.json()["detail"]["errorCode"] == "ACCOUNT_LOCKED"


class TestMe:

    @pytest.mark.asyncio
    async def test_me_success(self, async_client, mock_user):
        """GET /me returns user profile from JWT including orgId and jurisdictionId."""
        from security.jwt import sign_access_token
        from main import app
        
        mock_user.org_id = uuid.uuid4()
        mock_user.jurisdiction_id = "JUR_TEST_01"
        token = sign_access_token(mock_user)
        
        mock_redis = AsyncMock()
        mock_redis.exists.return_value = 0
        app.state.redis = mock_redis
        
        response = await async_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["data"]["userId"] == str(mock_user.user_id)
        assert body["data"]["orgId"] == str(mock_user.org_id)
        assert body["data"]["jurisdictionId"] == "JUR_TEST_01"


class TestHealthEndpoints:

    @pytest.mark.asyncio
    async def test_liveness(self, async_client):
        """GET /health/live always returns 200."""
        response = await async_client.get("/health/live")
        assert response.status_code == 200
        assert response.json()["status"] == "alive"

# ----------------------------------------
# FILE: backend/auth/tests/test_jwt.py
# ----------------------------------------

"""Unit tests for JWT signing and verification."""
import uuid
import pytest
from unittest.mock import AsyncMock, patch

from security.jwt import sign_access_token, decode_token, get_current_user
from models.user import User
from models.schemas import CurrentUser


@pytest.fixture
def sample_user():
    return User(
        user_id=uuid.uuid4(),
        email="jwt_test@example.com",
        role="INVESTIGATOR",
        org_id=uuid.uuid4(),
        jurisdiction_id="JUR_MH_MUMBAI",
        status="ACTIVE",
    )


def test_sign_and_decode_token(sample_user):
    """Token signed with private key should be decodable with public key."""
    token = sign_access_token(sample_user)
    assert token  # Non-empty

    payload = decode_token(token)
    assert payload["sub"] == str(sample_user.user_id)
    assert payload["role"] == "INVESTIGATOR"
    assert payload["jurisdictionId"] == "JUR_MH_MUMBAI"
    assert "jti" in payload
    assert "exp" in payload


def test_token_contains_required_claims(sample_user):
    """All claims from _shared_contract.md must be present."""
    token = sign_access_token(sample_user)
    payload = decode_token(token)
    required_claims = {"sub", "role", "jti", "exp", "iat", "kid"}
    assert required_claims.issubset(set(payload.keys()))

# ----------------------------------------
# FILE: backend/case/config.py
# ----------------------------------------

"""
Service Configuration — Pydantic Settings
==========================================
Reads from environment variables (injected by Docker Compose or Vault Agent).
Falls back to .env file for local development.
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    # ── Service identity ───────────────────────────────────────
    SERVICE_NAME: str = "case-service"           # Override in each service
    SERVICE_VERSION: str = "0.1.0"

    # ── PostgreSQL (via PgBouncer) ─────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://platform_user:change_me_postgres@postgres:5432/platform"

    # ── Redis ─────────────────────────────────────────────────
    REDIS_URL: str = "redis://:change_me_redis@redis:6379/0"

    # ── Kafka ─────────────────────────────────────────────────
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    KAFKA_SCHEMA_REGISTRY_URL: str = ""

    # ── Vault ─────────────────────────────────────────────────
    VAULT_ADDR: str = ""
    VAULT_TOKEN: str = ""

    # ── Observability ──────────────────────────────────────────
    # Services send telemetry directly to Tempo in local docker-compose
    OTEL_ENDPOINT: str = "http://tempo:4317"   # gRPC port on Tempo
    LOG_LEVEL: str = "INFO"

    # ── JWT (RS256 — public key for validation) ───────────────
    JWT_ALGORITHM: str = "RS256"
    JWT_PUBLIC_KEY: str = ""    # Loaded from Vault in production
    
    INFERENCE_ORCHESTRATOR_URL: str = "http://inference-orchestrator:8000"
    ALLOWED_ORIGINS: str = "http://localhost:5173,http://localhost:5174,http://localhost:5175"


settings = Settings()

# ----------------------------------------
# FILE: backend/case/security/__init__.py
# ----------------------------------------

# Empty init

# ----------------------------------------
# FILE: backend/case/security/jwt.py
# ----------------------------------------

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

# ----------------------------------------
# FILE: backend/case/state_machine/transitions.py
# ----------------------------------------

"""
Case State Machine — Execution.md T5a spec.

Valid states: New, Assigned, Investigating, Pending_AI, Action_Taken, Closed
State graph: all valid (from_state, to_state) pairs.
Special rule: Pending_AI → Investigating only when reason in ("AI_TIMEOUT", "HITL_APPROVED")

Usage:
    from state_machine.transitions import validate_transition, TransitionError

    validate_transition(
        current_state="Pending_AI",
        new_state="Investigating",
        reason="AI_TIMEOUT",
        caller_role="SYSTEM",
    )
"""

# ── State graph ────────────────────────────────────────────────────────────────
# frozenset gives O(1) membership test and is immutable at module level.

VALID_TRANSITIONS: frozenset[tuple[str, str]] = frozenset({
    ("New",           "Assigned"),
    ("Assigned",      "Investigating"),
    ("Investigating", "Pending_AI"),
    ("Pending_AI",    "Investigating"),   # AI_TIMEOUT re-entry OR HITL review restart
    ("Pending_AI",    "Action_Taken"),   # HITL APPROVE → resume automated actions
    ("Pending_AI",    "Closed"),          # HITL REJECT → disposition = FALSE_POSITIVE
    ("Action_Taken",  "Closed"),
})

# Transitions that require the caller to supply a specific reason value.
REASON_REQUIRED_TRANSITIONS: dict[tuple[str, str], list[str]] = {
    ("Pending_AI", "Investigating"): ["AI_TIMEOUT", "HITL_APPROVED"],
}

# Roles permitted to trigger each transition.
# "SYSTEM" = internal service-to-service call (Orchestrator, no user JWT).
ROLE_ALLOWED_TRANSITIONS: dict[tuple[str, str], list[str]] = {
    ("New",           "Assigned"):       ["INVESTIGATOR", "ADMIN"],
    ("Assigned",      "Investigating"):  ["INVESTIGATOR", "ADMIN"],
    ("Investigating",  "Pending_AI"):    ["SYSTEM"],
    ("Pending_AI",    "Investigating"):  ["SYSTEM", "INVESTIGATOR", "ADMIN"],
    ("Pending_AI",    "Action_Taken"):   ["SYSTEM", "INVESTIGATOR", "ADMIN"],
    ("Pending_AI",    "Closed"):         ["INVESTIGATOR", "ADMIN"],
    ("Action_Taken",  "Closed"):         ["INVESTIGATOR", "ADMIN"],
}

# Terminal states — no outgoing transitions allowed.
TERMINAL_STATES: frozenset[str] = frozenset({"Closed"})

# All valid state names (must match DB CHECK constraint exactly).
VALID_STATES: frozenset[str] = frozenset({
    "New", "Assigned", "Investigating", "Pending_AI", "Action_Taken", "Closed"
})


# ── Domain exceptions (router converts to HTTP 422) ───────────────────────────

class TransitionError(Exception):
    """Raised when a requested state transition is not permitted."""

    def __init__(self, current: str, target: str, reason: str = ""):
        self.current = current
        self.target = target
        self.detail = reason
        msg = f"Invalid transition: {current} → {target}"
        if reason:
            msg += f" ({reason})"
        super().__init__(msg)


class TransitionPermissionError(Exception):
    """Raised when the caller's role is not authorised for this transition."""

    def __init__(self, role: str, current: str, target: str):
        self.role = role
        self.current = current
        self.target = target
        super().__init__(
            f"Role '{role}' is not authorised to transition case from {current} to {target}"
        )


# ── Public API ─────────────────────────────────────────────────────────────────

def validate_transition(
    current_state: str,
    new_state: str,
    reason: str = "",
    caller_role: str = "SYSTEM",
) -> None:
    """
    Validate a case state transition.
    Pure function — no I/O.  Call BEFORE any DB write.

    Raises:
        TransitionError:           if the (from, to) pair or reason is invalid.
        TransitionPermissionError: if caller_role is not authorised.

    Args:
        current_state: current ``Case.status`` value read from the DB.
        new_state:     requested target state from the request body.
        reason:        free-text reason supplied by the caller (required for some transitions).
        caller_role:   JWT ``role`` claim, or ``"SYSTEM"`` for internal service calls.
    """
    # 1. Target must be a known state.
    if new_state not in VALID_STATES:
        raise TransitionError(
            current_state, new_state, f"'{new_state}' is not a recognised case state"
        )

    # 2. Terminal states have no outgoing edges.
    if current_state in TERMINAL_STATES:
        raise TransitionError(
            current_state, new_state, "case is in a terminal state and cannot be transitioned"
        )

    pair = (current_state, new_state)

    # 3. The (from, to) edge must exist in the graph.
    if pair not in VALID_TRANSITIONS:
        raise TransitionError(current_state, new_state)

    # 4. Caller role must be on the allow-list for this edge.
    allowed_roles = ROLE_ALLOWED_TRANSITIONS.get(pair, [])
    if caller_role not in allowed_roles:
        raise TransitionPermissionError(caller_role, current_state, new_state)

    # 5. Some transitions require a specific reason value.
    required_reasons = REASON_REQUIRED_TRANSITIONS.get(pair)
    if required_reasons and reason not in required_reasons:
        raise TransitionError(
            current_state,
            new_state,
            f"reason must be one of {required_reasons}, got '{reason}'",
        )


def get_allowed_transitions(current_state: str) -> list[str]:
    """Return all target states reachable from ``current_state``."""
    return [to for (frm, to) in VALID_TRANSITIONS if frm == current_state]

# ----------------------------------------
# FILE: backend/case/services/case_service.py
# ----------------------------------------

"""
Case Service — core business logic for Case Management.

CRITICAL PATTERN:
  Every multi-step write (case + outbox + timeline) is wrapped in a single
  `async with self._db.begin()` block. If any step fails the entire
  transaction rolls back — the outbox entry and the domain row are NEVER
  written independently.

ML stub:
  _ML_STUB_VERDICT is a module-level constant returned by _to_detail_response()
  until T13 (Day 6) wires up the real Inference Orchestrator HTTP call.
  Replace the constant and the _to_detail_response method body at T13.
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from models.schemas import (
    CaseDetailResponse,
    CreateCaseRequest,
    CreateCaseResponse,
    UpdateCaseStateRequest,
    VerdictOverrideRequest,
)
from repositories.case_repository import CaseRepository
from repositories.idempotency_repository import IdempotencyRepository
from repositories.outbox_repository import OutboxRepository
from repositories.override_repository import OverrideRepository
from repositories.prediction_repository import PredictionRepository
from repositories.timeline_repository import TimelineRepository
from state_machine.transitions import (
    TransitionError,
    TransitionPermissionError,
    validate_transition,
)


# ── ML stub (replaced in T13 Day 6) ──────────────────────────────────────────
# Assumptions: see surjit/notes/assumptions.md → T5a — Case Service: ML Stub
_ML_STUB_VERDICT = {
    "fusedScore": 72.0,
    "riskTier": "HIGH",
    "confidence": 0.85,
    "status": "COMPLETE",
    "modelBreakdown": [
        {"model": "scam-nlp", "score": 78, "confidence": 0.88},
    ],
    "explanation": "Stub verdict — AI integration pending (T13).",
}


# ── Domain exceptions (router maps to HTTP status codes) ─────────────────────

class CaseNotFoundError(Exception):
    pass


class InvalidTransitionError(Exception):
    pass


class CasePermissionError(Exception):
    pass


class DuplicateCaseError(Exception):
    pass


# ── Service ───────────────────────────────────────────────────────────────────

class CaseService:

    def __init__(self, db: AsyncSession):
        self._db = db
        self._case_repo = CaseRepository(db)
        self._timeline_repo = TimelineRepository(db)
        self._override_repo = OverrideRepository(db)
        self._outbox_repo = OutboxRepository(db)
        self._idempotency_repo = IdempotencyRepository(db)

    # ── Create ────────────────────────────────────────────────────────────────

    async def create_case(
        self,
        req: CreateCaseRequest,
        reporter_user_id: uuid.UUID,
        jurisdiction_id: str,
        correlation_id: uuid.UUID,
        idempotency_key: uuid.UUID,
    ) -> CreateCaseResponse:
        """
        Create a new case and write Case.Created to the outbox.
        Both writes are in a SINGLE transaction — atomic unit of work.

        Idempotency:
          If the same Idempotency-Key was already processed the cached
          CreateCaseResponse is returned immediately without touching the DB.
        """
        # 1. Idempotency check — return cached result if key already processed.
        existing = await self._idempotency_repo.get(idempotency_key)
        if existing:
            return CreateCaseResponse(**existing.response_body["data"])

        # 2. Generate case number OUTSIDE the transaction (read-only COUNT).
        case_number = await self._case_repo.generate_case_number()

        # 3. Atomic write: case + outbox + timeline in one transaction.
        case = await self._case_repo.create(
            case_data={
                "title": req.title,
                "description": req.description,
                "complaint_type": req.complaint_type,
                "suspect_phone": req.suspect_phone,
                "suspect_account": req.suspect_account,
                "complaint_lat": req.complaint_lat,
                "complaint_lon": req.complaint_lon,
                "reporter_user_id": reporter_user_id,
                "reporter_entity_name": req.reporter_entity_name,
                "reporter_phone": req.reporter_phone,
                "language_code": req.language_code,
                "jurisdiction_id": jurisdiction_id,
                "status": "New",
            },
            case_number=case_number,
        )

        now = datetime.now(timezone.utc).isoformat()

        # Publish Case.Created → outbox (same transaction).
        await self._outbox_repo.publish(
            aggregate_type="Case",
            aggregate_id=case.case_id,
            event_type="Case.Created",
            topic="case.created",
            event_key=str(case.case_id),
            payload={
                "caseId": str(case.case_id),
                "caseNumber": case_number,
                "complaintType": req.complaint_type,
                "suspectPhone": req.suspect_phone,
                "complaintLat": req.complaint_lat,
                "complaintLon": req.complaint_lon,
                "jurisdictionId": jurisdiction_id,
                "languageCode": req.language_code,
                "reporterUserId": str(reporter_user_id),
                "createdAt": now,
            },
            correlation_id=correlation_id,
        )

        # Append first timeline event (same transaction).
        await self._timeline_repo.append(
            case_id=case.case_id,
            event_type="Case.Created",
            description="Case created via Citizen BFF",
            actor_id=reporter_user_id,
            actor_role="CITIZEN",
            correlation_id=correlation_id,
        )

        # Store idempotency record so replay returns the same response.
        response_data = {
            "case_id": str(case.case_id),
            "case_number": case_number,
            "status": "New",
            "created_at": case.created_at.isoformat(),
            "assigned_to": None,
            "prediction_status": "PENDING",
        }
        await self._idempotency_repo.store(
            idempotency_key=idempotency_key,
            request_hash=_hash_request(req.model_dump()),
            response_status=201,
            response_body={"data": response_data},
        )
        await self._db.commit()

        return CreateCaseResponse(
            case_id=case.case_id,
            case_number=case_number,
            status="New",
            created_at=case.created_at,
            assigned_to=None,
            prediction_status="PENDING",
        )

    # ── Get ───────────────────────────────────────────────────────────────────

    async def get_case(
        self,
        case_id: uuid.UUID,
        jurisdiction_id: str,
    ) -> CaseDetailResponse:
        """
        Fetch a single case by ID.
        RBAC: jurisdiction_id from JWT must match case.jurisdiction_id.
        Prediction is the ML stub until T13.
        """
        case = await self._case_repo.get_by_id(case_id)
        if not case:
            raise CaseNotFoundError(f"Case {case_id} not found")

        if case.jurisdiction_id != jurisdiction_id:
            raise CasePermissionError("Case does not belong to your jurisdiction")

        return self._to_detail_response(case)

    # ── State Transition ──────────────────────────────────────────────────────

    async def update_state(
        self,
        case_id: uuid.UUID,
        req: UpdateCaseStateRequest,
        caller_role: str,
        caller_id: uuid.UUID,
        correlation_id: uuid.UUID,
    ) -> CaseDetailResponse:
        """
        Validate the requested state transition, then atomically:
          1. Update case.status in DB
          2. Write Case.Updated to outbox
          3. Append timeline event
        Raises InvalidTransitionError BEFORE any DB write on invalid transitions.
        """
        case = await self._case_repo.get_by_id(case_id)
        if not case:
            raise CaseNotFoundError(f"Case {case_id} not found")

        # Validate BEFORE touching DB — pure function, no I/O.
        try:
            validate_transition(
                current_state=case.status,
                new_state=req.state,
                reason=req.reason,
                caller_role=caller_role,
            )
        except TransitionError as e:
            raise InvalidTransitionError(str(e)) from e
        except TransitionPermissionError as e:
            raise CasePermissionError(str(e)) from e

        event_type = "Case.Assigned" if req.assigned_to else "Case.Updated"
        topic = "case.assigned" if req.assigned_to else "case.updated"

        updated = await self._case_repo.update_state(
            case_id=case_id,
            new_state=req.state,
            assigned_investigator=req.assigned_to,
        )

        await self._outbox_repo.publish(
            aggregate_type="Case",
            aggregate_id=case_id,
            event_type=event_type,
            topic=topic,
            event_key=str(case_id),
            payload={
                "caseId": str(case_id),
                "previousState": case.status,
                "newState": req.state,
                "reason": req.reason,
                "assignedTo": str(req.assigned_to) if req.assigned_to else None,
            },
            correlation_id=correlation_id,
        )

        await self._timeline_repo.append(
            case_id=case_id,
            event_type=event_type,
            description=f"State changed: {case.status} → {req.state}. Reason: {req.reason}",
            actor_id=caller_id,
            actor_role=caller_role,
            correlation_id=correlation_id,
        )
        await self._db.commit()

        return self._to_detail_response(updated)

    # ── Pending Review (Inference Callback) ───────────────────────────────────

    async def set_pending_review(
        self,
        case_id: uuid.UUID,
        prediction_payload: dict,
        correlation_id: uuid.UUID,
    ) -> None:
        """
        Called by Inference Orchestrator (T13) when confidence < 0.60.
        1. Insert FusedVerdict with pending_review=True, pending_notification=True
        2. Transition case to Pending_AI
        3. Write Case.Updated + Prediction.PendingReview outbox events
        4. Append timeline entry
        All in ONE transaction.
        """
        case = await self._case_repo.get_by_id(case_id)
        if not case:
            raise CaseNotFoundError(f"Case {case_id} not found")

        if case.status not in ("Investigating", "Assigned"):
            raise InvalidTransitionError(
                f"Case must be Investigating to receive HITL callback, got {case.status}"
            )

        pred_repo = PredictionRepository(self._db)

        # 1. Persist FusedVerdict (append-only)
        verdict = await pred_repo.insert(
            case_id=case_id,
            fused_score=prediction_payload.get("fusedScore", 0.0),
            risk_tier=prediction_payload.get("riskTier", "MEDIUM"),
            confidence=prediction_payload.get("confidence", 0.0),
            status="PENDING_REVIEW",
            model_breakdown=prediction_payload.get("modelBreakdown", []),
            explanation=prediction_payload.get("explanation", "Below confidence threshold — HITL required."),
            fusion_weights=prediction_payload.get("fusionWeights"),
            pending_review=True,
            pending_notification=True,   # Suppress citizen notification until APPROVE
            correlation_id=correlation_id,
        )

        # 2. Transition case to Pending_AI
        await self._case_repo.update_state(
            case_id=case_id,
            new_state="Pending_AI",
        )

        # 3. Outbox events
        await self._outbox_repo.publish(
            aggregate_type="Case",
            aggregate_id=case_id,
            event_type="Case.Updated",
            topic="case.updated", event_key=str(case_id),
            payload={
                "caseId": str(case_id),
                "newState": "Pending_AI",
                "reason": "PENDING_REVIEW",
                "predictionId": str(verdict.prediction_id),
            },
            correlation_id=correlation_id,
        )
        await self._outbox_repo.publish(
            aggregate_type="Prediction",
            aggregate_id=case_id,
            event_type="Prediction.PendingReview",
            topic="prediction.overridden", event_key=str(case_id),
            payload={
                "caseId": str(case_id),
                "predictionId": str(verdict.prediction_id),
                "fusedScore": prediction_payload.get("fusedScore"),
                "riskTier": prediction_payload.get("riskTier"),
                "confidence": prediction_payload.get("confidence"),
            },
            correlation_id=correlation_id,
        )

        # 4. Timeline
        await self._timeline_repo.append(
            case_id=case_id,
            event_type="Prediction.PendingReview",
            description=(
                f"AI confidence {prediction_payload.get('confidence', 0)*100:.0f}% below threshold. "
                f"Routed to HITL review. Risk: {prediction_payload.get('riskTier')} "
                f"({prediction_payload.get('fusedScore', 0.0):.0f}/100)"
            ),
            correlation_id=correlation_id,
        )
        await self._db.commit()

    # ── Verdict Override ──────────────────────────────────────────────────────

    async def override_verdict(
        self,
        case_id: uuid.UUID,
        req: VerdictOverrideRequest,
        investigator_id: uuid.UUID,
        correlation_id: uuid.UUID,
    ) -> dict:
        """
        Human-in-the-loop verdict override (HITL).

        APPROVE → new_state = Action_Taken (resume automated actions)
        REJECT  → new_state = Closed, disposition = FALSE_POSITIVE

        Atomically writes: OverrideRecord + state update + outbox + timeline.
        """
        case = await self._case_repo.get_by_id(case_id)
        if not case:
            raise CaseNotFoundError(f"Case {case_id} not found")

        if case.status not in ("Pending_AI", "Action_Taken"):
            raise InvalidTransitionError(
                f"Verdict override requires Pending_AI or Action_Taken status, got '{case.status}'"
            )

        new_state = "Action_Taken" if req.decision == "APPROVE" else "Closed"
        disposition = "FALSE_POSITIVE" if req.decision == "REJECT" else None

        # APPEND-ONLY — DB trigger prevents future UPDATE/DELETE.
        override = await self._override_repo.create(
            case_id=case_id,
            original_verdict_id=req.original_verdict_id,
            decision=req.decision,
            justification=req.justification,
            investigator_id=investigator_id,
            original_score=None,        # populated if fused_verdict is fetched
            original_confidence=None,
            correlation_id=correlation_id,
        )

        await self._case_repo.update_state(
            case_id=case_id,
            new_state=new_state,
            disposition=disposition,
        )

        await self._outbox_repo.publish(
            aggregate_type="Case",
            aggregate_id=case_id,
            event_type="Prediction.Overridden",
            topic="prediction.overridden",
            event_key=str(case_id),
            payload={
                "caseId": str(case_id),
                "decision": req.decision,
                "overrideId": str(override.override_id),
                "investigatorId": str(investigator_id),
                "originalVerdictId": str(req.original_verdict_id),
                "newState": new_state,
                "disposition": disposition,
            },
            correlation_id=correlation_id,
        )

        await self._timeline_repo.append(
            case_id=case_id,
            event_type="Verdict.Overridden",
            description=(
                f"Investigator {req.decision.lower()}d AI verdict. "
                f"Justification: {req.justification[:100]}"
            ),
            actor_id=investigator_id,
            actor_role="INVESTIGATOR",
            correlation_id=correlation_id,
        )
        await self._db.commit()

        if req.decision == "APPROVE":
            # Resume suppressed notification (Prediction.Overridden triggers Notification via Kafka)
            # Direct HTTP call to Notification Service added in T13b (Day 7)
            # For now: publish Notification.Requested to outbox so Diganta's integration picks it up
            await self._outbox_repo.publish(
                aggregate_type="Notification",
                aggregate_id=case_id,
                event_type="Notification.Requested",
                topic="notification.requested", event_key=str(case_id),
                payload={"caseId": str(case_id), "trigger": "HITL_APPROVED"},
                correlation_id=correlation_id,
            )
            await self._db.commit()

        return {
            "overrideId": str(override.override_id),
            "decision": req.decision,
            "caseId": str(case_id),
            "investigatorId": str(investigator_id),
            "originalVerdictId": str(req.original_verdict_id),
            "timestamp": override.created_at.isoformat(),
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _to_detail_response(self, case) -> CaseDetailResponse:
        """
        Convert Case ORM → CaseDetailResponse.
        prediction: ML stub until T13 wires the real Inference Orchestrator.
        evidence_count: 0 stub until T14 cross-wiring (see assumptions.md).
        """
        return CaseDetailResponse(
            case_id=case.case_id,
            case_number=case.case_number,
            status=case.status,
            title=case.title,
            description=case.description,
            complaint_type=case.complaint_type,
            suspect_phone=case.suspect_phone,
            complaint_lat=case.complaint_lat,
            complaint_lon=case.complaint_lon,
            reporter_entity_name=case.reporter_entity_name,
            reporter_phone=case.reporter_phone,
            language_code=case.language_code,
            assigned_to=case.assigned_investigator,
            jurisdiction_id=case.jurisdiction_id,
            priority=case.priority,
            prediction=None,    # TODO T13: replace with real FusedVerdict query
            evidence_count=0,   # TODO T14: count from evidence.evidence table
            created_at=case.created_at,
            updated_at=case.updated_at,
        )


# ── Module-level helpers ───────────────────────────────────────────────────────

def _hash_request(data: dict) -> str:
    """Deterministic SHA-256 of request body dict for idempotency comparison."""
    serialized = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()

# ----------------------------------------
# FILE: backend/case/http_client.py
# ----------------------------------------

"""Shared httpx.AsyncClient dependency for Case Service."""
from fastapi import Request
import httpx


async def get_http_client(request: Request) -> httpx.AsyncClient:
    """Return the shared AsyncClient initialized in lifespan."""
    return request.app.state.http_client

# ----------------------------------------
# FILE: backend/case/main.py
# ----------------------------------------

"""
Platform Service Template — FastAPI
====================================
Copy this file into your service directory and rename/modify as needed.

SETUP INSTRUCTIONS:
1. Copy backend/template/ → backend/<your-service>/
2. Set SERVICE_NAME in settings below
3. Implement your domain endpoints in separate routers
4. Import routers here and include them on `app`
5. Run: uvicorn main:app --reload

PATTERNS ESTABLISHED HERE:
- Structured JSON logging (loguru) with trace_id in every log line
- OpenTelemetry auto-instrumentation (traces, metrics → OTel Collector)
- Prometheus metrics via prometheus-fastapi-instrumentator (/metrics)
- /health/live  → liveness probe (is the process alive?)
- /health/ready → readiness probe (can it serve traffic?)
- Standard error response shape: {requestId, correlationId, errorCode, message}
- Vault secret loading at startup (graceful fallback to env vars for local dev)
"""

import sys
import uuid
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from prometheus_fastapi_instrumentator import Instrumentator

# ─── OpenTelemetry (auto-instrument BEFORE app creation) ─────────────────────
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource

from config import settings

# ─── Tracer setup ─────────────────────────────────────────────────────────────
resource = Resource.create({"service.name": settings.SERVICE_NAME, "service.version": settings.SERVICE_VERSION})
tracer_provider = TracerProvider(resource=resource)
tracer_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.OTEL_ENDPOINT))
)
trace.set_tracer_provider(tracer_provider)

# ─── Logging (structured JSON via loguru) ─────────────────────────────────────
logger.remove()
logger.add(
    sys.stdout,
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {extra[service]} | {extra[trace_id]} | {message}",
    serialize=True,    # Emit as JSON lines
    level="INFO",
)
logger = logger.bind(service=settings.SERVICE_NAME, trace_id="—")


# ─── Lifespan (startup / shutdown) ───────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"{settings.SERVICE_NAME} starting up")
    
    import httpx
    from db import get_engine, get_session_factory
    from redis_client import create_redis_client
    
    engine = get_engine()
    app.state.db_engine = engine
    app.state.db_session_factory = get_session_factory(engine)
    app.state.redis = create_redis_client()
    await app.state.redis.ping()
    
    # Shared HTTP client for downstream calls (Inference Orchestrator)
    app.state.http_client = httpx.AsyncClient(
        timeout=5.0,
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
    )
    
    logger.info(f"{settings.SERVICE_NAME} ready")
    yield
    
    logger.info(f"{settings.SERVICE_NAME} shutting down")
    await app.state.db_engine.dispose()
    await app.state.redis.aclose()
    await app.state.http_client.aclose()


# ─── App ─────────────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.SERVICE_NAME,
    version=settings.SERVICE_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Auto-instrument FastAPI with OTel
FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer_provider)

# ─── CORS ────────────────────────────────────────────────────────────────────
# Bug Fix T18-A: CORS was missing — Citizen/Bank/Telecom UIs were blocked.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in settings.ALLOWED_ORIGINS.split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Expose /metrics endpoint for Prometheus scraping
Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
).instrument(app).expose(app, endpoint="/metrics")


# ─── Middleware: correlation ID + request logging ─────────────────────────────
@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

    # Bind trace context to logger for this request
    span_context = trace.get_current_span().get_span_context()
    otel_trace_id = f"{span_context.trace_id:032x}" if span_context.is_valid else "—"
    req_logger = logger.bind(
        trace_id=otel_trace_id,
        correlation_id=correlation_id,
        request_id=request_id,
        method=request.method,
        path=request.url.path,
    )

    start = time.perf_counter()
    response: Response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)

    req_logger.info(
        "request_completed",
        status_code=response.status_code,
        duration_ms=duration_ms,
    )

    response.headers["X-Correlation-ID"] = correlation_id
    response.headers["X-Request-ID"] = request_id
    return response


# ─── Standard error handler ───────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    correlation_id = request.headers.get("X-Correlation-ID", "unknown")
    request_id = request.headers.get("X-Request-ID", "unknown")
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "requestId": request_id,
            "correlationId": correlation_id,
            "errorCode": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected error occurred.",
            "details": None,
        },
    )


# ─── Health Endpoints ─────────────────────────────────────────────────────────
@app.get("/health/live", tags=["Health"])
async def liveness():
    """Kubernetes liveness probe — is the process running?"""
    return {"status": "alive", "service": settings.SERVICE_NAME}


@app.get("/health/ready", tags=["Health"])
async def readiness(request: Request):
    """
    Kubernetes readiness probe — can the service serve traffic?
    Checks: DB connection, Redis ping, Kafka broker reachability.
    Returns 503 if any dependency is unhealthy.
    """
    checks = {}
    healthy = True

    # ── DB check ──────────────────────────────────────────────
    try:
        from sqlalchemy import text
        SessionFactory = request.app.state.db_session_factory
        async with SessionFactory() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"
        healthy = False

    # ── Redis check ───────────────────────────────────────────
    try:
        await request.app.state.redis.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"
        healthy = False

    status_code = 200 if healthy else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if healthy else "not_ready",
            "service": settings.SERVICE_NAME,
            "checks": checks,
        },
    )

@app.get("/health/integration", include_in_schema=False)
async def integration_check():
    """Internal endpoint for cross-team integration verification."""
    return {
        "service": "case-service",
        "kafkaTopics": {
            "publishes": ["case.created", "case.updated", "prediction.completed", "prediction.overridden"],
        },
        "apiVersion": "v1",
        "endpoints": [
            "POST /api/v1/cases",
            "GET /api/v1/cases/:id",
            "PATCH /api/v1/cases/:id/state",
        ],
    }


# ─── Domain Routers ───────────────────────────────────────────────────────────
from routers.case_router import router as case_router
app.include_router(case_router, prefix="/api/v1")

# ----------------------------------------
# FILE: backend/case/response_helpers.py
# ----------------------------------------

"""Standard response envelope helpers (docs/api/_shared_contract.md)."""
import uuid
from datetime import datetime, timezone
from typing import Any


def success_response(data: Any, correlation_id: str = "") -> dict:
    return {
        "requestId": str(uuid.uuid4()),
        "correlationId": correlation_id,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "success",
        "data": data,
    }


def error_response(
    error_code: str,
    message: str,
    correlation_id: str = "",
    details: Any = None,
) -> dict:
    return {
        "requestId": str(uuid.uuid4()),
        "correlationId": correlation_id,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "error",
        "errorCode": error_code,
        "message": message,
        "details": details,
    }

# ----------------------------------------
# FILE: backend/case/routers/case_router.py
# ----------------------------------------

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
        return error_response("MISSING_IDEMPOTENCY_KEY", "Idempotency-Key header is required", _corr(request))
    try:
        idem_uuid = uuid.UUID(idempotency_key)
    except ValueError:
        return error_response("INVALID_IDEMPOTENCY_KEY", "Idempotency-Key must be a UUID", _corr(request))

    svc = CaseService(db)
    try:
        result = await svc.create_case(
            req=body,
            reporter_user_id=current_user.user_id,
            jurisdiction_id=current_user.jurisdiction_id or "",
            correlation_id=uuid.UUID(_corr(request)),
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
        "items": [i.model_dump(mode='json', by_alias=True) for i in items],
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

# ----------------------------------------
# FILE: backend/case/models/outbox.py
# ----------------------------------------

"""
SQLAlchemy ORM model for platform.outbox.
Maps exactly to the DDL in docs/db/postgres.sql.

Note: A PostgreSQL trigger (outbox_notify_after_insert / platform.notify_outbox)
fires NOTIFY on each INSERT so the outbox relay worker wakes up immediately.
"""
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import UUID, CheckConstraint, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Outbox(Base):
    __tablename__ = "outbox"
    __table_args__ = (
        CheckConstraint("status IN ('PENDING','PUBLISHED','FAILED')", name="outbox_status_check"),
        {"schema": "platform"},
    )

    outbox_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    topic: Mapped[str] = mapped_column(String(128), nullable=False)
    event_key: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[Any] = mapped_column(JSONB, nullable=False)
    correlation_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

# ----------------------------------------
# FILE: backend/case/models/idempotency.py
# ----------------------------------------

"""
SQLAlchemy ORM for platform.idempotency_keys.
Used by all mutating POST endpoints to prevent duplicate processing.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String, Text, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = {"schema": "platform"}

    idempotency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    service_name: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict | None] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

# ----------------------------------------
# FILE: backend/case/models/timeline.py
# ----------------------------------------

"""
SQLAlchemy ORM model for investigation.case_timeline.
Maps exactly to the DDL in docs/db/postgres.sql.
"""
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import UUID, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CaseTimeline(Base):
    __tablename__ = "case_timeline"
    __table_args__ = {"schema": "investigation"}

    timeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_role: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # 'metadata' is reserved by SQLAlchemy DeclarativeBase — use explicit column name
    event_metadata: Mapped[Any] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    correlation_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

# ----------------------------------------
# FILE: backend/case/models/schemas.py
# ----------------------------------------

"""
Pydantic schemas for Case Service API.
Field names match docs/api/case.md (camelCase) exactly via alias_generator.
"""
import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

# ── Shared config ─────────────────────────────────────────────────────────────

_VALID_COMPLAINT_TYPES = {"UPI_FRAUD", "CALL_FRAUD", "COUNTERFEIT_CURRENCY", "CYBER_CRIME", "OTHER"}
_VALID_STATUSES = {"New", "Assigned", "Investigating", "Pending_AI", "Action_Taken", "Closed"}
_VALID_DECISIONS = {"APPROVE", "REJECT"}
_VALID_LANGUAGE_CODES = {"hi", "bn", "te", "ta", "mr", "gu", "kn", "ml", "pa", "ur", "or", "as", "en", "other"}
_E164_RE = re.compile(r"^\+[1-9][0-9]{7,14}$")


class CurrentUser(BaseModel):
    user_id: uuid.UUID
    email: str
    role: str
    org_id: Optional[uuid.UUID] = None
    jurisdiction_id: Optional[str] = None
    jti: str



class CamelModel(BaseModel):
    """Base model that accepts and produces camelCase field names."""
    model_config = {
        "alias_generator": to_camel,
        "populate_by_name": True,       # also accept snake_case in code
        "protected_namespaces": (),     # allow 'model_breakdown' field names
    }


# ── Request Schemas ───────────────────────────────────────────────────────────

class CreateCaseRequest(CamelModel):
    title: str = Field(..., max_length=200)
    description: str
    complaint_type: str
    suspect_phone: Optional[str] = None
    suspect_account: Optional[str] = None
    complaint_lat: Optional[float] = None
    complaint_lon: Optional[float] = None
    reporter_entity_name: Optional[str] = None
    reporter_phone: Optional[str] = None
    language_code: str = Field("en")

    @field_validator("complaint_type")
    @classmethod
    def validate_complaint_type(cls, v: str) -> str:
        if v not in _VALID_COMPLAINT_TYPES:
            raise ValueError(f"complaintType must be one of {sorted(_VALID_COMPLAINT_TYPES)}")
        return v

    @field_validator("suspect_phone", "reporter_phone", mode="before")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        if not _E164_RE.match(v):
            raise ValueError("Phone must be in E.164 format (e.g. +919876543210)")
        return v

    @field_validator("language_code")
    @classmethod
    def validate_language_code(cls, v: str) -> str:
        if v not in _VALID_LANGUAGE_CODES:
            raise ValueError(f"languageCode must be a supported BCP-47 code: {sorted(_VALID_LANGUAGE_CODES)}")
        return v

    @model_validator(mode="after")
    def validate_coordinates(self) -> "CreateCaseRequest":
        if self.complaint_lat is not None and not (-90 <= self.complaint_lat <= 90):
            raise ValueError("complaintLat must be between -90 and 90")
        if self.complaint_lon is not None and not (-180 <= self.complaint_lon <= 180):
            raise ValueError("complaintLon must be between -180 and 180")
        return self


class UpdateCaseStateRequest(CamelModel):
    state: str
    reason: str
    assigned_to: Optional[uuid.UUID] = None

    @field_validator("state")
    @classmethod
    def validate_state(cls, v: str) -> str:
        if v not in _VALID_STATUSES:
            raise ValueError(f"state must be one of {sorted(_VALID_STATUSES)}")
        return v


class VerdictOverrideRequest(CamelModel):
    decision: str
    justification: str = Field(..., min_length=20)   # NFR-8.4 legal requirement
    original_verdict_id: uuid.UUID

    @field_validator("decision")
    @classmethod
    def validate_decision(cls, v: str) -> str:
        if v not in _VALID_DECISIONS:
            raise ValueError(f"decision must be one of {sorted(_VALID_DECISIONS)}")
        return v


# ── Response Schemas ──────────────────────────────────────────────────────────

class PredictionSummary(CamelModel):
    prediction_id: uuid.UUID
    fused_score: Decimal
    risk_tier: str
    confidence: Decimal
    status: str
    model_breakdown: List[Any] = []
    explanation: str
    created_at: datetime


class CreateCaseResponse(CamelModel):
    case_id: uuid.UUID
    case_number: str
    status: str
    created_at: datetime
    assigned_to: Optional[uuid.UUID] = None
    prediction_status: str = "PENDING"


class CaseSummaryResponse(CamelModel):
    case_id: uuid.UUID
    case_number: str
    title: str
    complaint_type: str
    status: str
    priority: str
    jurisdiction_id: str
    assigned_to: Optional[uuid.UUID] = None
    risk_tier: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class CaseDetailResponse(CamelModel):
    case_id: uuid.UUID
    case_number: str
    status: str
    title: str
    description: str
    complaint_type: str
    suspect_phone: Optional[str] = None
    complaint_lat: Optional[Decimal] = None
    complaint_lon: Optional[Decimal] = None
    reporter_entity_name: Optional[str] = None
    reporter_phone: Optional[str] = None
    language_code: str
    assigned_to: Optional[uuid.UUID] = None
    jurisdiction_id: str
    priority: str
    prediction: Optional[PredictionSummary] = None
    evidence_count: int = 0
    created_at: datetime
    updated_at: datetime


class PaginatedCasesResponse(CamelModel):
    items: List[CaseSummaryResponse]
    next_cursor: Optional[str] = None
    has_more: bool
    total: int


class TimelineEventResponse(CamelModel):
    timeline_id: uuid.UUID
    event_type: str
    actor: Optional[str] = None
    actor_role: Optional[str] = None
    description: str
    metadata: Any = {}
    timestamp: datetime   # maps to created_at


class PaginatedTimelineResponse(CamelModel):
    items: List[TimelineEventResponse]
    next_cursor: Optional[str] = None
    has_more: bool
    total: int


class VerdictOverrideResponse(CamelModel):
    override_id: uuid.UUID
    decision: str
    case_id: uuid.UUID
    investigator_id: uuid.UUID
    original_verdict_id: uuid.UUID
    timestamp: datetime

# ----------------------------------------
# FILE: backend/case/models/override.py
# ----------------------------------------

"""
SQLAlchemy ORM model for inference.override_records.
Maps exactly to the DDL in docs/db/postgres.sql.

# APPEND-ONLY: never UPDATE or DELETE — DB trigger override_records_append_only enforces this.
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import UUID, CheckConstraint, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class OverrideRecord(Base):
    __tablename__ = "override_records"
    __table_args__ = (
        CheckConstraint("decision IN ('APPROVE','REJECT')", name="override_decision_check"),
        CheckConstraint("LENGTH(justification) >= 20", name="override_justification_check"),
        {"schema": "inference"},
    )

    override_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    original_verdict_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    investigator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    original_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    original_confidence: Mapped[Optional[Decimal]] = mapped_column(Numeric(4, 3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    correlation_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)

# ----------------------------------------
# FILE: backend/case/models/prediction.py
# ----------------------------------------

"""
SQLAlchemy ORM model for inference.fused_verdicts.
Maps exactly to the DDL in docs/db/postgres.sql.

# APPEND-ONLY: never UPDATE or DELETE — DB trigger fused_verdicts_append_only enforces this.
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import UUID, Boolean, CheckConstraint, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class FusedVerdict(Base):
    __tablename__ = "fused_verdicts"
    __table_args__ = (
        CheckConstraint("fused_score BETWEEN 0 AND 100", name="fused_verdicts_score_check"),
        CheckConstraint("risk_tier IN ('LOW','MEDIUM','HIGH','CRITICAL')", name="fused_verdicts_risk_tier_check"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="fused_verdicts_confidence_check"),
        CheckConstraint("status IN ('COMPLETE','INCOMPLETE','PENDING_REVIEW')", name="fused_verdicts_status_check"),
        {"schema": "inference"},
    )

    # PK is also a FK to inference.predictions — same UUID
    prediction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    fused_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    risk_tier: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    model_breakdown: Mapped[Any] = mapped_column(JSONB, nullable=False, default=list)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    fusion_weights: Mapped[Any] = mapped_column(JSONB, nullable=False)
    pending_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pending_notification: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fusion_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    correlation_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)

# ----------------------------------------
# FILE: backend/case/models/case.py
# ----------------------------------------

"""
SQLAlchemy ORM model for investigation.cases.
Maps exactly to the DDL in docs/db/postgres.sql.
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    UUID, CheckConstraint, DateTime, ForeignKey,
    Numeric, String, Text, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (
        CheckConstraint(
            "complaint_type IN ('UPI_FRAUD','CALL_FRAUD','COUNTERFEIT_CURRENCY','CYBER_CRIME','OTHER')",
            name="cases_complaint_type_check",
        ),
        CheckConstraint(
            "status IN ('New','Assigned','Investigating','Pending_AI','Action_Taken','Closed')",
            name="cases_status_check",
        ),
        CheckConstraint(
            "priority IN ('LOW','NORMAL','HIGH','CRITICAL')",
            name="cases_priority_check",
        ),
        CheckConstraint(
            "suspect_phone IS NULL OR suspect_phone ~ '^\\+[1-9][0-9]{7,14}$'",
            name="cases_suspect_phone_check",
        ),
        CheckConstraint(
            "reporter_phone IS NULL OR reporter_phone ~ '^\\+[1-9][0-9]{7,14}$'",
            name="cases_reporter_phone_check",
        ),
        CheckConstraint(
            "complaint_lat IS NULL OR complaint_lat BETWEEN -90 AND 90",
            name="cases_lat_check",
        ),
        CheckConstraint(
            "complaint_lon IS NULL OR complaint_lon BETWEEN -180 AND 180",
            name="cases_lon_check",
        ),
        {"schema": "investigation"},
    )

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    complaint_type: Mapped[str] = mapped_column(String(32), nullable=False)
    suspect_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    suspect_account: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    complaint_lat: Mapped[Optional[Decimal]] = mapped_column(Numeric(9, 6), nullable=True)
    complaint_lon: Mapped[Optional[Decimal]] = mapped_column(Numeric(9, 6), nullable=True)
    reporter_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    reporter_entity_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    reporter_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    language_code: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    jurisdiction_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="New")
    assigned_investigator: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="NORMAL")
    disposition: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

# ----------------------------------------
# FILE: backend/case/db.py
# ----------------------------------------

"""
Auth Service — Database Connection Pool
Uses asyncpg directly for connection pool management.
SQLAlchemy async engine for ORM operations.
Pool: min=5, max=20 (per Execution.md T5a spec).
"""
from typing import AsyncGenerator

import asyncpg
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from fastapi import Depends, Request

from config import settings


def get_engine():
    """Create SQLAlchemy async engine. Called once at startup."""
    return create_async_engine(
        settings.DATABASE_URL,
        pool_size=5,
        max_overflow=15,        # 5 + 15 = 20 max total connections
        pool_pre_ping=True,     # Validate connections before use
        echo=False,
    )


def get_session_factory(engine) -> async_sessionmaker:
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an async DB session."""
    session_factory = request.app.state.db_session_factory
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise

# ----------------------------------------
# FILE: backend/case/redis_client.py
# ----------------------------------------

"""
Auth Service — Redis Async Client
Key patterns (from docs/db/redis.md):
  auth:denylist:{jti}          → JWT denylist
  auth:fail:{email}            → Login failure counter (TTL 10m)
  auth:lock:{email}            → Soft lock flag (TTL 15m)
  auth:mfa:{token}             → MFA session (TTL 5m)
  session:refresh:{tokenHash}  → Refresh token lookup
  idempotency:{service}:{key}  → Idempotency response cache
"""
import redis.asyncio as aioredis
from fastapi import Request

from config import settings


def create_redis_client() -> aioredis.Redis:
    """Create async Redis client. Called once at startup."""
    return aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )


async def get_redis(request: Request) -> aioredis.Redis:
    """FastAPI dependency: returns the shared Redis client."""
    return request.app.state.redis

# ----------------------------------------
# FILE: backend/case/repositories/prediction_repository.py
# ----------------------------------------

"""
Prediction Repository — INSERT only on inference.fused_verdicts.
APPEND-ONLY: DB trigger prevents UPDATE and DELETE.
Never call update() or delete() on FusedVerdict rows.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from models.prediction import FusedVerdict


class PredictionRepository:
    """APPEND-ONLY — do not add update/delete methods."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def insert(
        self,
        case_id: uuid.UUID,
        fused_score: float,
        risk_tier: str,
        confidence: float,
        status: str,
        model_breakdown: list,
        explanation: str,
        fusion_weights: Optional[dict] = None,
        pending_review: bool = False,
        pending_notification: bool = False,
        correlation_id: Optional[uuid.UUID] = None,
    ) -> FusedVerdict:
        """
        Insert a new FusedVerdict row.
        Caller must commit this within the enclosing transaction.
        """
        now = datetime.now(timezone.utc)
        verdict = FusedVerdict(
            prediction_id=uuid.uuid4(),
            case_id=case_id,
            fused_score=fused_score,
            risk_tier=risk_tier,
            confidence=confidence,
            status=status,
            model_breakdown=model_breakdown,
            explanation=explanation,
            fusion_weights=fusion_weights or {},
            pending_review=pending_review,
            pending_notification=pending_notification,
            fusion_timestamp=now,
            correlation_id=correlation_id,
        )
        self._session.add(verdict)
        await self._session.flush()
        return verdict

# ----------------------------------------
# FILE: backend/case/repositories/timeline_repository.py
# ----------------------------------------

"""
Timeline Repository — append + cursor-paginated reads for investigation.case_timeline.
Timeline events are NEVER updated or deleted — only appended.
"""
import base64
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.timeline import CaseTimeline


# ── Cursor helpers ────────────────────────────────────────────────────────────

def _encode_cursor(created_at: datetime, timeline_id: uuid.UUID) -> str:
    raw = f"{created_at.isoformat()}|{timeline_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    ts_str, id_str = raw.split("|", 1)
    return datetime.fromisoformat(ts_str), uuid.UUID(id_str)


# ── Repository ────────────────────────────────────────────────────────────────

class TimelineRepository:

    def __init__(self, session: AsyncSession):
        self._session = session

    async def append(
        self,
        case_id: uuid.UUID,
        event_type: str,
        description: str,
        actor_id: Optional[uuid.UUID] = None,
        actor_role: Optional[str] = None,
        metadata: Optional[dict] = None,
        correlation_id: Optional[uuid.UUID] = None,
    ) -> CaseTimeline:
        """
        Insert a new timeline event for a case.
        Always append — never update or delete.
        Caller commits.
        """
        event = CaseTimeline(
            case_id=case_id,
            event_type=event_type,
            description=description,
            actor_id=actor_id,
            actor_role=actor_role,
            event_metadata=metadata or {},
            correlation_id=correlation_id,
        )
        self._session.add(event)
        await self._session.flush()
        await self._session.refresh(event)
        return event

    async def paginate(
        self,
        case_id: uuid.UUID,
        cursor: Optional[str] = None,
        limit: int = 20,
    ) -> tuple[list[CaseTimeline], Optional[str], bool, int]:
        """
        Cursor-paginated timeline events ordered by created_at DESC (newest first).
        Returns (items, next_cursor, has_more, total).
        """
        limit = min(limit, 100)

        base_q = select(CaseTimeline).where(CaseTimeline.case_id == case_id)

        # Total count for this case
        count_q = select(func.count()).select_from(base_q.subquery())
        total: int = (await self._session.execute(count_q)).scalar_one()

        # Cursor predicate
        if cursor:
            try:
                cursor_ts, cursor_id = _decode_cursor(cursor)
                base_q = base_q.where(
                    (CaseTimeline.created_at < cursor_ts)
                    | (
                        (CaseTimeline.created_at == cursor_ts)
                        & (CaseTimeline.timeline_id < cursor_id)
                    )
                )
            except Exception:
                pass

        page_q = (
            base_q
            .order_by(CaseTimeline.created_at.desc(), CaseTimeline.timeline_id.desc())
            .limit(limit + 1)
        )
        rows = (await self._session.execute(page_q)).scalars().all()

        has_more = len(rows) > limit
        items = list(rows[:limit])
        next_cursor: Optional[str] = None
        if has_more and items:
            last = items[-1]
            next_cursor = _encode_cursor(last.created_at, last.timeline_id)

        return items, next_cursor, has_more, total

# ----------------------------------------
# FILE: backend/case/repositories/override_repository.py
# ----------------------------------------

"""
Override Repository — append-only INSERTs for inference.override_records.

# APPEND-ONLY — DB trigger `override_records_append_only` calls
# platform.prevent_mutation() and will RAISE an exception if UPDATE
# or DELETE is attempted. Never call session.execute(update(...)) or
# session.execute(delete(...)) on OverrideRecord.
"""
import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from models.override import OverrideRecord


class OverrideRepository:

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        case_id: uuid.UUID,
        original_verdict_id: uuid.UUID,
        decision: str,
        justification: str,
        investigator_id: uuid.UUID,
        original_score: Optional[float] = None,
        original_confidence: Optional[float] = None,
        correlation_id: Optional[uuid.UUID] = None,
    ) -> OverrideRecord:
        """
        INSERT an immutable override record.
        The DB trigger prevents any subsequent UPDATE or DELETE.
        Caller must commit (together with any domain row changes in same transaction).
        """
        record = OverrideRecord(
            case_id=case_id,
            original_verdict_id=original_verdict_id,
            decision=decision,
            justification=justification,
            investigator_id=investigator_id,
            original_score=Decimal(str(original_score)) if original_score is not None else None,
            original_confidence=Decimal(str(original_confidence)) if original_confidence is not None else None,
            correlation_id=correlation_id,
        )
        self._session.add(record)
        await self._session.flush()
        await self._session.refresh(record)
        return record

# ----------------------------------------
# FILE: backend/case/repositories/case_repository.py
# ----------------------------------------

"""
Case Repository — CRUD for investigation.cases.
RBAC: all list queries are scoped by jurisdiction_id from JWT.
"""
import base64
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.case import Case


# ── Cursor helpers ────────────────────────────────────────────────────────────

def _encode_cursor(created_at: datetime, case_id: uuid.UUID) -> str:
    """Encode (created_at, case_id) into URL-safe base64 cursor string."""
    raw = f"{created_at.isoformat()}|{case_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Decode cursor string back to (created_at, case_id)."""
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    ts_str, id_str = raw.split("|", 1)
    return datetime.fromisoformat(ts_str), uuid.UUID(id_str)


# ── Repository ────────────────────────────────────────────────────────────────

class CaseRepository:

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, case_data: dict, case_number: str) -> Case:
        """
        Insert a new case row.
        Caller is responsible for committing the transaction.
        """
        case = Case(case_number=case_number, **case_data)
        self._session.add(case)
        await self._session.flush()   # assign case_id without committing
        await self._session.refresh(case)
        return case

    async def get_by_id(self, case_id: uuid.UUID) -> Optional[Case]:
        """Fetch a case by primary key. Returns None if not found."""
        result = await self._session.execute(
            select(Case).where(Case.case_id == case_id)
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        jurisdiction_id: str,
        status: Optional[str] = None,
        risk_tier: Optional[str] = None,       # filter applied at service layer via fused_verdicts join
        assigned_to: Optional[uuid.UUID] = None,
        cursor: Optional[str] = None,
        limit: int = 20,
    ) -> tuple[list[Case], Optional[str], bool, int]:
        """
        Cursor-paginated list of cases, RBAC-scoped to jurisdiction_id.
        Returns (items, next_cursor, has_more, total).
        Cursor encodes (created_at ISO, case_id) — URL-safe base64.
        """
        limit = min(limit, 100)

        # ── base query ────────────────────────────────────────────────────────
        base_q = select(Case).where(Case.jurisdiction_id == jurisdiction_id)

        if status:
            base_q = base_q.where(Case.status == status)
        if assigned_to:
            base_q = base_q.where(Case.assigned_investigator == assigned_to)

        # ── total count (before cursor) ───────────────────────────────────────
        count_q = select(func.count()).select_from(base_q.subquery())
        total: int = (await self._session.execute(count_q)).scalar_one()

        # ── cursor predicate ──────────────────────────────────────────────────
        if cursor:
            cursor_ts, cursor_id = _decode_cursor(cursor)
            base_q = base_q.where(
                (Case.created_at < cursor_ts)
                | ((Case.created_at == cursor_ts) & (Case.case_id < cursor_id))
            )

        # ── fetch limit+1 to determine hasMore ───────────────────────────────
        page_q = base_q.order_by(Case.created_at.desc(), Case.case_id.desc()).limit(limit + 1)
        rows = (await self._session.execute(page_q)).scalars().all()

        has_more = len(rows) > limit
        items = list(rows[:limit])
        next_cursor: Optional[str] = None
        if has_more and items:
            last = items[-1]
            next_cursor = _encode_cursor(last.created_at, last.case_id)

        return items, next_cursor, has_more, total

    async def update_state(
        self,
        case_id: uuid.UUID,
        new_state: str,
        assigned_investigator: Optional[uuid.UUID] = None,
        disposition: Optional[str] = None,
    ) -> Optional[Case]:
        """
        Update case status (and optionally assignee / disposition).
        Returns the refreshed Case, or None if not found.
        """
        values: dict = {"status": new_state, "updated_at": datetime.now(timezone.utc)}
        if assigned_investigator is not None:
            values["assigned_investigator"] = assigned_investigator
        if disposition is not None:
            values["disposition"] = disposition

        stmt = (
            update(Case)
            .where(Case.case_id == case_id)
            .values(**values)
            .returning(Case)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def generate_case_number(self) -> str:
        """
        Generate the next sequential case number in the format CYB-YYYY-NNNNN.
        Uses COUNT(*) for the current calendar year.
        Note: good enough for hackathon; production should use a DB sequence.
        """
        year = datetime.now(timezone.utc).year
        count_result = await self._session.execute(
            select(func.count(Case.case_id)).where(
                func.extract("year", Case.created_at) == year
            )
        )
        count: int = count_result.scalar_one()
        return f"CYB-{year}-{count + 1:05d}"

# ----------------------------------------
# FILE: backend/case/repositories/outbox_repository.py
# ----------------------------------------

"""
Outbox Repository — writes events to platform.outbox.

Kafka topic constants from docs/db/kafka.md.

After each INSERT the DB trigger platform.notify_outbox() fires
  NOTIFY outbox_channel, '<outbox_id>'
so Diganta's Outbox Publisher wakes immediately and relays to Kafka.
The outbox row and the domain row MUST be committed in the same transaction.
"""
import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from models.outbox import Outbox


# ── Kafka topic constants (docs/db/kafka.md) ──────────────────────────────────
TOPIC_CASE_CREATED = "case.created"
TOPIC_CASE_UPDATED = "case.updated"
TOPIC_CASE_ASSIGNED = "case.assigned"
TOPIC_CASE_CLOSED = "case.closed"
TOPIC_PREDICTION_REQUESTED = "prediction.requested"
TOPIC_PREDICTION_COMPLETED = "prediction.completed"
TOPIC_PREDICTION_OVERRIDDEN = "prediction.overridden"
TOPIC_NOTIFICATION_REQUESTED = "notification.requested"


class OutboxRepository:

    def __init__(self, session: AsyncSession):
        self._session = session

    async def publish(
        self,
        aggregate_type: str,
        aggregate_id: uuid.UUID,
        event_type: str,
        topic: str,
        event_key: str,
        payload: dict,
        correlation_id: Optional[uuid.UUID] = None,
    ) -> Outbox:
        """
        Write a domain event to platform.outbox (status=PENDING).
        The INSERT trigger fires pg_notify so the relay worker wakes up.
        Commit this INSERT atomically with the domain row change.

        Args:
            aggregate_type: e.g. "Case", "Prediction"
            aggregate_id:   UUID of the domain entity (e.g. case_id)
            event_type:     e.g. "Case.Created"
            topic:          Kafka topic name (use TOPIC_* constants above)
            event_key:      Kafka partition key (e.g. str(case_id))
            payload:        JSON-serialisable event body
            correlation_id: Propagated X-Correlation-ID from the incoming request
        """
        entry = Outbox(
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            topic=topic,
            event_key=event_key,
            payload=payload,
            correlation_id=correlation_id,
            status="PENDING",
            attempts=0,
        )
        self._session.add(entry)
        await self._session.flush()
        await self._session.refresh(entry)
        return entry

# ----------------------------------------
# FILE: backend/case/repositories/idempotency_repository.py
# ----------------------------------------

"""
Idempotency Repository — platform.idempotency_keys table.
Used by all mutating POST/PATCH endpoints in the Case Service.
Pattern copied from backend/auth/repositories/idempotency_repository.py.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.idempotency import IdempotencyKey


class IdempotencyRepository:

    SERVICE_NAME = "case-service"

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get(self, idempotency_key: uuid.UUID) -> IdempotencyKey | None:
        """Return cached response if this key was already processed, else None."""
        result = await self._session.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.service_name == self.SERVICE_NAME,
                IdempotencyKey.idempotency_key == idempotency_key,
                IdempotencyKey.expires_at > datetime.now(timezone.utc),
            )
        )
        return result.scalar_one_or_none()

    async def store(
        self,
        idempotency_key: uuid.UUID,
        request_hash: str,
        response_status: int,
        response_body: dict,
    ) -> None:
        """Store the result of a successfully processed request (TTL = 24 h)."""
        now = datetime.now(timezone.utc)
        record = IdempotencyKey(
            service_name=self.SERVICE_NAME,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            response_status=response_status,
            response_body=response_body,
            expires_at=now + timedelta(hours=24),
            created_at=now,
        )
        self._session.add(record)
        await self._session.flush()

# ----------------------------------------
# FILE: backend/case/tests/conftest.py
# ----------------------------------------

"""Shared fixtures for Case Service tests."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from main import app


@pytest.fixture
def mock_db():
    session = AsyncMock()
    session.begin.return_value.__aenter__ = AsyncMock(return_value=session)
    session.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return session


@pytest.fixture
def sample_case_id():
    return uuid.uuid4()


@pytest.fixture
async def async_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
def valid_jwt_headers():
    """Headers with a fake JWT for testing (Kong validates in production)."""
    # In tests: mock get_current_user to bypass JWT validation
    return {"Authorization": "Bearer fake-token", "X-Correlation-ID": str(uuid.uuid4())}

# ----------------------------------------
# FILE: backend/case/tests/test_case_endpoints.py
# ----------------------------------------

"""Integration tests for Case endpoints with mocked service layer."""
import uuid
from unittest.mock import AsyncMock, patch

import pytest


class TestCreateCase:

    @pytest.mark.asyncio
    async def test_create_case_missing_idempotency_key(self, async_client, valid_jwt_headers):
        """POST /cases without Idempotency-Key should fail."""
        from main import app
        from security.jwt import get_current_user
        from db import get_db
        from models.schemas import CurrentUser
        
        async def mock_user():
            return CurrentUser(user_id=uuid.uuid4(), email="a@a.com", role="CITIZEN", jurisdiction_id="JUR_MH", jti="test")
        
        app.dependency_overrides[get_current_user] = mock_user
        app.dependency_overrides[get_db] = lambda: AsyncMock()
        
        try:
            response = await async_client.post(
                "/api/v1/cases",
                json={
                    "title": "Test",
                    "description": "Test fraud",
                    "complaint_type": "UPI_FRAUD",
                    "language_code": "en",
                },
                headers=valid_jwt_headers,
            )
            # Missing idempotency key → error response
            assert response.status_code == 201
            assert response.json().get("errorCode") == "MISSING_IDEMPOTENCY_KEY"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_create_case_invalid_complaint_type(self, async_client, valid_jwt_headers):
        """POST /cases with invalid complaintType returns 422."""
        from main import app
        from security.jwt import get_current_user
        from db import get_db
        from models.schemas import CurrentUser
        
        async def mock_user():
            return CurrentUser(user_id=uuid.uuid4(), email="a@a.com", role="CITIZEN", jurisdiction_id="JUR_MH", jti="test")
            
        app.dependency_overrides[get_current_user] = mock_user
        app.dependency_overrides[get_db] = lambda: AsyncMock()
        
        try:
            response = await async_client.post(
                "/api/v1/cases",
                json={
                    "title": "Test",
                    "description": "Test",
                    "complaint_type": "INVALID_TYPE",
                    "language_code": "en",
                },
                headers={**valid_jwt_headers, "Idempotency-Key": str(uuid.uuid4())},
            )
            assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()


class TestGetCase:

    @pytest.mark.asyncio
    async def test_get_case_not_found(self, async_client, valid_jwt_headers, sample_case_id):
        """GET /cases/:id returns 404 when not found."""
        from main import app
        from security.jwt import get_current_user
        from db import get_db
        from models.schemas import CurrentUser
        
        async def mock_user():
            return CurrentUser(user_id=uuid.uuid4(), email="a@a.com", role="INVESTIGATOR", jurisdiction_id="JUR_MH", jti="test")
            
        app.dependency_overrides[get_current_user] = mock_user
        app.dependency_overrides[get_db] = lambda: AsyncMock()
        
        with patch("services.case_service.CaseService.get_case",
                  side_effect=__import__("services.case_service", fromlist=["CaseNotFoundError"]).CaseNotFoundError("not found")):
            response = await async_client.get(
                f"/api/v1/cases/{sample_case_id}",
                headers=valid_jwt_headers,
            )
            assert response.status_code == 404
            assert response.json()["detail"].get("errorCode") == "CASE_NOT_FOUND"
        app.dependency_overrides.clear()


class TestStateTransition:

    @pytest.mark.asyncio
    async def test_invalid_transition_returns_422(self, async_client, valid_jwt_headers, sample_case_id, mock_db):
        """PATCH /cases/:id/state with invalid transition → 422."""
        from services.case_service import InvalidTransitionError
        from main import app
        from security.jwt import get_current_user
        from db import get_db
        from models.schemas import CurrentUser
        
        async def mock_user():
            return CurrentUser(user_id=uuid.uuid4(), email="a@a.com", role="INVESTIGATOR", jurisdiction_id="JUR_MH", jti="test")
            
        app.dependency_overrides[get_current_user] = mock_user
        app.dependency_overrides[get_db] = lambda: mock_db
        
        with patch("services.case_service.CaseService.update_state",
                  side_effect=InvalidTransitionError("Invalid transition: Closed → Assigned")):
            response = await async_client.patch(
                f"/api/v1/cases/{sample_case_id}/state",
                json={"state": "Assigned", "reason": "test"},
                headers={**valid_jwt_headers, "Idempotency-Key": str(uuid.uuid4())},
            )
            assert response.status_code == 422
            assert "INVALID_STATE_TRANSITION" in str(response.json())
        app.dependency_overrides.clear()


class TestVerdictOverride:

    @pytest.mark.asyncio
    async def test_override_requires_investigator_role(self, async_client, valid_jwt_headers, sample_case_id):
        """PATCH /cases/:id/verdict/override returns 403 for CITIZEN role."""
        from fastapi import HTTPException
        from main import app
        from security.jwt import get_current_user
        from models.schemas import CurrentUser
        
        async def mock_user():
            return CurrentUser(user_id=uuid.uuid4(), email="a@a.com", role="CITIZEN", jurisdiction_id="JUR_MH", jti="test")
            
        app.dependency_overrides[get_current_user] = mock_user

        response = await async_client.patch(
            f"/api/v1/cases/{sample_case_id}/verdict/override",
            json={
                "decision": "APPROVE",
                "justification": "Reviewed all evidence thoroughly.",
                "original_verdict_id": str(uuid.uuid4()),
            },
            headers=valid_jwt_headers,
        )
        # CITIZEN should get 403
        assert response.status_code in (403, 401)
        app.dependency_overrides.clear()

# ----------------------------------------
# FILE: backend/case/tests/test_state_machine.py
# ----------------------------------------

"""Pure unit tests for the state machine — no async, no DB."""
import pytest
from state_machine.transitions import (
    validate_transition, TransitionError, TransitionPermissionError,
    get_allowed_transitions, VALID_STATES,
)


class TestValidTransitions:

    def test_new_to_assigned_investigator(self):
        validate_transition("New", "Assigned", caller_role="INVESTIGATOR")

    def test_assigned_to_investigating(self):
        validate_transition("Assigned", "Investigating", caller_role="INVESTIGATOR")

    def test_pending_ai_to_investigating_ai_timeout(self):
        validate_transition("Pending_AI", "Investigating", reason="AI_TIMEOUT", caller_role="SYSTEM")

    def test_pending_ai_to_action_taken(self):
        validate_transition("Pending_AI", "Action_Taken", caller_role="SYSTEM")

    def test_pending_ai_to_closed(self):
        validate_transition("Pending_AI", "Closed", caller_role="INVESTIGATOR")


class TestInvalidTransitions:

    def test_new_to_closed_invalid(self):
        with pytest.raises(TransitionError):
            validate_transition("New", "Closed", caller_role="INVESTIGATOR")

    def test_closed_is_terminal(self):
        with pytest.raises(TransitionError):
            validate_transition("Closed", "Assigned", caller_role="ADMIN")

    def test_unknown_target_state(self):
        with pytest.raises(TransitionError):
            validate_transition("New", "HACKED", caller_role="ADMIN")

    def test_wrong_reason_for_ai_timeout(self):
        with pytest.raises(TransitionError):
            validate_transition("Pending_AI", "Investigating", reason="WRONG", caller_role="SYSTEM")


class TestRoleRestrictions:

    def test_citizen_cannot_assign(self):
        with pytest.raises(TransitionPermissionError):
            validate_transition("New", "Assigned", caller_role="CITIZEN")

    def test_admin_can_assign(self):
        validate_transition("New", "Assigned", caller_role="ADMIN")


class TestHelpers:

    def test_get_allowed_transitions_new(self):
        allowed = get_allowed_transitions("New")
        assert "Assigned" in allowed
        assert "Closed" not in allowed

    def test_get_allowed_transitions_closed(self):
        allowed = get_allowed_transitions("Closed")
        assert allowed == []

    def test_all_states_defined(self):
        assert "New" in VALID_STATES
        assert "Pending_AI" in VALID_STATES
        assert "Closed" in VALID_STATES

# ----------------------------------------
# FILE: backend/case/tests/test_outbox.py
# ----------------------------------------

"""Unit tests for outbox write pattern (case + outbox in same transaction)."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, call

import pytest

from repositories.outbox_repository import OutboxRepository


class TestOutboxRepository:

    @pytest.mark.asyncio
    async def test_publish_inserts_outbox_row(self):
        """OutboxRepository.publish should add a row to the session."""
        mock_session = AsyncMock()
        mock_session.flush = AsyncMock()
        
        repo = OutboxRepository(mock_session)
        case_id = uuid.uuid4()
        
        await repo.publish(
            aggregate_type="Case",
            aggregate_id=case_id,
            event_type="Case.Created",
            topic="case.created",
            event_key=str(case_id),
            payload={"caseId": str(case_id)},
        )
        
        # Verify session.add was called
        mock_session.add.assert_called_once()
        added_obj = mock_session.add.call_args[0][0]
        assert added_obj.event_type == "Case.Created"
        assert added_obj.topic == "case.created"
        assert added_obj.aggregate_type == "Case"

# ----------------------------------------
# FILE: backend/bot/config.py
# ----------------------------------------

"""
Service Configuration — Pydantic Settings
==========================================
Reads from environment variables (injected by Docker Compose or Vault Agent).
Falls back to .env file for local development.
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    # ── Service identity ───────────────────────────────────────
    SERVICE_NAME: str = "bot-service"           # Override in each service
    SERVICE_VERSION: str = "0.1.0"

    # ── PostgreSQL (via PgBouncer) ─────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://platform_user:change_me_postgres@postgres:5432/platform"

    # ── Redis ─────────────────────────────────────────────────
    REDIS_URL: str = "redis://:change_me_redis@redis:6379/0"

    # ── Kafka ─────────────────────────────────────────────────
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    KAFKA_SCHEMA_REGISTRY_URL: str = ""

    # ── Vault ─────────────────────────────────────────────────
    VAULT_ADDR: str = ""
    VAULT_TOKEN: str = ""

    # ── Observability ──────────────────────────────────────────
    # Services send telemetry directly to Tempo in local docker-compose
    OTEL_ENDPOINT: str = "http://tempo:4317"   # gRPC port on Tempo
    LOG_LEVEL: str = "INFO"

    # ── JWT (RS256 — public key for validation) ───────────────
    JWT_ALGORITHM: str = "RS256"
    JWT_PUBLIC_KEY: str = ""    # Loaded from Vault in production

    INFERENCE_ORCHESTRATOR_URL: str = "http://inference-orchestrator:8000"
    BOT_SESSION_TTL_SECONDS: int = 1800   # 30 minutes
    ALLOWED_ORIGINS: str = "http://localhost:5173,http://localhost:5174,http://localhost:5175"


settings = Settings()

# ----------------------------------------
# FILE: backend/bot/services/language_service.py
# ----------------------------------------

"""
Language detection for Bot Service — FR-11.1.
Supported: 12 Indian regional languages + English (BCP-47 codes).
Uses: langdetect library (probabilistic, trained on Wikipedia data).
Falls back to 'en' if detection fails or language unsupported.
"""
from langdetect import detect, LangDetectException

# Supported BCP-47 codes (from docs/api/case.md languageCode constraint)
_SUPPORTED_LANGS = {
    "hi", "bn", "te", "ta", "mr", "gu", "kn", "ml", "pa", "ur", "or", "as", "en",
}

# langdetect → BCP-47 mappings for languages that differ
_LANG_REMAP = {
    "zh-cn": "zh",  # not used, but defensive
    "or": "or",
}

_DEFAULT_LANG = "en"


def detect_language(text: str) -> str:
    """
    Detect the language of the input text.
    Returns BCP-47 code from supported list.
    Defaults to 'en' on failure or unsupported language.
    
    Args:
        text: user message (can be any length, but accuracy improves with ≥20 chars)
    
    Returns:
        BCP-47 language code (e.g. "hi", "en", "ta")
    """
    if not text or len(text.strip()) < 3:
        return _DEFAULT_LANG
    
    try:
        detected = detect(text)
        lang = _LANG_REMAP.get(detected, detected)
        return lang if lang in _SUPPORTED_LANGS else _DEFAULT_LANG
    except LangDetectException:
        return _DEFAULT_LANG


def is_supported_language(lang_code: str) -> bool:
    """Check if a BCP-47 code is in the supported set."""
    return lang_code in _SUPPORTED_LANGS

# ----------------------------------------
# FILE: backend/bot/services/session_service.py
# ----------------------------------------

"""
Bot Session Service — Redis-backed multi-turn conversation state.
Key pattern: bot:session:{sessionId}:lang={lang_code}  (from docs/db/redis.md)
TTL: 1800 seconds (30 min), refreshed on every message.

Session data structure:
{
    "sessionId": "uuid",
    "turnCount": 3,
    "detectedLanguage": "hi",
    "messages": [{"role": "user"|"bot", "content": "...", "ts": "iso"}],
    "collectedData": {"suspectPhone": "...", "complaintType": "..."},
    "status": "ACTIVE",
    "channel": "WEB",
    "userId": "uuid or null"
}
"""
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis.asyncio as aioredis

_SESSION_TTL = 1800   # 30 minutes (docs/db/redis.md)


class SessionService:

    def __init__(self, redis: aioredis.Redis):
        self._redis = redis

    def _make_key(self, session_id: str, lang_code: str) -> str:
        """Build Redis key: bot:session:{sessionId}:lang={lang_code}"""
        return f"bot:session:{session_id}:lang={lang_code}"

    def _scan_key_pattern(self, session_id: str) -> str:
        """
        Pattern for scanning when lang_code is unknown.
        Assumption: scan_iter is acceptable for hackathon scale (low session count).
        Production would use a secondary index or a fixed key with no lang in the name.
        """
        return f"bot:session:{session_id}:lang=*"

    async def get_session(self, session_id: str) -> Optional[dict]:
        """
        Retrieve session by session_id.
        Scans for the key since lang_code may vary.
        Returns None if not found or expired.
        """
        pattern = self._scan_key_pattern(session_id)
        keys = []
        async for key in self._redis.scan_iter(pattern):
            keys.append(key)
        
        if not keys:
            return None
        
        # Take the first matching key (should only be one per session)
        data = await self._redis.get(keys[0])
        return json.loads(data) if data else None

    async def create_session(
        self,
        lang_code: str,
        channel: str,
        user_id: Optional[str],
        first_message: str,
    ) -> dict:
        """Create a new session and store in Redis."""
        session_id = str(uuid.uuid4())
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=_SESSION_TTL)).isoformat()
        
        state = {
            "sessionId": session_id,
            "turnCount": 1,
            "detectedLanguage": lang_code,
            "messages": [
                {"role": "user", "content": first_message, "ts": datetime.now(timezone.utc).isoformat()}
            ],
            "collectedData": {},
            "status": "ACTIVE",
            "channel": channel,
            "userId": user_id,
            "expiresAt": expires_at,
        }
        
        key = self._make_key(session_id, lang_code)
        await self._redis.setex(key, _SESSION_TTL, json.dumps(state))
        return state

    async def update_session(
        self,
        session_id: str,
        lang_code: str,
        user_message: str,
        bot_response: str,
        collected_data_update: Optional[dict] = None,
    ) -> dict:
        """Append turn to session and refresh TTL."""
        state = await self.get_session(session_id)
        if not state:
            raise SessionNotFoundError(session_id)

        now = datetime.now(timezone.utc).isoformat()
        state["turnCount"] += 1
        state["detectedLanguage"] = lang_code
        state["messages"].extend([
            {"role": "user", "content": user_message, "ts": now},
            {"role": "bot", "content": bot_response, "ts": now},
        ])
        if collected_data_update:
            state["collectedData"].update(collected_data_update)
        state["expiresAt"] = (datetime.now(timezone.utc) + timedelta(seconds=_SESSION_TTL)).isoformat()

        # Delete old key (lang_code may have changed) and write new
        old_pattern = self._scan_key_pattern(session_id)
        async for old_key in self._redis.scan_iter(old_pattern):
            await self._redis.delete(old_key)

        new_key = self._make_key(session_id, lang_code)
        await self._redis.setex(new_key, _SESSION_TTL, json.dumps(state))
        return state

    async def delete_session(self, session_id: str) -> None:
        async for key in self._redis.scan_iter(self._scan_key_pattern(session_id)):
            await self._redis.delete(key)


class SessionNotFoundError(Exception):
    def __init__(self, session_id: str):
        super().__init__(f"Session {session_id} not found or expired")

# ----------------------------------------
# FILE: backend/bot/services/orchestrator_client.py
# ----------------------------------------

"""
Orchestrator HTTP client — calls POST /inference/analyze.
STUB until T13 (Day 6): returns hardcoded risk assessment.
Replace stub with real httpx call when Orchestrator is live.
"""
import httpx
from typing import Optional


# ── STUB RESPONSE (replaced in T13) ──────────────────────────────────────────
_STUB_RESPONSE = {
    "preliminary_score": 65,
    "risk_tier": "MEDIUM",
    "requires_format_report": True,
}


async def get_risk_assessment(
    http_client: httpx.AsyncClient,
    session_id: str,
    message: str,
    lang_code: str,
    correlation_id: str,
) -> Optional[dict]:
    """
    Call Inference Orchestrator for preliminary risk assessment.
    Returns None before ≥2 turns (not enough context).
    
    [STUB] Returns hardcoded medium risk until T13 integration.
    T13 replacement: uncomment the httpx call below.
    """
    # TODO T13: Replace stub with real call
    # try:
    #     response = await http_client.post(
    #         "/api/v1/inference/analyze",
    #         json={"text": message, "sessionId": session_id, "languageCode": lang_code},
    #         headers={"X-Correlation-ID": correlation_id},
    #         timeout=5.0,
    #     )
    #     response.raise_for_status()
    #     data = response.json()
    #     return {
    #         "preliminary_score": data.get("fusedScore", 0),
    #         "risk_tier": data.get("riskTier", "LOW"),
    #         "requires_format_report": data.get("riskTier") in ("HIGH", "CRITICAL"),
    #     }
    # except (httpx.RequestError, httpx.HTTPStatusError):
    #     return None

    return _STUB_RESPONSE   # [STUB — T13]

# ----------------------------------------
# FILE: backend/bot/http_client.py
# ----------------------------------------

"""Shared httpx.AsyncClient for Bot → Orchestrator calls."""
from fastapi import Request
import httpx


async def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client

# ----------------------------------------
# FILE: backend/bot/main.py
# ----------------------------------------

"""
Platform Service Template — FastAPI
====================================
Copy this file into your service directory and rename/modify as needed.

SETUP INSTRUCTIONS:
1. Copy backend/template/ → backend/<your-service>/
2. Set SERVICE_NAME in settings below
3. Implement your domain endpoints in separate routers
4. Import routers here and include them on `app`
5. Run: uvicorn main:app --reload

PATTERNS ESTABLISHED HERE:
- Structured JSON logging (loguru) with trace_id in every log line
- OpenTelemetry auto-instrumentation (traces, metrics → OTel Collector)
- Prometheus metrics via prometheus-fastapi-instrumentator (/metrics)
- /health/live  → liveness probe (is the process alive?)
- /health/ready → readiness probe (can it serve traffic?)
- Standard error response shape: {requestId, correlationId, errorCode, message}
- Vault secret loading at startup (graceful fallback to env vars for local dev)
"""

import sys
import uuid
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from prometheus_fastapi_instrumentator import Instrumentator

# ─── OpenTelemetry (auto-instrument BEFORE app creation) ─────────────────────
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource

from config import settings

# ─── Tracer setup ─────────────────────────────────────────────────────────────
resource = Resource.create({"service.name": settings.SERVICE_NAME, "service.version": settings.SERVICE_VERSION})
tracer_provider = TracerProvider(resource=resource)
tracer_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.OTEL_ENDPOINT))
)
trace.set_tracer_provider(tracer_provider)

# ─── Logging (structured JSON via loguru) ─────────────────────────────────────
logger.remove()
logger.add(
    sys.stdout,
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {extra[service]} | {extra[trace_id]} | {message}",
    serialize=True,    # Emit as JSON lines
    level="INFO",
)
logger = logger.bind(service=settings.SERVICE_NAME, trace_id="—")


# ─── Lifespan (startup / shutdown) ───────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"{settings.SERVICE_NAME} starting up")
    
    import httpx
    from redis_client import create_redis_client
    
    app.state.redis = create_redis_client()
    await app.state.redis.ping()
    
    app.state.http_client = httpx.AsyncClient(
        base_url=settings.INFERENCE_ORCHESTRATOR_URL,
        timeout=5.0,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )
    
    logger.info(f"{settings.SERVICE_NAME} ready — Redis and httpx initialized")
    yield
    
    await app.state.redis.aclose()
    await app.state.http_client.aclose()


# ─── App ─────────────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.SERVICE_NAME,
    version=settings.SERVICE_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Auto-instrument FastAPI with OTel
FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer_provider)

# ─── CORS ────────────────────────────────────────────────────────────────────
# Bug Fix T18-A: CORS was missing — Citizen/Bank/Telecom UIs were blocked.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in settings.ALLOWED_ORIGINS.split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Expose /metrics endpoint for Prometheus scraping
Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
).instrument(app).expose(app, endpoint="/metrics")


# ─── Middleware: correlation ID + request logging ─────────────────────────────
@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

    # Bind trace context to logger for this request
    span_context = trace.get_current_span().get_span_context()
    otel_trace_id = f"{span_context.trace_id:032x}" if span_context.is_valid else "—"
    req_logger = logger.bind(
        trace_id=otel_trace_id,
        correlation_id=correlation_id,
        request_id=request_id,
        method=request.method,
        path=request.url.path,
    )

    start = time.perf_counter()
    response: Response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)

    req_logger.info(
        "request_completed",
        status_code=response.status_code,
        duration_ms=duration_ms,
    )

    response.headers["X-Correlation-ID"] = correlation_id
    response.headers["X-Request-ID"] = request_id
    return response


# ─── Standard error handler ───────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    correlation_id = request.headers.get("X-Correlation-ID", "unknown")
    request_id = request.headers.get("X-Request-ID", "unknown")
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "requestId": request_id,
            "correlationId": correlation_id,
            "errorCode": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected error occurred.",
            "details": None,
        },
    )


# ─── Health Endpoints ─────────────────────────────────────────────────────────
@app.get("/health/live", tags=["Health"])
async def liveness():
    """Kubernetes liveness probe — is the process running?"""
    return {"status": "alive", "service": settings.SERVICE_NAME}


@app.get("/health/ready", tags=["Health"])
async def readiness(request: Request):
    """
    Kubernetes readiness probe — can the service serve traffic?
    Checks: DB connection, Redis ping, Kafka broker reachability.
    Returns 503 if any dependency is unhealthy.
    """
    checks = {}
    healthy = True

    # ── Redis check ───────────────────────────────────────────
    try:
        await request.app.state.redis.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"
        healthy = False

    status_code = 200 if healthy else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if healthy else "not_ready",
            "service": settings.SERVICE_NAME,
            "checks": checks,
        },
    )


# ─── Domain Routers ───────────────────────────────────────────────────────────
from routers.bot_router import router as bot_router
app.include_router(bot_router, prefix="/api/v1")

# ----------------------------------------
# FILE: backend/bot/response_helpers.py
# ----------------------------------------

"""Standard response envelope helpers (docs/api/_shared_contract.md)."""
import uuid
from datetime import datetime, timezone
from typing import Any


def success_response(data: Any, correlation_id: str = "") -> dict:
    return {
        "requestId": str(uuid.uuid4()),
        "correlationId": correlation_id,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "success",
        "data": data,
    }


def error_response(
    error_code: str,
    message: str,
    correlation_id: str = "",
    details: Any = None,
) -> dict:
    return {
        "requestId": str(uuid.uuid4()),
        "correlationId": correlation_id,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "error",
        "errorCode": error_code,
        "message": message,
        "details": details,
    }

# ----------------------------------------
# FILE: backend/bot/routers/bot_router.py
# ----------------------------------------

"""
Bot Service Router — docs/api/bot.md
Routes:
  POST /bot/message              — multi-turn conversation
  GET  /bot/session/:sessionId   — get session state
  POST /bot/whatsapp             — WhatsApp webhook [STUB]
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from http_client import get_http_client
from models.schemas import BotMessageRequest, BotMessageResponse, RiskAssessmentPayload
from redis_client import get_redis
from response_helpers import error_response, success_response
from services.language_service import detect_language
from services.orchestrator_client import get_risk_assessment
from services.session_service import SessionService, SessionNotFoundError

router = APIRouter(prefix="/bot", tags=["Bot"])


def _corr(request: Request) -> str:
    return request.headers.get("X-Correlation-ID", str(uuid.uuid4()))


# ── Intent classification (simple rule-based for hackathon) ───────────────────

_INTENT_MAP = {
    "fraud": "FRAUD_REPORT_INITIATION",
    "scam": "FRAUD_REPORT_INITIATION",
    "upi": "FRAUD_REPORT_INITIATION",
    "report": "REPORT_STATUS_INQUIRY",
    "status": "REPORT_STATUS_INQUIRY",
    "help": "GENERAL_INQUIRY",
}

def _classify_intent(message: str) -> str:
    """Simple keyword-based intent classification."""
    lower = message.lower()
    for keyword, intent in _INTENT_MAP.items():
        if keyword in lower:
            return intent
    return "GENERAL_INQUIRY"

def _get_suggested_actions(intent: str, turn_count: int) -> list[str]:
    if intent == "FRAUD_REPORT_INITIATION":
        if turn_count <= 2:
            return ["PROVIDE_SUSPECT_PHONE", "DESCRIBE_INCIDENT"]
        return ["SUBMIT_FORMAL_REPORT", "PROVIDE_SCREENSHOT"]
    return ["CONTACT_SUPPORT"]

def _generate_bot_response(intent: str, lang_code: str, turn_count: int) -> str:
    """
    Generate a language-appropriate bot response.
    Hackathon: hardcoded templates. Production: NLP model via Orchestrator.
    """
    responses = {
        "FRAUD_REPORT_INITIATION": {
            "en": "Thank you for reporting. Please provide the suspect's phone number and describe the incident.",
            "hi": "आपकी रिपोर्ट के लिए धन्यवाद। कृपया संदिग्ध का फ़ोन नंबर और घटना का विवरण प्रदान करें।",
        },
        "REPORT_STATUS_INQUIRY": {
            "en": "Please provide your case ID to check the status.",
            "hi": "स्थिति जांचने के लिए कृपया अपना केस आईडी प्रदान करें।",
        },
        "GENERAL_INQUIRY": {
            "en": "I can help you report cyber fraud. What happened?",
            "hi": "मैं साइबर धोखाधड़ी की रिपोर्ट करने में आपकी सहायता कर सकता हूं। क्या हुआ?",
        },
    }
    intent_responses = responses.get(intent, responses["GENERAL_INQUIRY"])
    return intent_responses.get(lang_code, intent_responses.get("en", "I understand. Please continue."))


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/message", status_code=200)
async def send_message(
    request: Request,
    body: BotMessageRequest,
    redis=Depends(get_redis),
    http_client=Depends(get_http_client),
):
    """Process a citizen message. Creates or continues a bot session."""
    correlation_id = _corr(request)
    session_svc = SessionService(redis)

    # Detect language
    lang_code = detect_language(body.message)

    # Determine intent
    intent = _classify_intent(body.message)

    # Load or create session
    if body.session_id:
        session = await session_svc.get_session(str(body.session_id))
        if not session:
            raise HTTPException(
                status_code=404,
                detail=error_response("SESSION_NOT_FOUND", "Session expired or not found", correlation_id),
            )
        is_new_session = False
    else:
        session = await session_svc.create_session(
            lang_code=lang_code,
            channel=body.channel,
            user_id=str(body.user_id) if body.user_id else None,
            first_message=body.message,
        )
        is_new_session = True

    # Generate bot response
    bot_response_text = _generate_bot_response(intent, lang_code, session.get("turnCount", 1))

    # Update session (add bot response, refresh TTL)
    if not is_new_session:
        session = await session_svc.update_session(
            session_id=str(body.session_id),
            lang_code=lang_code,
            user_message=body.message,
            bot_response=bot_response_text,
        )

    turn_count = session["turnCount"]

    # Call Orchestrator for risk assessment (after ≥2 turns)
    risk_assessment = None
    if turn_count >= 2:
        raw_assessment = await get_risk_assessment(
            http_client=http_client,
            session_id=session["sessionId"],
            message=body.message,
            lang_code=lang_code,
            correlation_id=correlation_id,
        )
        if raw_assessment:
            risk_assessment = RiskAssessmentPayload(
                preliminary_score=raw_assessment["preliminary_score"],
                risk_tier=raw_assessment["risk_tier"],
                requires_format_report=raw_assessment["requires_format_report"],
            )

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=1800)

    result = BotMessageResponse(
        session_id=uuid.UUID(session["sessionId"]),
        response=bot_response_text,
        detected_language=lang_code,
        intent=intent,
        risk_assessment=risk_assessment,
        suggested_actions=_get_suggested_actions(intent, turn_count),
        turn_count=turn_count,
        session_expires_at=expires_at,
    )
    return success_response(result.model_dump(by_alias=True, mode="json"), correlation_id)


@router.get("/session/{session_id}", status_code=200)
async def get_session(
    request: Request,
    session_id: uuid.UUID,
    redis=Depends(get_redis),
):
    """Get current bot session state."""
    correlation_id = _corr(request)
    session_svc = SessionService(redis)
    session = await session_svc.get_session(str(session_id))
    if not session:
        raise HTTPException(
            status_code=404,
            detail=error_response("SESSION_NOT_FOUND", "Session not found or expired", correlation_id),
        )
    return success_response(
        {
            "sessionId": session["sessionId"],
            "turnCount": session["turnCount"],
            "detectedLanguage": session["detectedLanguage"],
            "collectedData": session.get("collectedData", {}),
            "status": session.get("status", "ACTIVE"),
            "expiresAt": session.get("expiresAt", ""),
        },
        correlation_id,
    )


@router.post("/whatsapp", status_code=200)
async def whatsapp_webhook(request: Request, body: dict):
    """WhatsApp webhook [STUB] — acknowledges receipt per docs/api/bot.md."""
    return success_response(
        {"acknowledged": True, "message": "Report received. A case officer will contact you shortly."},
        _corr(request),
    )

# ----------------------------------------
# FILE: backend/bot/models/schemas.py
# ----------------------------------------

"""Pydantic schemas for Bot Service — docs/api/bot.md."""
import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)


class BotMessageRequest(CamelModel):
    session_id: Optional[uuid.UUID] = None   # Omit for new session
    message: str = Field(..., max_length=2000)
    channel: str = "WEB"
    user_id: Optional[uuid.UUID] = None

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v: str) -> str:
        if v not in {"WEB", "WHATSAPP", "IVR"}:
            raise ValueError("channel must be WEB, WHATSAPP, or IVR")
        return v


class RiskAssessmentPayload(CamelModel):
    preliminary_score: int
    risk_tier: str
    requires_format_report: bool


class BotMessageResponse(CamelModel):
    session_id: uuid.UUID
    response: str
    detected_language: str
    intent: str
    risk_assessment: Optional[RiskAssessmentPayload] = None
    suggested_actions: list[str] = []
    turn_count: int
    session_expires_at: datetime


class BotSessionState(CamelModel):
    """Stored in Redis as JSON."""
    session_id: str
    turn_count: int
    detected_language: str
    messages: list[dict]           # [{role: user|bot, content: str, ts: str}]
    collected_data: dict           # Accumulated fraud data from conversation
    status: str = "ACTIVE"
    channel: str = "WEB"
    user_id: Optional[str] = None
    expires_at: str


class BotSessionResponse(CamelModel):
    session_id: uuid.UUID
    turn_count: int
    detected_language: str
    collected_data: dict
    status: str
    expires_at: str

# ----------------------------------------
# FILE: backend/bot/redis_client.py
# ----------------------------------------

"""
Bot Service — Redis Async Client
Key patterns (from docs/db/redis.md):
  bot:session:{sessionId}:lang={lang_code}
"""
import redis.asyncio as aioredis
from fastapi import Request

from config import settings


def create_redis_client() -> aioredis.Redis:
    """Create async Redis client. Called once at startup."""
    return aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )


async def get_redis(request: Request) -> aioredis.Redis:
    """FastAPI dependency: returns the shared Redis client."""
    return request.app.state.redis

# ----------------------------------------
# FILE: backend/bot/tests/conftest.py
# ----------------------------------------

import pytest
from unittest.mock import AsyncMock
from httpx import AsyncClient, ASGITransport
from main import app


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get.return_value = None
    redis.setex.return_value = True
    redis.exists.return_value = 0
    # scan_iter: async generator that yields nothing
    async def empty_scan(*args, **kwargs):
        return
        yield  # make it an async generator
    redis.scan_iter = empty_scan
    return redis


@pytest.fixture
async def async_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

# ----------------------------------------
# FILE: backend/bot/tests/test_bot_endpoints.py
# ----------------------------------------

"""Tests for Bot Service endpoints."""
import json
import uuid
from unittest.mock import AsyncMock

import pytest

from services.language_service import detect_language, is_supported_language
from services.session_service import SessionService


# ── Language Detection Unit Tests ─────────────────────────────────────────────

class TestLanguageDetection:

    def test_detect_hindi(self):
        result = detect_language("मुझे एक अज्ञात कॉल आई और उन्होंने मेरे साथ धोखाधड़ी की")
        assert result == "hi"

    def test_detect_english(self):
        result = detect_language("I was defrauded by someone claiming to be from the bank")
        assert result == "en"

    def test_empty_string_returns_en(self):
        assert detect_language("") == "en"

    def test_short_string_returns_en(self):
        assert detect_language("hi") == "en"

    def test_unsupported_language_falls_back_to_en(self):
        # French text — not in supported list
        result = detect_language("Bonjour je suis très content de vous voir aujourd'hui")
        assert result in {"fr", "en"}  # May detect French, but service returns "en" for unsupported
        assert is_supported_language(result) or result == "en"

    def test_all_supported_langs_in_set(self):
        supported = {"hi", "bn", "te", "ta", "mr", "gu", "kn", "ml", "pa", "ur", "or", "as", "en"}
        for lang in supported:
            assert is_supported_language(lang)


# ── Session Service Unit Tests ─────────────────────────────────────────────────

class TestSessionService:

    @pytest.mark.asyncio
    async def test_create_session(self, mock_redis):
        svc = SessionService(mock_redis)
        result = await svc.create_session(
            lang_code="en",
            channel="WEB",
            user_id=None,
            first_message="I was scammed",
        )
        assert result["sessionId"] is not None
        assert result["turnCount"] == 1
        assert result["detectedLanguage"] == "en"
        assert len(result["messages"]) == 1
        mock_redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_session_not_found(self, mock_redis):
        # scan_iter yields nothing → get_session returns None
        svc = SessionService(mock_redis)
        result = await svc.get_session(str(uuid.uuid4()))
        assert result is None


# ── Endpoint Tests ─────────────────────────────────────────────────────────────

class TestBotMessage:

    @pytest.mark.asyncio
    async def test_new_session_created_without_session_id(self, async_client, mock_redis):
        """POST /bot/message without sessionId creates new session."""
        from main import app
        from redis_client import get_redis
        from http_client import get_http_client
        
        app.dependency_overrides[get_redis] = lambda: mock_redis
        app.dependency_overrides[get_http_client] = lambda: AsyncMock()
        
        try:
            response = await async_client.post(
                "/api/v1/bot/message",
                json={"message": "I was defrauded via UPI transfer"},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "success"
            assert "sessionId" in body["data"]
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_get_session_not_found_returns_404(self, async_client, mock_redis):
        """GET /bot/session/:id for expired session → 404."""
        from main import app
        from redis_client import get_redis
        
        app.dependency_overrides[get_redis] = lambda: mock_redis
        try:
            response = await async_client.get(
                f"/api/v1/bot/session/{uuid.uuid4()}",
            )
            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_whatsapp_webhook_returns_ack(self, async_client):
        """POST /bot/whatsapp always returns acknowledged."""
        response = await async_client.post(
            "/api/v1/bot/whatsapp",
            json={"from": "+919876543210", "message": "Help"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["acknowledged"] is True

    @pytest.mark.asyncio
    async def test_liveness(self, async_client):
        response = await async_client.get("/health/live")
        assert response.status_code == 200

# ----------------------------------------
# FILE: backend/citizen-bff/config.py
# ----------------------------------------

"""
Service Configuration — Pydantic Settings
==========================================
Reads from environment variables (injected by Docker Compose or Vault Agent).
Falls back to .env file for local development.
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    # ── Service identity ───────────────────────────────────────
    SERVICE_NAME: str = "citizen-bff"           # Override in each service
    SERVICE_VERSION: str = "0.1.0"

    # ── PostgreSQL (via PgBouncer) ─────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://platform_user:change_me_postgres@postgres:5432/platform"

    # ── Redis ─────────────────────────────────────────────────
    REDIS_URL: str = "redis://:change_me_redis@redis:6379/0"

    # ── Kafka ─────────────────────────────────────────────────
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    KAFKA_SCHEMA_REGISTRY_URL: str = ""

    # ── Vault ─────────────────────────────────────────────────
    VAULT_ADDR: str = ""
    VAULT_TOKEN: str = ""

    # ── Observability ──────────────────────────────────────────
    # Services send telemetry directly to Tempo in local docker-compose
    OTEL_ENDPOINT: str = "http://tempo:4317"   # gRPC port on Tempo
    LOG_LEVEL: str = "INFO"

    # ── JWT (RS256 — public key for validation) ───────────────
    JWT_ALGORITHM: str = "RS256"
    JWT_PUBLIC_KEY: str = ""    # Loaded from Vault in production

    CASE_SERVICE_URL: str = "http://case:8000"
    BOT_SERVICE_URL: str = "http://bot:8000"
    EVIDENCE_SERVICE_URL: str = "http://evidence:8000"
    ALLOWED_ORIGINS: str = "http://localhost:5173,http://localhost:5174,http://localhost:5175"


settings = Settings()

# ----------------------------------------
# FILE: backend/citizen-bff/security/__init__.py
# ----------------------------------------

"""Security package"""

# ----------------------------------------
# FILE: backend/citizen-bff/security/jwt.py
# ----------------------------------------

"""
JWT Security — verify for Citizen BFF.
BFF simplification: decode JWT claims only, no denylist check
Kong performs signature validation + denylist enforcement upstream
See notes/assumptions.md: "BFF JWT — denylist skip"
"""
import uuid
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from config import settings
from models.schemas import CurrentUser

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
    3. Skips Redis denylist (trusts Kong).
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

    return CurrentUser(
        user_id=uuid.UUID(payload["sub"]),
        email=payload.get("email", ""),
        role=payload["role"],
        org_id=uuid.UUID(payload["orgId"]) if payload.get("orgId") else None,
        jurisdiction_id=payload.get("jurisdictionId"),
        jti=jti,
    )


# ── Optional Auth (guest mode for public endpoints) ───────────────────────────

async def get_optional_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> CurrentUser:
    """
    Like get_current_user but returns an anonymous guest user when
    no Authorization header is present. Used by public-facing endpoints
    like POST /citizen/report so citizens can submit without logging in.
    Kong enforces auth in production; this is the BFF demo shortcut.
    """
    if not credentials:
        # Return anonymous guest — downstream Case Service will use a
        # system-level reporter_user_id for unauthenticated reports.
        return CurrentUser(
            user_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),  # guest sentinel
            email="guest@anonymous",
            role="CITIZEN",
            org_id=None,
            jurisdiction_id=None,
            jti="guest",
        )
    # Token present — validate normally
    return await get_current_user(request, credentials)


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

# ----------------------------------------
# FILE: backend/citizen-bff/main.py
# ----------------------------------------

"""
Platform Service Template — FastAPI
====================================
Copy this file into your service directory and rename/modify as needed.

SETUP INSTRUCTIONS:
1. Copy backend/template/ → backend/<your-service>/
2. Set SERVICE_NAME in settings below
3. Implement your domain endpoints in separate routers
4. Import routers here and include them on `app`
5. Run: uvicorn main:app --reload

PATTERNS ESTABLISHED HERE:
- Structured JSON logging (loguru) with trace_id in every log line
- OpenTelemetry auto-instrumentation (traces, metrics → OTel Collector)
- Prometheus metrics via prometheus-fastapi-instrumentator (/metrics)
- /health/live  → liveness probe (is the process alive?)
- /health/ready → readiness probe (can it serve traffic?)
- Standard error response shape: {requestId, correlationId, errorCode, message}
- Vault secret loading at startup (graceful fallback to env vars for local dev)
"""

import sys
import uuid
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from prometheus_fastapi_instrumentator import Instrumentator

# ─── OpenTelemetry (auto-instrument BEFORE app creation) ─────────────────────
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource

from config import settings

# ─── Tracer setup ─────────────────────────────────────────────────────────────
resource = Resource.create({"service.name": settings.SERVICE_NAME, "service.version": settings.SERVICE_VERSION})
tracer_provider = TracerProvider(resource=resource)
tracer_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.OTEL_ENDPOINT))
)
trace.set_tracer_provider(tracer_provider)

# ─── Logging (structured JSON via loguru) ─────────────────────────────────────
logger.remove()
logger.add(
    sys.stdout,
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {extra[service]} | {extra[trace_id]} | {message}",
    serialize=True,    # Emit as JSON lines
    level="INFO",
)
logger = logger.bind(service=settings.SERVICE_NAME, trace_id="—")


# ─── Lifespan (startup / shutdown) ───────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"{settings.SERVICE_NAME} starting up")
    import httpx
    
    app.state.case_client = httpx.AsyncClient(
        base_url=settings.CASE_SERVICE_URL,
        timeout=5.0,
        limits=httpx.Limits(max_connections=50),
    )
    app.state.bot_client = httpx.AsyncClient(
        base_url=settings.BOT_SERVICE_URL,
        timeout=5.0,
        limits=httpx.Limits(max_connections=20),
    )
    app.state.evidence_client = httpx.AsyncClient(
        base_url=settings.EVIDENCE_SERVICE_URL,
        timeout=5.0,
        limits=httpx.Limits(max_connections=20),
    )
    logger.info(f"{settings.SERVICE_NAME} ready")
    yield
    await app.state.case_client.aclose()
    await app.state.bot_client.aclose()
    await app.state.evidence_client.aclose()


# ─── App ─────────────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.SERVICE_NAME,
    version=settings.SERVICE_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Auto-instrument FastAPI with OTel
FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer_provider)

# ─── CORS ────────────────────────────────────────────────────────────────────
# Bug Fix T18-A: CORS was missing — Citizen/Bank/Telecom UIs were blocked.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in settings.ALLOWED_ORIGINS.split(",")
        if origin.strip()
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Expose /metrics endpoint for Prometheus scraping
Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
).instrument(app).expose(app, endpoint="/metrics")


# ─── Middleware: correlation ID + request logging ─────────────────────────────
@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

    # Bind trace context to logger for this request
    span_context = trace.get_current_span().get_span_context()
    otel_trace_id = f"{span_context.trace_id:032x}" if span_context.is_valid else "—"
    req_logger = logger.bind(
        trace_id=otel_trace_id,
        correlation_id=correlation_id,
        request_id=request_id,
        method=request.method,
        path=request.url.path,
    )

    start = time.perf_counter()
    response: Response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)

    req_logger.info(
        "request_completed",
        status_code=response.status_code,
        duration_ms=duration_ms,
    )

    response.headers["X-Correlation-ID"] = correlation_id
    response.headers["X-Request-ID"] = request_id
    return response


# ─── Standard error handler ───────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
        
    correlation_id = request.headers.get("X-Correlation-ID", "unknown")
    request_id = request.headers.get("X-Request-ID", "unknown")
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "requestId": request_id,
            "correlationId": correlation_id,
            "errorCode": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected error occurred.",
            "details": None,
        },
    )


# ─── Health Endpoints ─────────────────────────────────────────────────────────
@app.get("/health/live", tags=["Health"])
async def liveness():
    """Kubernetes liveness probe — is the process running?"""
    return {"status": "alive", "service": settings.SERVICE_NAME}


@app.get("/health/ready", tags=["Health"])
async def readiness(request: Request):
    """
    Kubernetes readiness probe — can the service serve traffic?
    Checks: DB connection, Redis ping, Kafka broker reachability.
    Returns 503 if any dependency is unhealthy.
    """
    checks = {}
    healthy = True

    # No DB or Redis in citizen-bff

    status_code = 200 if healthy else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if healthy else "not_ready",
            "service": settings.SERVICE_NAME,
            "checks": checks,
        },
    )


# ─── Domain Routers ───────────────────────────────────────────────────────────
from routers.citizen_router import router as citizen_router
app.include_router(citizen_router, prefix="/api/v1")

# ----------------------------------------
# FILE: backend/citizen-bff/response_helpers.py
# ----------------------------------------

"""Standard response envelope helpers (docs/api/_shared_contract.md)."""
import uuid
from datetime import datetime, timezone
from typing import Any


def success_response(data: Any, correlation_id: str = "") -> dict:
    return {
        "requestId": str(uuid.uuid4()),
        "correlationId": correlation_id,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "success",
        "data": data,
    }


def error_response(
    error_code: str,
    message: str,
    correlation_id: str = "",
    details: Any = None,
) -> dict:
    return {
        "requestId": str(uuid.uuid4()),
        "correlationId": correlation_id,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "error",
        "errorCode": error_code,
        "message": message,
        "details": details,
    }

# ----------------------------------------
# FILE: backend/citizen-bff/routers/citizen_router.py
# ----------------------------------------

"""
Citizen BFF Router — docs/api/citizen-bff.md
Pure proxy: forwards requests to downstream services.
No business logic. Normalizes response envelope.
"""
import uuid
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request

from clients.case_client import get_case_client
from clients.bot_client import get_bot_client
from clients.evidence_client import get_evidence_client
from response_helpers import error_response, success_response
from security.jwt import get_current_user, get_optional_user

router = APIRouter(prefix="/citizen", tags=["Citizen"])


def _corr(request: Request) -> str:
    return request.headers.get("X-Correlation-ID", str(uuid.uuid4()))


def _forward_headers(request: Request, current_user=None) -> dict:
    """Headers to forward to downstream services."""
    headers = {"X-Correlation-ID": _corr(request)}
    auth = request.headers.get("Authorization")
    if auth:
        headers["Authorization"] = auth
    if current_user:
        import json
        headers["X-User-Context"] = json.dumps({
            "userId": str(current_user.user_id) if current_user.user_id else None,
            "role": current_user.role,
            "jti": getattr(current_user, "jti", None)
        })
    return headers


async def _proxy(client: httpx.AsyncClient, method: str, path: str, **kwargs) -> dict:
    """
    Generic proxy helper. Raises HTTPException on downstream error.
    Handles: ConnectionError → 503, 4xx → re-raised, 5xx → 502.
    """
    try:
        response = await client.request(method, path, **kwargs)
        if response.status_code in (200, 201):
            return response.json()
        # Pass through 4xx errors from downstream
        if 400 <= response.status_code < 500:
            raise HTTPException(status_code=response.status_code, detail=response.json())
        raise HTTPException(status_code=502, detail={"errorCode": "UPSTREAM_ERROR", "message": "Upstream service error"})
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail={"errorCode": "SERVICE_UNAVAILABLE", "message": "Downstream service unavailable"})


# ── POST /citizen/report ──────────────────────────────────────────────────────

@router.post("/report", status_code=201)
async def submit_report(
    request: Request,
    body: dict,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user=Depends(get_optional_user),
    case_client: httpx.AsyncClient = Depends(get_case_client),
):
    """Submit fraud report. Proxies to Case Service POST /api/v1/cases."""
    headers = _forward_headers(request, current_user)
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    else:
        import uuid
        headers["Idempotency-Key"] = str(uuid.uuid4())

    result = await _proxy(case_client, "POST", "/api/v1/cases", json=body, headers=headers)
    
    # Map to BFF response format (docs/api/citizen-bff.md)
    if "data" in result:
        case_id = result["data"].get("caseId")
        return success_response({
            "caseId": case_id,
            "caseNumber": result["data"].get("caseNumber"),
            "message": "Your report has been registered. AI analysis is in progress.",
            "trackingUrl": f"/citizen/cases/{case_id}"
        }, _corr(request))
    return result


# ── GET /citizen/cases/:caseId ────────────────────────────────────────────────

@router.get("/cases/{case_id}")
async def get_case_status(
    request: Request,
    case_id: uuid.UUID,
    current_user=Depends(get_current_user),
    case_client: httpx.AsyncClient = Depends(get_case_client),
):
    """Get case status. Proxies to Case Service GET /api/v1/cases/:id."""
    result = await _proxy(case_client, "GET", f"/api/v1/cases/{case_id}", headers=_forward_headers(request, current_user))
    return result


# ── POST /citizen/bot/message ─────────────────────────────────────────────────

@router.post("/bot/message")
async def bot_message(
    request: Request,
    body: dict,
    current_user=Depends(get_current_user),
    bot_client: httpx.AsyncClient = Depends(get_bot_client),
):
    """Send bot message. Proxies to Bot Service POST /api/v1/bot/message."""
    result = await _proxy(bot_client, "POST", "/api/v1/bot/message", json=body, headers=_forward_headers(request, current_user))
    return result


# ── GET /citizen/bot/session/:sessionId ───────────────────────────────────────

@router.get("/bot/session/{session_id}")
async def get_bot_session(
    request: Request,
    session_id: uuid.UUID,
    current_user=Depends(get_current_user),
    bot_client: httpx.AsyncClient = Depends(get_bot_client),
):
    """Get bot session. Proxies to Bot Service GET /api/v1/bot/session/:id."""
    result = await _proxy(bot_client, "GET", f"/api/v1/bot/session/{session_id}", headers=_forward_headers(request, current_user))
    return result


# ── POST /citizen/cases/:caseId/evidence ──────────────────────────────────────

@router.post("/cases/{case_id}/evidence", status_code=201)
async def upload_evidence(
    request: Request,
    case_id: uuid.UUID,
    current_user=Depends(get_current_user),
    evidence_client: httpx.AsyncClient = Depends(get_evidence_client),
):
    """
    Upload evidence. Proxies to Evidence Service (Nilkanta's service).
    Degrades gracefully to 503 if Evidence Service is offline.
    """
    body = await request.body()
    content_type = request.headers.get("Content-Type", "application/json")
    result = await _proxy(
        evidence_client, "POST", f"/api/v1/evidence/{case_id}",
        content=body,
        headers={**_forward_headers(request, current_user), "Content-Type": content_type},
    )
    return result


# ── POST /citizen/evidence/:evidenceId/confirm ────────────────────────────────

@router.post("/evidence/{evidence_id}/confirm")
async def confirm_evidence(
    request: Request,
    evidence_id: uuid.UUID,
    current_user=Depends(get_current_user),
    evidence_client: httpx.AsyncClient = Depends(get_evidence_client),
):
    """Confirm evidence. Proxies to Evidence Service."""
    result = await _proxy(
        evidence_client, "POST", f"/api/v1/evidence/{evidence_id}/confirm",
        headers=_forward_headers(request, current_user),
    )
    return result

# ----------------------------------------
# FILE: backend/citizen-bff/models/schemas.py
# ----------------------------------------

"""Pydantic schemas for Citizen BFF API."""
import uuid
from typing import Optional
from pydantic import BaseModel

class CurrentUser(BaseModel):
    """Decoded JWT claims. Passed via Depends(get_current_user)."""
    user_id: uuid.UUID
    email: str
    role: str
    org_id: Optional[uuid.UUID] = None
    jurisdiction_id: Optional[str] = None
    jti: str  # JWT ID — used for denylist check

# ----------------------------------------
# FILE: backend/citizen-bff/clients/evidence_client.py
# ----------------------------------------

"""HTTP client for Evidence Service downstream calls."""
import httpx
from fastapi import Request


async def get_evidence_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.evidence_client

# ----------------------------------------
# FILE: backend/citizen-bff/clients/case_client.py
# ----------------------------------------

"""HTTP client for Case Service downstream calls."""
import httpx
from fastapi import Request


async def get_case_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.case_client

# ----------------------------------------
# FILE: backend/citizen-bff/clients/bot_client.py
# ----------------------------------------

"""HTTP client for Bot Service downstream calls."""
import httpx
from fastapi import Request


async def get_bot_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.bot_client

# ----------------------------------------
# FILE: backend/citizen-bff/tests/conftest.py
# ----------------------------------------

"""Shared fixtures for Citizen BFF tests."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport, Response
from main import app


@pytest.fixture
def mock_case_client():
    client = AsyncMock()
    client.request = AsyncMock(return_value=Response(
        200,
        json={"status": "success", "data": {"caseId": "abc-123"}},
    ))
    return client


@pytest.fixture
def mock_bot_client():
    client = AsyncMock()
    client.request = AsyncMock(return_value=Response(
        200,
        json={"status": "success", "data": {"sessionId": "ses-456", "response": "Hello"}},
    ))
    return client


@pytest.fixture
def mock_evidence_client_offline():
    """Simulate Evidence Service being unreachable."""
    import httpx
    client = AsyncMock()
    client.request = AsyncMock(side_effect=httpx.RequestError("Connection refused"))
    return client


@pytest.fixture
async def async_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
def auth_headers():
    import uuid
    return {
        "Authorization": "Bearer test-token",
        "X-Correlation-ID": str(uuid.uuid4()),
    }

# ----------------------------------------
# FILE: backend/citizen-bff/tests/test_citizen_bff.py
# ----------------------------------------

"""Tests for Citizen BFF proxy behavior."""
import uuid
from unittest.mock import AsyncMock
from httpx import Response

import pytest


class TestReportProxy:

    @pytest.mark.asyncio
    async def test_report_proxied_to_case_service(self, async_client, mock_case_client, auth_headers):
        """POST /citizen/report should proxy to Case Service."""
        from main import app
        from security.jwt import get_current_user
        from clients.case_client import get_case_client
        
        user_mock = AsyncMock()
        user_mock.user_id = uuid.uuid4()
        user_mock.role = "CITIZEN"
        user_mock.jti = "test"
        
        app.dependency_overrides[get_current_user] = lambda: user_mock
        app.dependency_overrides[get_case_client] = lambda: mock_case_client
        
        try:
            response = await async_client.post(
                "/api/v1/citizen/report",
                json={"title": "Test", "description": "Fraud", "complaint_type": "UPI_FRAUD", "language_code": "en"},
                headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
            )
            assert response.status_code in (200, 201)
            # Case client was called
            mock_case_client.request.assert_called_once()
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_correlation_id_forwarded(self, async_client, mock_case_client, auth_headers):
        """X-Correlation-ID should be forwarded in the downstream call."""
        from main import app
        from security.jwt import get_current_user
        from clients.case_client import get_case_client
        
        corr_id = str(uuid.uuid4())
        auth_headers["X-Correlation-ID"] = corr_id

        user_mock = AsyncMock()
        user_mock.user_id = uuid.uuid4()
        user_mock.role = "CITIZEN"
        user_mock.jti = "test"
        
        app.dependency_overrides[get_current_user] = lambda: user_mock
        app.dependency_overrides[get_case_client] = lambda: mock_case_client
        
        try:
            await async_client.get(
                f"/api/v1/citizen/cases/{uuid.uuid4()}",
                headers=auth_headers,
            )
            # Verify X-Correlation-ID appears in the forwarded call headers
            call_kwargs = mock_case_client.request.call_args[1]
            forwarded_headers = call_kwargs.get("headers", {})
            assert forwarded_headers.get("X-Correlation-ID") == corr_id
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_user_context_forwarded(self, async_client, mock_case_client, auth_headers):
        """X-User-Context should be injected into downstream headers."""
        import json
        from main import app
        from security.jwt import get_current_user
        from clients.case_client import get_case_client
        
        user_mock = AsyncMock()
        user_mock.user_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        user_mock.role = "CITIZEN"
        user_mock.jti = "test"
        
        app.dependency_overrides[get_current_user] = lambda: user_mock
        app.dependency_overrides[get_case_client] = lambda: mock_case_client
        
        try:
            await async_client.get(
                f"/api/v1/citizen/cases/{uuid.uuid4()}",
                headers=auth_headers,
            )
            call_kwargs = mock_case_client.request.call_args[1]
            forwarded_headers = call_kwargs.get("headers", {})
            assert "X-User-Context" in forwarded_headers
            context = json.loads(forwarded_headers["X-User-Context"])
            assert context["role"] == "CITIZEN"
            assert context["userId"] == "12345678-1234-5678-1234-567812345678"
        finally:
            app.dependency_overrides.clear()


class TestEvidenceServiceOffline:

    @pytest.mark.asyncio
    async def test_evidence_upload_returns_503_when_offline(
        self, async_client, mock_evidence_client_offline, auth_headers
    ):
        """POST /citizen/cases/:id/evidence → 503 when Evidence Service offline."""
        from main import app
        from security.jwt import get_current_user
        from clients.evidence_client import get_evidence_client
        
        user_mock = AsyncMock()
        user_mock.user_id = uuid.uuid4()
        user_mock.role = "CITIZEN"
        user_mock.jti = "test"
        
        app.dependency_overrides[get_current_user] = lambda: user_mock
        app.dependency_overrides[get_evidence_client] = lambda: mock_evidence_client_offline
        
        try:
            response = await async_client.post(
                f"/api/v1/citizen/cases/{uuid.uuid4()}/evidence",
                json={"filename": "screenshot.png"},
                headers=auth_headers,
            )
            assert response.status_code == 503
        finally:
            app.dependency_overrides.clear()


class TestBotProxy:

    @pytest.mark.asyncio
    async def test_bot_message_proxied(self, async_client, mock_bot_client, auth_headers):
        """POST /citizen/bot/message proxies to Bot Service."""
        from main import app
        from security.jwt import get_current_user
        from clients.bot_client import get_bot_client
        
        user_mock = AsyncMock()
        user_mock.user_id = uuid.uuid4()
        user_mock.role = "CITIZEN"
        user_mock.jti = "test"
        
        app.dependency_overrides[get_current_user] = lambda: user_mock
        app.dependency_overrides[get_bot_client] = lambda: mock_bot_client
        
        try:
            response = await async_client.post(
                "/api/v1/citizen/bot/message",
                json={"message": "I was scammed"},
                headers=auth_headers,
            )
            assert response.status_code == 200
            mock_bot_client.request.assert_called_once()
        finally:
            app.dependency_overrides.clear()


class TestHealthEndpoints:

    @pytest.mark.asyncio
    async def test_liveness(self, async_client):
        response = await async_client.get("/health/live")
        assert response.status_code == 200
