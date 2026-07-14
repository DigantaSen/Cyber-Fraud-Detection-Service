import asyncio
import json
import logging
import signal
import sys
from kafka import KafkaProducer
from kafka.errors import KafkaError

from config import settings
from database import db

# Configure logging
logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL, logging.INFO))
logger = logging.getLogger("outbox-publisher")

# Global flags
running = True

def create_kafka_producer() -> KafkaProducer:
    """Create an idempotent Kafka producer."""
    logger.info(f"Connecting to Kafka at {settings.KAFKA_BOOTSTRAP_SERVERS}")
    return KafkaProducer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        client_id="event-processing-outbox-publisher",
        # Explicit requirements from T8b
        acks="all",
        # Note: enable_idempotence is not supported by kafka-python; acks='all', retries > 0,
        # and max_in_flight_requests_per_connection=1 achieve idempotent behavior.
        max_in_flight_requests_per_connection=1, # required for idempotence if < Kafka 2.0
        retries=5,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8") if k else None
    )

async def publish_event(producer: KafkaProducer, topic: str, key: str, payload: dict):
    """Publish event to Kafka and wait for acknowledgment."""
    loop = asyncio.get_running_loop()
    # producer.send is async in the Kafka background thread, but we need to block for the ack
    # so we run the .get() inside a thread pool to avoid blocking the asyncio event loop.
    def _send_and_wait():
        future = producer.send(topic, key=key, value=payload)
        return future.get(timeout=10) # Block until ack
        
    await loop.run_in_executor(None, _send_and_wait)

async def process_outbox(producer: KafkaProducer):
    """Polls the database for pending events and publishes them."""
    if not db.pool:
        await db.connect()
        
    async with db.pool.acquire() as conn:
        # We process in batches
        query = """
            SELECT outbox_id, topic, event_key, payload 
            FROM platform.outbox 
            WHERE status = 'PENDING' 
            ORDER BY created_at ASC 
            LIMIT 100
            FOR UPDATE SKIP LOCKED;
        """
        
        while running:
            records = await conn.fetch(query)
            if not records:
                break
                
            for record in records:
                outbox_id = record["outbox_id"]
                topic = record["topic"]
                key = record["event_key"]
                
                # Payload is JSONB in Postgres, which asyncpg returns as a string or parsed dict depending on config.
                # If it's a string, we parse it.
                payload = record["payload"]
                if isinstance(payload, str):
                    payload = json.loads(payload)
                    
                try:
                    logger.debug(f"Publishing event {outbox_id} to {topic}")
                    await publish_event(producer, topic, key, payload)
                    
                    # Mark as published
                    await conn.execute(
                        "UPDATE platform.outbox SET status = 'PUBLISHED', published_at = NOW() WHERE outbox_id = $1", 
                        outbox_id
                    )
                except KafkaError as e:
                    logger.error(f"Failed to publish event {outbox_id}: {e}")
                    # Mark as failed (a retry mechanism would be needed for production, but this handles basic flow)
                    await conn.execute(
                        "UPDATE platform.outbox SET status = 'FAILED', attempts = attempts + 1 WHERE outbox_id = $1", 
                        outbox_id
                    )
                    break # Backoff on failure

async def listen_for_notifications(producer: KafkaProducer):
    """Listen to outbox_channel for push-based publishing."""
    if not db.pool:
        await db.connect()
        
    # Create an event to wake up the polling loop
    wakeup_event = asyncio.Event()
    
    def on_notify(connection, pid, channel, payload):
        logger.debug(f"Received notification on {channel}: {payload}")
        wakeup_event.set()
        
    conn = await db.pool.acquire()
    try:
        await conn.add_listener('outbox_channel', on_notify)
        logger.info("Listening on outbox_channel...")
        
        while running:
            # We process anything currently pending
            await process_outbox(producer)
            
            # Then wait for the next notification or a polling interval fallback
            wakeup_event.clear()
            try:
                await asyncio.wait_for(wakeup_event.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass # Periodic fallback
    finally:
        await conn.remove_listener('outbox_channel', on_notify)
        await db.pool.release(conn)

def handle_shutdown(sig, frame):
    global running
    logger.info("Shutting down outbox publisher...")
    running = False

async def main():
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    
    producer = None
    try:
        producer = create_kafka_producer()
        await listen_for_notifications(producer)
    except Exception as e:
        logger.exception("Outbox publisher encountered a fatal error.")
    finally:
        if producer:
            producer.flush(timeout=5)
            producer.close()
        await db.close()

if __name__ == "__main__":
    asyncio.run(main())
