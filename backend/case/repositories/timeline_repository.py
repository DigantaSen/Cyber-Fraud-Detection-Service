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
