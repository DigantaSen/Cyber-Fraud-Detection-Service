"""
Audit Service — Kafka Consumer Pod (T7)

Runs as a headless, long-running process (no HTTP server).
Subscribes to ALL domain event topics and appends every event to
audit.audit_log as an immutable record.

Architecture notes:
  - Consumer group: audit-consumer (isolated from search-indexer)
  - Manual offset commit: committed only AFTER successful DB insert or DLQ routing
  - Retry: 3 attempts with exponential backoff (1s, 5s, 30s) — mirrors search/indexer.py
  - DLQ: failed messages → <topic>.DLQ topic
  - asyncpg pool is shared via database.py (same pattern as event-processing)

Kafka topics consumed (see api/audit.md §Architecture):
  Case.*           → case.created, case.updated
  Evidence.*       → evidence.uploaded, evidence.verified
  Prediction.*     → prediction.completed, prediction.overridden
  MHAAlert.*       → mhaalert.sent
  User.*           → user.created, user.updated
  Intervention.*   → intervention.created
  IntelligencePackage.* → intelligencepackage.created
  Report.*         → report.generated

⚠️  Tweak vs plan: consumer.py uses asyncio.run() to drive the async DB inserts
    from the synchronous kafka-python-ng loop — same approach as the outbox
    publisher avoids introducing aiokafka as a new dependency.
"""

import asyncio
import json
import logging
import signal
import sys
import time
import uuid
from typing import Any, Callable, Dict, Optional

from kafka import KafkaConsumer, KafkaProducer

from config import settings
from database import db

# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("audit-consumer")

# ── Graceful shutdown ──────────────────────────────────────────────────────────

running = True


def handle_shutdown(sig, frame):
    global running
    logger.info("Shutdown signal received — draining consumer...")
    running = False


signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

# ── Retry config (matches search/indexer.py) ───────────────────────────────────

RETRY_INTERVALS = [1, 5, 30]  # seconds between attempts

# ── Topic → event_type / entity_type / entity_id key mapping ──────────────────
#
# Each entry: (event_type_label, entity_type_label, entity_id_field, fallback_fields)
# fallback_fields: tried in order if the primary key is absent.
#
# Tweak vs plan: added fallback_fields list so the consumer is resilient to
# minor payload schema variations from different service owners.

TOPIC_MAP: Dict[str, Dict[str, Any]] = {
    "case.created": {
        "event_type": "Case.Created",
        "entity_type": "Case",
        "entity_id_fields": ["caseId", "case_id"],
        "actor_id_fields": ["actorId", "userId", "reporterUserId"],
        "actor_role_default": "SYSTEM",
    },
    "case.updated": {
        "event_type": "Case.Updated",
        "entity_type": "Case",
        "entity_id_fields": ["caseId", "case_id"],
        "actor_id_fields": ["actorId", "assignedInvestigator"],
        "actor_role_default": "SYSTEM",
    },
    "evidence.uploaded": {
        "event_type": "Evidence.Uploaded",
        "entity_type": "Evidence",
        "entity_id_fields": ["evidenceId", "evidence_id"],
        "actor_id_fields": ["uploadedBy", "actorId"],
        "actor_role_default": "SYSTEM",
    },
    "evidence.verified": {
        "event_type": "Evidence.Verified",
        "entity_type": "Evidence",
        "entity_id_fields": ["evidenceId", "evidence_id"],
        "actor_id_fields": ["verifiedBy", "actorId"],
        "actor_role_default": "SYSTEM",
    },
    "prediction.completed": {
        "event_type": "Prediction.Completed",
        "entity_type": "Prediction",
        "entity_id_fields": ["predictionId", "prediction_id"],
        "actor_id_fields": [],  # machine event — no human actor
        "actor_role_default": "SYSTEM",
    },
    "prediction.overridden": {
        "event_type": "Prediction.Overridden",
        "entity_type": "Prediction",
        "entity_id_fields": ["predictionId", "prediction_id", "originalVerdictId"],
        "actor_id_fields": ["investigatorId", "actorId"],
        "actor_role_default": "INVESTIGATOR",
    },
    "mhaalert.sent": {
        "event_type": "MHAAlert.Sent",
        "entity_type": "MHAAlert",
        "entity_id_fields": ["alertId", "alert_id"],
        "actor_id_fields": ["triggeredBy", "actorId"],
        "actor_role_default": "SYSTEM",
    },
    "user.created": {
        "event_type": "User.Created",
        "entity_type": "User",
        "entity_id_fields": ["userId", "user_id"],
        "actor_id_fields": ["createdBy", "actorId"],
        "actor_role_default": "SYSTEM",
    },
    "user.updated": {
        "event_type": "User.Updated",
        "entity_type": "User",
        "entity_id_fields": ["userId", "user_id"],
        "actor_id_fields": ["updatedBy", "actorId"],
        "actor_role_default": "SYSTEM",
    },
    "intervention.created": {
        "event_type": "Intervention.Created",
        "entity_type": "Intervention",
        "entity_id_fields": ["interventionId", "intervention_id", "caseId"],
        "actor_id_fields": ["actorId", "investigatorId"],
        "actor_role_default": "INVESTIGATOR",
    },
    "intelligencepackage.created": {
        "event_type": "IntelligencePackage.Created",
        "entity_type": "IntelligencePackage",
        "entity_id_fields": ["packageId", "package_id", "reportId"],
        "actor_id_fields": ["generatedBy", "actorId"],
        "actor_role_default": "SYSTEM",
    },
    "report.generated": {
        "event_type": "Report.Generated",
        "entity_type": "Report",
        "entity_id_fields": ["reportId", "report_id"],
        "actor_id_fields": ["generatedBy", "actorId"],
        "actor_role_default": "SYSTEM",
    },
}

TOPICS = list(TOPIC_MAP.keys())


# ── Field extraction helpers ───────────────────────────────────────────────────

def _extract_uuid(payload: Dict, fields: list) -> Optional[uuid.UUID]:
    """Try each field name in order; return the first valid UUID found."""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    for field in fields:
        val = payload.get(field) or data.get(field)
        if val:
            try:
                return uuid.UUID(str(val))
            except (ValueError, AttributeError):
                continue
    return None


def _extract_str(payload: Dict, fields: list) -> Optional[str]:
    """Try each field name; return first non-empty string."""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    for field in fields:
        val = payload.get(field) or data.get(field)
        if val:
            return str(val)
    return None


# ── Core handler ───────────────────────────────────────────────────────────────

async def _handle_message(topic: str, payload: Dict[str, Any]):
    """
    Map a Kafka message to an audit_log INSERT.

    Raises ValueError for unrecoverable payload issues (triggers DLQ routing).
    Raises any asyncpg exception (triggers retry logic).
    """
    mapping = TOPIC_MAP.get(topic)
    if not mapping:
        logger.warning(f"No mapping for topic '{topic}' — skipping (forward-compatible)")
        return

    event_type: str = mapping["event_type"]
    entity_type: str = mapping["entity_type"]

    entity_id = _extract_uuid(payload, mapping["entity_id_fields"])
    if entity_id is None:
        # Log and skip — do NOT route to DLQ for missing entity_id since some
        # future topics may be structurally different; we prefer to not lose events.
        logger.error(
            f"[{topic}] Could not extract entity_id from fields "
            f"{mapping['entity_id_fields']} in payload: {payload} — "
            f"storing with nil UUID as entity_id for audit trail completeness"
        )
        entity_id = uuid.UUID("00000000-0000-0000-0000-000000000000")

    actor_id = _extract_uuid(payload, mapping["actor_id_fields"])

    # actor_role: prefer explicit payload field, fall back to topic default
    actor_role = (
        payload.get("actorRole")
        or payload.get("actor_role")
        or payload.get("role")
        or mapping["actor_role_default"]
    )

    correlation_id = _extract_uuid(payload, ["correlationId", "correlation_id"])

    audit_id = await db.insert_audit_entry(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload,
        actor_id=actor_id,
        actor_role=actor_role,
        correlation_id=correlation_id,
    )
    logger.info(
        f"[{topic}] Appended audit entry {audit_id} "
        f"| entity={entity_type}:{entity_id} actor={actor_id}({actor_role})"
    )


# ── DLQ Producer ──────────────────────────────────────────────────────────────

def _create_dlq_producer() -> KafkaProducer:
    return KafkaProducer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        client_id="audit-consumer-dlq-producer",
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )


def _route_to_dlq(producer: KafkaProducer, topic: str, value: Any, key: bytes):
    dlq_topic = f"{topic}.DLQ"
    try:
        logger.warning(f"Routing failed audit message to DLQ: {dlq_topic}")
        producer.send(dlq_topic, key=key, value=value)
        producer.flush()
    except Exception as e:
        logger.error(f"FATAL: Could not route to DLQ {dlq_topic}: {e}")


# ── Main consumer loop ─────────────────────────────────────────────────────────

def run():
    # Bootstrap asyncpg pool (blocking call inside asyncio.run)
    logger.info("Connecting to PostgreSQL...")
    asyncio.run(db.connect())

    logger.info(f"Connecting to Kafka at {settings.KAFKA_BOOTSTRAP_SERVERS}")
    consumer = KafkaConsumer(
        *TOPICS,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=settings.KAFKA_GROUP_ID,
        enable_auto_commit=False,   # manual commit — only after successful write or DLQ
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        auto_offset_reset="earliest",
        client_id="audit-consumer-main",
    )
    dlq_producer = _create_dlq_producer()

    logger.info(f"Subscribed to {len(TOPICS)} topics: {TOPICS}")

    try:
        for msg in consumer:
            if not running:
                break

            topic = msg.topic
            success = False
            attempts = 0
            max_attempts = len(RETRY_INTERVALS) + 1  # 4 total

            while attempts < max_attempts and not success:
                try:
                    # Bridge sync Kafka loop → async DB insert
                    asyncio.run(_handle_message(topic, msg.value))
                    success = True
                except Exception as e:
                    attempts += 1
                    logger.error(
                        f"Error processing [{topic}] attempt {attempts}/{max_attempts}: {e}"
                    )
                    if attempts < max_attempts:
                        backoff = RETRY_INTERVALS[attempts - 1]
                        logger.info(f"Retrying in {backoff}s...")
                        time.sleep(backoff)

            if not success:
                logger.error(f"[{topic}] Failed after {max_attempts} attempts — routing to DLQ")
                _route_to_dlq(dlq_producer, topic, msg.value, msg.key)

            # Commit offset after each message regardless of success / DLQ
            consumer.commit()

    except Exception as e:
        logger.exception(f"Consumer fatal error: {e}")
        sys.exit(1)
    finally:
        logger.info("Closing Kafka consumer and DLQ producer...")
        consumer.close()
        dlq_producer.close()
        asyncio.run(db.close())


if __name__ == "__main__":
    run()
