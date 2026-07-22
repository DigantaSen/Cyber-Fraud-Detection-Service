"""
Search Service — Kafka Indexer (Consumer Pod)

This module runs as a dedicated headless pod (no HTTP server).
It consumes events from Kafka and upserts documents into OpenSearch,
keeping the CQRS read model in sync.

Topics consumed:
  - case.created          → full upsert into case_index
  - case.updated          → partial update in case_index
  - evidence.uploaded     → full upsert into evidence_index
  - prediction.completed  → partial score update in case_index

Consumer group: search-indexer (isolated — allows independent scaling)
Retry strategy: 3 attempts with exponential backoff (1s, 5s, 30s)
DLQ: failed messages routed to <topic>.DLQ
"""

import json
import logging
import signal
import sys
import time
from typing import Any, Callable

from kafka import KafkaConsumer, KafkaProducer
from opensearchpy import OpenSearch, OpenSearchException

from config import settings
from opensearch_client import client as os_client, ensure_indices

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
logger = logging.getLogger("search-indexer")

# ── Graceful shutdown ──────────────────────────────────────────────────────────
running = True

def handle_shutdown(sig, frame):
    global running
    logger.info("Shutdown signal received — stopping consumer...")
    running = False

signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)


# ── Topic → Handler dispatch ───────────────────────────────────────────────────

def handle_case_created(payload: dict):
    """Full upsert a new case document into case_index."""
    case_id = payload.get("caseId") or payload.get("case_id")
    if not case_id:
        raise ValueError(f"case.created payload missing caseId: {payload}")

    doc = {
        "caseId":               case_id,
        "caseNumber":           payload.get("caseNumber", ""),
        "title":                payload.get("title", ""),
        "description":          payload.get("description", ""),
        "notes":                payload.get("notes", ""),
        "status":               payload.get("status", "New"),
        "riskTier":             payload.get("riskTier", "LOW"),
        "confidence":           payload.get("confidence", 0.0),
        "fusedScore":           payload.get("fusedScore", 0.0),
        "jurisdictionId":       payload.get("jurisdictionId", ""),
        "assignedInvestigator": payload.get("assignedInvestigator") or payload.get("assignedTo", ""),
        "complaintType":        payload.get("complaintType", ""),
        "reporterPhone":        payload.get("reporterPhone", ""),
        "reporterEntityName":   payload.get("reporterEntityName", ""),
        "complaintLocation":    payload.get("complaintLocation"),  # expects {"lat": ..., "lon": ...}
        "createdAt":            payload.get("createdAt"),
        "updatedAt":            payload.get("updatedAt") or payload.get("createdAt"),
    }
    os_client.index(index="case_index", id=case_id, body=doc)
    logger.info(f"[case.created] Indexed case {case_id}")


def handle_case_updated(payload: dict):
    """Partial update of an existing case document in case_index."""
    case_id = payload.get("caseId") or payload.get("case_id")
    if not case_id:
        raise ValueError(f"case.updated payload missing caseId: {payload}")

    # Only update fields that are present in the payload to avoid wiping fields.
    partial = {}
    if "status" in payload:
        partial["status"] = payload["status"]
    elif "newState" in payload:
        partial["status"] = payload["newState"]

    for field in ["title", "description", "notes", "riskTier",
                  "assignedInvestigator", "complaintType", "updatedAt"]:
        if field in payload:
            partial[field] = payload[field]

    if partial:
        os_client.update(index="case_index", id=case_id, body={"doc": partial})
        logger.info(f"[case.updated] Updated case {case_id} fields: {list(partial.keys())}")


def handle_evidence_uploaded(payload: dict):
    """Full upsert of a new evidence document into evidence_index."""
    evidence_id = payload.get("evidenceId") or payload.get("evidence_id")
    if not evidence_id:
        raise ValueError(f"evidence.uploaded payload missing evidenceId: {payload}")

    doc = {
        "evidenceId": evidence_id,
        "caseId":     payload.get("caseId", ""),
        "fileName":   payload.get("fileName", ""),
        "mimeType":   payload.get("mimeType", ""),
        "sha256":     payload.get("sha256", ""),
        "fileSize":   payload.get("fileSize", 0),
        "uploadedBy": payload.get("uploadedBy", ""),
        "createdAt":  payload.get("createdAt"),
    }
    os_client.index(index="evidence_index", id=evidence_id, body=doc)
    logger.info(f"[evidence.uploaded] Indexed evidence {evidence_id}")


def handle_prediction_completed(payload: dict):
    """Partial update of a case with AI prediction scores."""
    case_id = payload.get("caseId") or payload.get("case_id")
    if not case_id:
        raise ValueError(f"prediction.completed payload missing caseId: {payload}")

    partial = {}
    for field in ["fusedScore", "riskTier", "confidence"]:
        if field in payload:
            partial[field] = payload[field]

    if partial:
        try:
            os_client.update(index="case_index", id=case_id, body={"doc": partial})
            logger.info(f"[prediction.completed] Updated scores for case {case_id}: {partial}")
        except Exception as e:
            # Case may not be indexed yet if prediction arrived before case.created
            logger.warning(f"[prediction.completed] Could not update case {case_id} (may not exist yet): {e}")



def handle_prediction_overridden(payload: dict):
    """Partial update of a case when an investigator overrides the verdict."""
    case_id = payload.get("caseId") or payload.get("case_id")
    if not case_id:
        raise ValueError(f"prediction.overridden payload missing caseId: {payload}")

    new_state = payload.get("newState")
    decision = payload.get("decision")
    disposition = payload.get("disposition")

    partial = {}
    if new_state:
        partial["status"] = new_state
    if decision:
        partial["verdictStatus"] = "CONFIRMED_FRAUD" if decision == "APPROVE" else "DISMISSED"
    if disposition:
        partial["disposition"] = disposition

    if partial:
        try:
            os_client.update(index="case_index", id=case_id, body={"doc": partial})
            logger.info(f"[prediction.overridden] Updated case {case_id} status to {partial.get('status')}")
        except Exception as e:
            logger.warning(f"[prediction.overridden] Could not update case {case_id}: {e}")


TOPIC_HANDLERS: dict[str, Callable[[dict], None]] = {
    "case.created":          handle_case_created,
    "case.updated":          handle_case_updated,
    "evidence.uploaded":     handle_evidence_uploaded,
    "prediction.completed":  handle_prediction_completed,
    "prediction.overridden": handle_prediction_overridden,
}

TOPICS = list(TOPIC_HANDLERS.keys())

# Backoff intervals in seconds (matches consumer.py in event-processing)
RETRY_INTERVALS = [1, 5, 30]


# ── DLQ Producer ──────────────────────────────────────────────────────────────

def create_dlq_producer() -> KafkaProducer:
    return KafkaProducer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        client_id="search-indexer-dlq-producer",
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )


def route_to_dlq(producer: KafkaProducer, topic: str, value: Any, key: bytes):
    dlq_topic = f"{topic}.DLQ"
    try:
        logger.warning(f"Routing failed message to DLQ: {dlq_topic}")
        producer.send(dlq_topic, key=key, value=value)
        producer.flush()
    except Exception as e:
        logger.error(f"FATAL: Could not route to DLQ {dlq_topic}: {e}")


# ── Main Consumer Loop ─────────────────────────────────────────────────────────

def run():
    logger.info("Ensuring OpenSearch indices exist...")
    ensure_indices()

    logger.info(f"Connecting to Kafka at {settings.KAFKA_BOOTSTRAP_SERVERS}")
    consumer = KafkaConsumer(
        *TOPICS,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=settings.KAFKA_GROUP_ID,
        enable_auto_commit=False,   # Manual commit after processing
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        auto_offset_reset="earliest",
        client_id="search-indexer-consumer",
    )

    dlq_producer = create_dlq_producer()

    logger.info(f"Subscribed to topics: {TOPICS}")

    try:
        for msg in consumer:
            if not running:
                break

            topic = msg.topic
            handler = TOPIC_HANDLERS.get(topic)
            if not handler:
                logger.warning(f"No handler for topic: {topic} — skipping")
                consumer.commit()
                continue

            success = False
            attempts = 0
            max_attempts = len(RETRY_INTERVALS) + 1  # 4 total

            while attempts < max_attempts and not success:
                try:
                    handler(msg.value)
                    success = True
                except Exception as e:
                    attempts += 1
                    logger.error(f"Error processing {topic} (attempt {attempts}/{max_attempts}): {e}")
                    if attempts < max_attempts:
                        backoff = RETRY_INTERVALS[attempts - 1]
                        logger.info(f"Retrying in {backoff}s...")
                        time.sleep(backoff)

            if not success:
                logger.error(f"Message failed after {max_attempts} attempts — routing to DLQ")
                route_to_dlq(dlq_producer, topic, msg.value, msg.key)

            # Commit offset regardless of success or DLQ routing
            consumer.commit()

    except Exception as e:
        logger.exception(f"Consumer encountered a fatal error: {e}")
    finally:
        logger.info("Closing consumer and DLQ producer...")
        consumer.close()
        dlq_producer.close()


if __name__ == "__main__":
    run()
