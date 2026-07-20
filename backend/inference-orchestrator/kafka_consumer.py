"""
Inference Orchestrator — Kafka Consumer

Subscribes to case.created and evidence.uploaded topics.
Runs as a background asyncio.Task started in FastAPI lifespan.

Uses aiokafka (async-native) instead of kafka-python-ng + asyncio.run() because
this consumer runs inside FastAPI's already-running asyncio event loop.
asyncio.run() inside a running loop raises RuntimeError — aiokafka avoids this.

DLQ / retry:
  3 retries with exponential backoff (1s, 5s, 30s) per message.
  After max retries, message is routed to <topic>.DLQ via a sync KafkaProducer.
  This mirrors the platform standard from T8b's RetryableKafkaConsumer,
  re-implemented here for the aiokafka API.
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Optional

from aiokafka import AIOKafkaConsumer
from kafka import KafkaProducer

from config import settings
from orchestrator import (
    AnalyzeRequest,
    ComplaintPayload,
    EvidenceRef,
    analyze,
)

logger = logging.getLogger("orch-consumer")

TOPICS = [settings.TOPIC_CASE_CREATED, settings.TOPIC_EVIDENCE_UPLOADED]
RETRY_INTERVALS = [1, 5, 30]  # seconds — exponential backoff matching platform standard


def _make_dlq_producer() -> KafkaProducer:
    return KafkaProducer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        client_id="orch-dlq-producer",
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )


async def _handle_case_created(payload: dict, http_client) -> None:
    """Build an AnalyzeRequest from a case.created event and invoke the engine."""
    case_id_raw = payload.get("caseId") or payload.get("case_id")
    if not case_id_raw:
        logger.warning("case.created event missing caseId — skipping")
        return

    try:
        case_id = uuid.UUID(case_id_raw)
    except ValueError:
        logger.warning(f"case.created event has invalid caseId={case_id_raw!r} — skipping")
        return

    corr_raw = payload.get("correlationId") or payload.get("correlation_id")
    correlation_id = uuid.UUID(corr_raw) if corr_raw else None

    evidence_refs = [
        EvidenceRef(evidence_id=e.get("evidenceId", ""), mime_type=e.get("mimeType", ""))
        for e in payload.get("evidenceRefs", [])
    ]

    request = AnalyzeRequest(
        case_id=case_id,
        trigger_type="CASE_CREATED",
        complaint=ComplaintPayload(
            title=payload.get("title", ""),
            description=payload.get("description", ""),
            complaint_type=payload.get("complaintType", "OTHER"),
            suspect_phone=payload.get("suspectPhone"),
            suspect_account=payload.get("suspectAccount"),
            language_code=payload.get("languageCode", "en"),
        ),
        evidence_refs=evidence_refs,
        sync=False,
        correlation_id=correlation_id,
    )

    await analyze(request, http_client)


async def _handle_evidence_uploaded(payload: dict, http_client) -> None:
    """
    Re-trigger analysis when relevant new evidence arrives.
    Only fires for audio/* or image/* MIME types — text documents don't activate
    the audio or counterfeit models and would produce an identical verdict.
    """
    mime_type = payload.get("mimeType", "")
    if not (mime_type.startswith("audio/") or mime_type.startswith("image/")):
        logger.debug(f"evidence.uploaded: mimeType={mime_type} — no model re-trigger needed, skipping")
        return

    case_id_raw = payload.get("caseId")
    if not case_id_raw:
        return

    try:
        case_id = uuid.UUID(case_id_raw)
    except ValueError:
        return

    corr_raw = payload.get("correlationId")
    correlation_id = uuid.UUID(corr_raw) if corr_raw else None

    request = AnalyzeRequest(
        case_id=case_id,
        trigger_type="EVIDENCE_UPLOADED",
        complaint=ComplaintPayload(
            title=payload.get("title", ""),
            description=payload.get("description", ""),
            complaint_type=payload.get("complaintType", "OTHER"),
            language_code=payload.get("languageCode", "en"),
        ),
        evidence_refs=[
            EvidenceRef(
                evidence_id=payload.get("evidenceId", ""),
                mime_type=mime_type,
            )
        ],
        sync=False,
        correlation_id=correlation_id,
    )

    await analyze(request, http_client)


async def run_consumer(http_client) -> None:
    """
    Long-running coroutine. Started as asyncio.create_task() in FastAPI lifespan.
    Consumes case.created and evidence.uploaded with 3-retry + DLQ routing.
    """
    consumer = AIOKafkaConsumer(
        *TOPICS,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=settings.KAFKA_GROUP_ID,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
    )

    dlq_producer = _make_dlq_producer()

    await consumer.start()
    logger.info(f"Kafka consumer started — topics: {TOPICS} group: {settings.KAFKA_GROUP_ID}")

    try:
        async for msg in consumer:
            topic = msg.topic
            payload = msg.value
            event_type = payload.get("eventType", topic)

            success = False
            for attempt in range(len(RETRY_INTERVALS) + 1):
                try:
                    if topic == settings.TOPIC_CASE_CREATED:
                        await _handle_case_created(payload, http_client)
                    elif topic == settings.TOPIC_EVIDENCE_UPLOADED:
                        await _handle_evidence_uploaded(payload, http_client)
                    success = True
                    break
                except Exception as e:
                    logger.error(f"Error processing {topic} attempt {attempt + 1}: {e}")
                    if attempt < len(RETRY_INTERVALS):
                        wait = RETRY_INTERVALS[attempt]
                        logger.info(f"Retrying in {wait}s...")
                        await asyncio.sleep(wait)

            if not success:
                dlq_topic = f"{topic}.DLQ"
                try:
                    dlq_producer.send(dlq_topic, value=payload)
                    dlq_producer.flush()
                    logger.error(f"Message routed to DLQ: {dlq_topic}")
                except Exception as dlq_err:
                    logger.error(f"FATAL: could not route to DLQ {dlq_topic}: {dlq_err}")

            await consumer.commit()

    except asyncio.CancelledError:
        logger.info("Kafka consumer task cancelled — shutting down")
    finally:
        await consumer.stop()
        dlq_producer.close()
        logger.info("Kafka consumer stopped")
