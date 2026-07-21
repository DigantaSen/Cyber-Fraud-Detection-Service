"""
Prediction Repository — INSERT only on inference.fused_verdicts.
APPEND-ONLY: DB trigger prevents UPDATE and DELETE.
Never call update() or delete() on FusedVerdict rows.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

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

    async def latest_for_case(self, case_id: uuid.UUID) -> Optional[FusedVerdict]:
        """Return the most recent immutable fused verdict for a case."""
        result = await self._session.execute(
            select(FusedVerdict)
            .where(FusedVerdict.case_id == case_id)
            .order_by(FusedVerdict.fusion_timestamp.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
