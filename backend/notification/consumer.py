import asyncio
import json
import logging
from confluent_kafka import Consumer, Producer
import httpx
import redis.asyncio as redis
from config import settings

logger = logging.getLogger(__name__)

async def process_standard_message(redis_client, msg, producer):
    try:
        topic = msg.topic()
        value = json.loads(msg.value().decode('utf-8'))
        event_type = value.get('eventType', topic)
        data = value.get('data', value)
        
        if topic == "Prediction.Completed":
            # Publish to redis pubsub
            await redis_client.publish("investigator_sse_events", json.dumps({
                "event": "prediction_completed",
                "data": {
                    "caseId": data.get("caseId", data.get("entityId")),
                    "fusedScore": data.get("fraudScore"),
                    "riskTier": data.get("riskTier", "HIGH")
                }
            }))
        elif topic == "Case.Assigned":
            # Publish to redis pubsub
            await redis_client.publish("investigator_sse_events", json.dumps({
                "event": "case_updated",
                "data": {
                    "caseId": data.get("caseId"),
                    "status": "Action_Taken",
                    "riskTier": data.get("riskTier", "HIGH")
                }
            }))
            # Dispatch SMS/Email -> STUB
            logger.info(f"[STUB] Sent SMS/Email to investigator for Case {data.get('caseId')}")
            
    except Exception as e:
        logger.error(f"Error processing standard message: {e}")

async def process_mha_message(http_client, msg, producer):
    try:
        topic = msg.topic()
        value = json.loads(msg.value().decode('utf-8'))
        data = value.get('data', value)
        
        if topic == "CallSession.Flagged":
            # Trigger MHA alert
            alert_payload = {
                "caseId": data.get("caseId", "unknown"),
                "alertType": "FRAUD_RING_DETECTED",
                "riskTier": "CRITICAL",
                "summary": data.get("summary", "Telecom interdiction triggered MHA alert."),
                "suspects": data.get("suspects", []),
                "jurisdictionId": data.get("jurisdictionId", "MHA_HQ"),
                "triggeredBy": "telecom-interdiction"
            }
            
            try:
                resp = await http_client.post(
                    settings.MHA_WEBHOOK_URL,
                    json=alert_payload,
                    timeout=4.0
                )
                logger.info(f"MHA Webhook triggered, status {resp.status_code}")
            except Exception as e:
                logger.error(f"Failed to post to MHA webhook: {e}")
                
            # Publish MHAAlert.Sent
            producer.produce("MHAAlert.Sent", json.dumps({
                "eventType": "MHAAlert.Sent",
                "data": {
                    "caseId": alert_payload["caseId"],
                    "alertType": alert_payload["alertType"],
                    "jurisdictionId": alert_payload["jurisdictionId"]
                }
            }).encode('utf-8'))
            producer.poll(0)

    except Exception as e:
        logger.error(f"Error processing MHA message: {e}")


def consume_loop(consumer, topics, process_func, *args):
    consumer.subscribe(topics)
    while True:
        msg = consumer.poll(1.0)
        if msg is None:
            yield None
            continue
        if msg.error():
            logger.error(f"Consumer error: {msg.error()}")
            continue
        yield msg


async def standard_consumer_task():
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    conf = {
        'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS,
        'group.id': 'notification-service-consumer',
        'auto.offset.reset': 'earliest'
    }
    producer = Producer({'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS})
    consumer = Consumer(conf)
    
    logger.info("Starting standard notification consumer...")
    
    try:
        for msg in consume_loop(consumer, ["Prediction.Completed", "Case.Assigned"]):
            if msg is None:
                await asyncio.sleep(0.1)
                continue
            await process_standard_message(redis_client, msg, producer)
    finally:
        consumer.close()
        await redis_client.close()

async def mha_consumer_task():
    http_client = httpx.AsyncClient()
    conf = {
        'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS,
        'group.id': 'mha-alert-priority',
        'auto.offset.reset': 'earliest'
    }
    producer = Producer({'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS})
    consumer = Consumer(conf)
    
    logger.info("Starting MHA high-priority consumer...")
    
    try:
        for msg in consume_loop(consumer, ["CallSession.Flagged"]):
            if msg is None:
                await asyncio.sleep(0.1)
                continue
            await process_mha_message(http_client, msg, producer)
    finally:
        consumer.close()
        await http_client.aclose()


async def main():
    await asyncio.gather(
        standard_consumer_task(),
        mha_consumer_task()
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
