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
