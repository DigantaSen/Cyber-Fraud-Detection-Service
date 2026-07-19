"""
Outbox Repository — writes events to platform.outbox.

Kafka topic constants from docs/db/kafka.md.

After each INSERT the DB trigger platform.notify_outbox() fires
  NOTIFY outbox_channel, '<outbox_id>'
so Diganta's Outbox Publisher wakes immediately and relays to Kafka.
The outbox row and the domain row MUST be committed in the same transaction.
"""
import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from models.outbox import Outbox


# ── Kafka topic constants (docs/db/kafka.md) ──────────────────────────────────
TOPIC_CASE_CREATED = "case.created"
TOPIC_CASE_UPDATED = "case.updated"
TOPIC_CASE_ASSIGNED = "case.assigned"
TOPIC_CASE_CLOSED = "case.closed"
TOPIC_PREDICTION_REQUESTED = "prediction.requested"
TOPIC_PREDICTION_COMPLETED = "prediction.completed"
TOPIC_PREDICTION_OVERRIDDEN = "prediction.overridden"
TOPIC_NOTIFICATION_REQUESTED = "notification.requested"


class OutboxRepository:

    def __init__(self, session: AsyncSession):
        self._session = session

    async def publish(
        self,
        aggregate_type: str,
        aggregate_id: uuid.UUID,
        event_type: str,
        topic: str,
        event_key: str,
        payload: dict,
        correlation_id: Optional[uuid.UUID] = None,
    ) -> Outbox:
        """
        Write a domain event to platform.outbox (status=PENDING).
        The INSERT trigger fires pg_notify so the relay worker wakes up.
        Commit this INSERT atomically with the domain row change.

        Args:
            aggregate_type: e.g. "Case", "Prediction"
            aggregate_id:   UUID of the domain entity (e.g. case_id)
            event_type:     e.g. "Case.Created"
            topic:          Kafka topic name (use TOPIC_* constants above)
            event_key:      Kafka partition key (e.g. str(case_id))
            payload:        JSON-serialisable event body
            correlation_id: Propagated X-Correlation-ID from the incoming request
        """
        entry = Outbox(
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            topic=topic,
            event_key=event_key,
            payload=payload,
            correlation_id=correlation_id,
            status="PENDING",
            attempts=0,
        )
        self._session.add(entry)
        await self._session.flush()
        await self._session.refresh(entry)
        return entry
