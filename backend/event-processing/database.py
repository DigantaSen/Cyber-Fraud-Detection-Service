import json
import uuid
import asyncpg
from datetime import datetime
from config import settings

class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(
            settings.DSN,
            min_size=2,
            max_size=10
        )

    async def close(self):
        if self.pool:
            await self.pool.close()

    async def insert_outbox_event(self, aggregate_type: str, aggregate_id: uuid.UUID, event_type: str, topic: str, event_key: str, payload: dict, correlation_id: uuid.UUID = None):
        """
        Inserts an event into the platform.outbox table. 
        A database trigger will notify the outbox publisher via listen/notify.
        """
        query = """
            INSERT INTO platform.outbox (
                aggregate_type, aggregate_id, event_type, topic, event_key, payload, correlation_id
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING outbox_id;
        """
        async with self.pool.acquire() as conn:
            outbox_id = await conn.fetchval(
                query,
                aggregate_type,
                aggregate_id,
                event_type,
                topic,
                event_key,
                json.dumps(payload),
                correlation_id
            )
            return outbox_id

db = Database()
