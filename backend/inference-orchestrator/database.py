"""
Inference Orchestrator — Database Layer

Two tables written atomically per analysis:
  inference.predictions   — parent row (status starts PROCESSING)
  inference.fused_verdicts — child row (append-only via trigger)

After writing fused_verdicts, we UPDATE predictions.status to COMPLETE/FAILED.
fused_verdicts is protected by platform.prevent_mutation() — no UPDATE/DELETE ever.

Design notes:
  - Pool min=2 / max=10: orchestrator makes DB writes on each Kafka message +
    reads on HTTP GET endpoints. 10 max is sufficient for single-pod local use.
  - All three operations (INSERT predictions, INSERT fused_verdicts, UPDATE predictions)
    run inside a single transaction so failures leave no orphan rows.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import asyncpg

from config import settings

logger = logging.getLogger("orch-db")


class Database:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        """Create the asyncpg connection pool. Called once at app startup."""
        self.pool = await asyncpg.create_pool(
            settings.DATABASE_URL,
            min_size=2,
            max_size=10,
        )
        logger.info("asyncpg pool connected to PostgreSQL")

    async def close(self):
        """Graceful shutdown — drain and close pool."""
        if self.pool:
            await self.pool.close()
            logger.info("asyncpg pool closed")

    # ── Write ──────────────────────────────────────────────────────────────────

    async def persist_verdict(
        self,
        case_id: uuid.UUID,
        trigger_type: str,
        correlation_id: Optional[uuid.UUID],
        fused_score: float,
        risk_tier: str,
        confidence: float,
        verdict_status: str,      # COMPLETE | INCOMPLETE | PENDING_REVIEW
        prediction_status: str,   # COMPLETE | FAILED (for predictions row)
        model_breakdown: list,
        explanation: str,
        fusion_weights: dict,
        pending_review: bool,
    ) -> uuid.UUID:
        """
        Atomically:
          1. INSERT inference.predictions (status=PROCESSING)
          2. INSERT inference.fused_verdicts
          3. UPDATE inference.predictions.status = final status

        Returns prediction_id UUID.
        fused_verdicts is append-only — no UPDATE/DELETE possible.
        """
        prediction_id = uuid.uuid4()

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Step 1: create the prediction row (status=PROCESSING initially)
                await conn.execute(
                    """
                    INSERT INTO inference.predictions
                        (prediction_id, case_id, trigger_type, status, correlation_id)
                    VALUES ($1, $2, $3, 'PROCESSING', $4)
                    """,
                    prediction_id, case_id, trigger_type, correlation_id,
                )

                # Step 2: write the verdict (append-only — trigger blocks UPDATE/DELETE)
                await conn.execute(
                    """
                    INSERT INTO inference.fused_verdicts
                        (prediction_id, case_id, fused_score, risk_tier, confidence,
                         status, model_breakdown, explanation, fusion_weights,
                         pending_review, pending_notification, correlation_id)
                    VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9::jsonb, $10, $11, $12)
                    """,
                    prediction_id,
                    case_id,
                    round(fused_score, 2),
                    risk_tier,
                    round(confidence, 3),
                    verdict_status,
                    json.dumps(model_breakdown),
                    explanation,
                    json.dumps(fusion_weights),
                    pending_review,
                    pending_review,   # pending_notification = True when PENDING_REVIEW
                    correlation_id,
                )

                # Step 3: update predictions.status to final value
                await conn.execute(
                    """
                    UPDATE inference.predictions
                    SET status = $1, completed_at = NOW()
                    WHERE prediction_id = $2
                    """,
                    prediction_status, prediction_id,
                )

        logger.info(
            f"Verdict persisted: prediction_id={prediction_id} "
            f"case_id={case_id} status={verdict_status} score={fused_score:.1f} tier={risk_tier}"
        )
        return prediction_id

    async def persist_failed(
        self,
        case_id: uuid.UUID,
        trigger_type: str,
        correlation_id: Optional[uuid.UUID],
    ) -> uuid.UUID:
        """
        Records a fully-failed prediction (all models unavailable).
        No fused_verdicts row — predictions row with status=FAILED.
        """
        prediction_id = uuid.uuid4()
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO inference.predictions
                    (prediction_id, case_id, trigger_type, status, completed_at, correlation_id)
                VALUES ($1, $2, $3, 'FAILED', NOW(), $4)
                """,
                prediction_id, case_id, trigger_type, correlation_id,
            )
        logger.warning(f"All models failed for case_id={case_id}. Recorded FAILED prediction.")
        return prediction_id

    # ── Read ───────────────────────────────────────────────────────────────────

    async def fetch_verdict(self, prediction_id: uuid.UUID) -> Optional[Dict[str, Any]]:
        """Fetch FusedVerdict by prediction_id. Returns None if not found."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT p.prediction_id, p.case_id, p.trigger_type, p.requested_at,
                       v.fused_score, v.risk_tier, v.confidence, v.status,
                       v.model_breakdown, v.explanation, v.fusion_weights,
                       v.pending_review, v.fusion_timestamp, p.correlation_id
                FROM inference.predictions p
                JOIN inference.fused_verdicts v USING (prediction_id)
                WHERE p.prediction_id = $1
                """,
                prediction_id,
            )
        return dict(row) if row else None

    async def fetch_latest_for_case(self, case_id: uuid.UUID) -> Optional[Dict[str, Any]]:
        """Fetch most recent FusedVerdict for a case. Returns None if none exists."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT p.prediction_id, p.case_id, p.trigger_type, p.requested_at,
                       v.fused_score, v.risk_tier, v.confidence, v.status,
                       v.model_breakdown, v.explanation, v.fusion_weights,
                       v.pending_review, v.fusion_timestamp, p.correlation_id
                FROM inference.predictions p
                JOIN inference.fused_verdicts v USING (prediction_id)
                WHERE p.case_id = $1
                ORDER BY p.requested_at DESC
                LIMIT 1
                """,
                case_id,
            )
        return dict(row) if row else None

    async def fetch_case_details(self, case_id: uuid.UUID) -> Optional[Dict[str, Any]]:
        """Fetch title, description, complaint_type, suspect_phone, suspect_account from investigation.cases."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT title, description, complaint_type, suspect_phone, suspect_account, language_code
                FROM investigation.cases
                WHERE case_id = $1
                """,
                case_id,
            )
        return dict(row) if row else None

    async def ping(self) -> bool:
        """Health check — returns True if DB is reachable."""
        try:
            async with self.pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception:
            return False


db = Database()
