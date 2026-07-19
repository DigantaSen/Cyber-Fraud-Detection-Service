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
