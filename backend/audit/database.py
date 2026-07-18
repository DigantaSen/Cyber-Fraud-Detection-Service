"""
Audit Service — Database Layer

Thin asyncpg connection pool wrapper.
Mirrors event-processing/database.py with audit-specific insert helper.

Design notes:
  - Pool min=2 / max=10 keeps connections low (single consumer pod writing).
  - The audit_log table is protected by platform.prevent_mutation() trigger —
    any attempt to UPDATE or DELETE will raise a PostgreSQL exception at the
    DB level, making it impossible even from code that accidentally calls the
    wrong method.
  - The insert_audit_entry() helper is the ONLY write path in this service.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import asyncpg

from config import settings

logger = logging.getLogger("audit-db")


class Database:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        """Create the asyncpg connection pool. Called once at startup."""
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

    # ── Write (consumer pod only) ──────────────────────────────────────────────

    async def insert_audit_entry(
        self,
        event_type: str,
        entity_type: str,
        entity_id: uuid.UUID,
        payload: Dict[str, Any],
        actor_id: Optional[uuid.UUID] = None,
        actor_role: Optional[str] = None,
        correlation_id: Optional[uuid.UUID] = None,
    ) -> uuid.UUID:
        """
        Append one record to audit.audit_log.
        NEVER called with UPDATE or DELETE — the DB trigger enforces this too.
        Returns the generated audit entry UUID.
        """
        query = """
            INSERT INTO audit.audit_log (
                event_type, entity_type, entity_id,
                actor_id, actor_role, payload, correlation_id
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id;
        """
        async with self.pool.acquire() as conn:
            row_id = await conn.fetchval(
                query,
                event_type,
                entity_type,
                entity_id,
                actor_id,
                actor_role,
                json.dumps(payload),  # asyncpg accepts str for JSONB columns
                correlation_id,
            )
        return row_id

    # ── Read helpers (API pod only) ────────────────────────────────────────────

    async def fetch_by_case(
        self,
        case_id: uuid.UUID,
        limit: int,
        cursor_ts: Optional[str],
        cursor_id: Optional[str],
    ):
        """
        Fetch audit entries for a case in chronological order (ASC).

        Strategy (see implementation plan §Design Decisions §2):
          - Primary match:   entity_id = case_id  (uses audit_entity_idx)
          - Secondary match: payload->>'caseId' = case_id::text
            (covers Prediction.Overridden, Evidence.Uploaded etc. whose
             entity_id is NOT the case UUID but whose payload carries caseId)

        Cursor pagination: keyset on (created_at ASC, id ASC) — stable and
        O(log n) on the (entity_id, created_at DESC) index.

        ⚠️  Fix: both the row fetch and total count share a single pool
        connection to avoid exhausting the min=2 pool under rapid requests.
        Returns (rows, total) tuple so callers need only one await.
        """
        async with self.pool.acquire() as conn:
            if cursor_ts and cursor_id:
                # asyncpg requires a datetime object (not str) for timestamptz params
                cursor_dt = datetime.fromisoformat(cursor_ts.replace("Z", "+00:00"))
                rows = await conn.fetch(
                    """
                    SELECT id, event_type, entity_type, entity_id,
                           actor_id, actor_role, payload, correlation_id, created_at
                    FROM audit.audit_log
                    WHERE (entity_id = $1 OR (payload->>'caseId')::text = $2)
                      AND (created_at, id) > ($3, $4::uuid)
                    ORDER BY created_at ASC, id ASC
                    LIMIT $5;
                    """,
                    case_id, str(case_id), cursor_dt, cursor_id, limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT id, event_type, entity_type, entity_id,
                           actor_id, actor_role, payload, correlation_id, created_at
                    FROM audit.audit_log
                    WHERE entity_id = $1 OR (payload->>'caseId')::text = $2
                    ORDER BY created_at ASC, id ASC
                    LIMIT $3;
                    """,
                    case_id, str(case_id), limit,
                )
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM audit.audit_log WHERE entity_id = $1 OR (payload->>'caseId')::text = $2;",
                case_id, str(case_id),
            )
        return rows, total

    async def fetch_by_entity(
        self,
        entity_id: uuid.UUID,
        entity_type: Optional[str],
        from_ts: Optional[str],
        to_ts: Optional[str],
        limit: int,
        cursor_ts: Optional[str],
        cursor_id: Optional[str],
    ):
        """
        Fetch audit entries for any entity type with optional filters.
        Returns (rows, total) tuple — both queries share one connection
        to avoid pool exhaustion under rapid requests.
        """
        conditions = ["entity_id = $1"]
        params: list = [entity_id]
        idx = 2

        if entity_type:
            conditions.append(f"entity_type = ${idx}")
            params.append(entity_type)
            idx += 1
        if from_ts:
            conditions.append(f"created_at >= ${idx}::timestamptz")
            params.append(from_ts)
            idx += 1
        if to_ts:
            conditions.append(f"created_at <= ${idx}::timestamptz")
            params.append(to_ts)
            idx += 1

        # Build count params before adding cursor (count ignores cursor)
        count_params = list(params)
        count_where = " AND ".join(conditions)

        if cursor_ts and cursor_id:
            # asyncpg requires datetime object, not ISO string, for timestamptz
            cursor_dt = datetime.fromisoformat(cursor_ts.replace("Z", "+00:00"))
            conditions.append(f"(created_at, id) > (${idx}, ${idx+1}::uuid)")
            params.append(cursor_dt)
            params.append(cursor_id)
            idx += 2

        where = " AND ".join(conditions)
        fetch_params = list(params) + [limit]
        fetch_query = f"""
            SELECT id, event_type, entity_type, entity_id,
                   actor_id, actor_role, payload, correlation_id, created_at
            FROM audit.audit_log
            WHERE {where}
            ORDER BY created_at ASC, id ASC
            LIMIT ${idx};
        """
        count_query = f"SELECT COUNT(*) FROM audit.audit_log WHERE {count_where};"

        async with self.pool.acquire() as conn:
            rows  = await conn.fetch(fetch_query, *fetch_params)
            total = await conn.fetchval(count_query, *count_params)
        return rows, total

    async def ping(self) -> bool:
        """Health check — returns True if DB is reachable."""
        try:
            async with self.pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception:
            return False


# Module-level singleton — shared by both API and (if ever co-located) consumer
db = Database()
