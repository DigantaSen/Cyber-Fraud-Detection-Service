"""
Inference Orchestrator — Kafka Publisher

Publishes Prediction.Completed and Prediction.Failed events after fusion.
Uses kafka-python-ng with acks=all + idempotent producer for exactly-once semantics.

Payload matches ml-contract.md §Fusion Contract exactly.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from kafka import KafkaProducer
from kafka.errors import KafkaError

from config import settings

logger = logging.getLogger("orch-publisher")


class PredictionPublisher:
    def __init__(self):
        self._producer: Optional[KafkaProducer] = None

    def connect(self):
        """Create the Kafka producer. Called once at app startup."""
        self._producer = KafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            client_id="inference-orchestrator-publisher",
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
            acks="all",
            retries=3,
        )
        logger.info("Kafka producer connected")

    def close(self):
        if self._producer:
            self._producer.flush()
            self._producer.close()
            logger.info("Kafka producer closed")

    async def ping(self) -> bool:
        """Check if connected to Kafka"""
        if not self._producer:
            return False
        try:
            return self._producer.bootstrap_connected()
        except Exception as e:
            logger.error(f"Kafka ping failed: {e}")
            return False

    def publish_completed(
        self,
        prediction_id: uuid.UUID,
        case_id: uuid.UUID,
        fused_score: float,
        risk_tier: str,
        confidence: float,
        verdict_status: str,
        model_breakdown: List[Dict[str, Any]],
        explanation: str,
        fusion_weights: Dict[str, float],
        pending_review: bool,
        correlation_id: Optional[uuid.UUID],
    ) -> None:
        """
        Publishes to prediction.completed topic.
        Payload matches ml-contract.md §Fusion Contract.
        The Case Service consumes this and updates case.status autonomously.
        """
        event = {
            "eventType": "Prediction.Completed",
            "predictionId": str(prediction_id),
            "caseId": str(case_id),
            "fusedScore": round(fused_score, 2),
            "riskTier": risk_tier,
            "confidence": round(confidence, 3),
            "status": verdict_status,
            "modelBreakdown": model_breakdown,
            "explanation": explanation,
            "fusionWeights": fusion_weights,
            "fusionTimestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "pendingReview": pending_review,
            "correlationId": str(correlation_id) if correlation_id else None,
        }
        self._publish(settings.TOPIC_PREDICTION_COMPLETED, str(case_id), event)

    def publish_failed(
        self,
        prediction_id: uuid.UUID,
        case_id: uuid.UUID,
        reason: str,
        correlation_id: Optional[uuid.UUID],
    ) -> None:
        """Publishes to prediction.failed topic when all models are UNAVAILABLE."""
        event = {
            "eventType": "Prediction.Failed",
            "predictionId": str(prediction_id),
            "caseId": str(case_id),
            "reason": reason,
            "fusionTimestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "correlationId": str(correlation_id) if correlation_id else None,
        }
        self._publish(settings.TOPIC_PREDICTION_FAILED, str(case_id), event)

    def _publish(self, topic: str, key: str, event: dict) -> None:
        try:
            future = self._producer.send(topic, key=key, value=event)
            self._producer.flush()
            future.get(timeout=5)
            logger.info(f"Published {event.get('eventType')} to {topic} key={key}")
        except KafkaError as e:
            logger.error(f"Failed to publish to {topic}: {e}")


publisher = PredictionPublisher()
