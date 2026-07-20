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
