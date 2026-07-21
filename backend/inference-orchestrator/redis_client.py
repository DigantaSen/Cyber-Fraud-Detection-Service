"""
Inference Orchestrator — Redis Client

Loads the 4 fusion configuration keys on every analysis call (hot-reload FR-14.4).
All keys live in the redis.md manifest. Defaults apply if Redis is cold (first start).

Default values match T13 spec (Execution.md line 779) and §12.2:
  scam-nlp:       0.40
  counterfeit-cv: 0.20
  graph-analyzer: 0.25
  audio-analyzer: 0.15
  confidence_threshold: 0.60  (NFR-8.1)
  per_model_timeout_ms: 2000
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Set

import redis.asyncio as aioredis

logger = logging.getLogger("orch-redis")

# ── Defaults (spec-authoritative, used when Redis keys absent) ─────────────────
DEFAULT_WEIGHTS: Dict[str, float] = {
    "scam-nlp":       0.40,
    "counterfeit-cv": 0.20,
    "graph-analyzer": 0.25,
    "audio-analyzer": 0.15,
}
DEFAULT_ENABLED_MODELS: Set[str] = set(DEFAULT_WEIGHTS.keys())
DEFAULT_CONFIDENCE_THRESHOLD: float = 0.60
DEFAULT_PER_MODEL_TIMEOUT_S: float = 8.0


@dataclass
class FusionConfig:
    weights: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    enabled_models: Set[str] = field(default_factory=lambda: set(DEFAULT_ENABLED_MODELS))
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
    per_model_timeout_s: float = DEFAULT_PER_MODEL_TIMEOUT_S


class RedisClient:
    def __init__(self):
        self._redis: aioredis.Redis | None = None

    async def connect(self, url: str):
        self._redis = aioredis.from_url(url, decode_responses=True)
        logger.info("Redis async client connected")

    async def close(self):
        if self._redis:
            await self._redis.aclose()
            logger.info("Redis connection closed")

    async def ping(self) -> bool:
        try:
            return await self._redis.ping()
        except Exception as e:
            logger.error(f"Redis ping failed: {e}")
            return False

    async def load_fusion_config(self) -> FusionConfig:
        """
        Reads all 4 fusion keys fresh on every call (hot-reload without restart).
        Falls back to defaults if any key is absent (cold Redis on first startup).
        """
        try:
            weights_raw   = await self._redis.hgetall("fusion:weights")
            enabled_raw   = await self._redis.smembers("fusion:enabled_models")
            threshold_raw = await self._redis.get("fusion:confidence_threshold")
            timeout_raw   = await self._redis.get("fusion:per_model_timeout_ms")
        except Exception as e:
            logger.warning(f"Redis read failed — using defaults. Error: {e}")
            return FusionConfig()

        weights = (
            {k: float(v) for k, v in weights_raw.items()}
            if weights_raw else dict(DEFAULT_WEIGHTS)
        )
        enabled = set(enabled_raw) if enabled_raw else set(DEFAULT_ENABLED_MODELS)
        threshold = float(threshold_raw) if threshold_raw else DEFAULT_CONFIDENCE_THRESHOLD
        timeout_s = (int(timeout_raw) / 1000.0) if timeout_raw else DEFAULT_PER_MODEL_TIMEOUT_S

        config = FusionConfig(
            weights=weights,
            enabled_models=enabled,
            confidence_threshold=threshold,
            per_model_timeout_s=timeout_s,
        )
        logger.debug(
            f"FusionConfig loaded: enabled={config.enabled_models} "
            f"threshold={config.confidence_threshold} timeout={config.per_model_timeout_s}s"
        )
        return config


redis_client = RedisClient()
