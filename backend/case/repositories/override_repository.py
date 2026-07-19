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
