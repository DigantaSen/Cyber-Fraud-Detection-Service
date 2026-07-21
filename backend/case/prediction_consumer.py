"""Consume inference results and update only the case workflow projection."""

import asyncio
import json
import logging
import uuid

from aiokafka import AIOKafkaConsumer

from config import settings
from services.case_service import CaseService

logger = logging.getLogger("case-prediction-consumer")


async def run_prediction_consumer(session_factory) -> None:
    """Process prediction events at-least-once; state updates are idempotent."""
    consumer = AIOKafkaConsumer(
        "prediction.completed",
        "prediction.failed",
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id="case-prediction-consumer",
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        value_deserializer=lambda value: json.loads(value.decode("utf-8")),
    )
    await consumer.start()
    logger.info("Prediction consumer started")
    try:
        async for message in consumer:
            payload = message.value
            try:
                correlation_id = uuid.UUID(payload.get("correlationId")) if payload.get("correlationId") else uuid.uuid4()
                if message.topic == "prediction.failed":
                    payload = {
                        **payload,
                        "status": "INCOMPLETE",
                        "pendingReview": True,
                    }
                async with session_factory() as session:
                    await CaseService(session).apply_prediction_result(payload, correlation_id)
                await consumer.commit()
            except Exception:
                logger.exception("Could not apply prediction event; leaving offset uncommitted")
                await asyncio.sleep(1)
    except asyncio.CancelledError:
        logger.info("Prediction consumer stopped")
        raise
    finally:
        await consumer.stop()
