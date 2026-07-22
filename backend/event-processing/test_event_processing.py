import sys
import os
import time
import asyncio
import uuid
import threading
import signal
import json
import logging

# Configure test logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("test-suite")

# Monkeypatch selectors.BaseSelector.unregister to avoid "Invalid file descriptor: -1" on Windows
import selectors
try:
    # Get the selector implementation class used on Windows
    selector_cls = selectors.SelectSelector
except AttributeError:
    selector_cls = selectors.BaseSelector

original_unregister = selector_cls.unregister
def patched_unregister(self, fileobj):
    try:
        return original_unregister(self, fileobj)
    except (ValueError, KeyError):
        return None
selector_cls.unregister = patched_unregister

# Add backend/event-processing to sys.path
sys.path.insert(0, r"c:\Users\digan\VSCode\Hackathons\AI_Fraud_Detection_System\backend\event-processing")

# Override settings via env variables before importing
os.environ["DATABASE_URL"] = "postgresql+asyncpg://platform_user:change_me_postgres@localhost:5435/platform"
os.environ["DSN"] = "postgresql://platform_user:change_me_postgres@localhost:5435/platform"
os.environ["KAFKA_BOOTSTRAP_SERVERS"] = "localhost:29092"
os.environ["LOG_LEVEL"] = "INFO"
os.environ["TELECOM_WEBHOOK_SECRET"] = "change_me_telecom"
os.environ["BANK_WEBHOOK_SECRET"] = "change_me_bank"
os.environ["COUNTERFEIT_WEBHOOK_SECRET"] = "change_me_counterfeit"

# Monkeypatch signal.signal to avoid "signal only works in main thread" in threads
original_signal = signal.signal
def dummy_signal(sig, handler):
    return None
signal.signal = dummy_signal

from config import settings
from database import db
from main import app
import outbox_publisher
from consumer import RetryableKafkaConsumer, dlq_depth_counter

# We will use FastAPI TestClient
from fastapi.testclient import TestClient
import hmac
import hashlib

def get_hmac_header(payload_str: str, secret: str) -> dict:
    body_bytes = payload_str.encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    return {"X-HMAC-Signature": f"sha256={sig}"}

async def init_db_schema():
    logger.info("Initializing platform schema and outbox table in Postgres...")
    import asyncpg
    # Connect directly to Postgres on localhost
    conn = await asyncpg.connect(settings.DSN)
    try:
        # Create platform schema
        await conn.execute("CREATE SCHEMA IF NOT EXISTS platform;")
        
        # Create platform.outbox table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS platform.outbox (
              outbox_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              aggregate_type VARCHAR(64) NOT NULL,
              aggregate_id UUID NOT NULL,
              event_type VARCHAR(128) NOT NULL,
              topic VARCHAR(128) NOT NULL,
              event_key TEXT NOT NULL,
              payload JSONB NOT NULL,
              correlation_id UUID,
              status VARCHAR(32) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','PUBLISHED','FAILED')),
              attempts INTEGER NOT NULL DEFAULT 0,
              next_attempt_at TIMESTAMPTZ,
              published_at TIMESTAMPTZ,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        
        # Create indexes
        await conn.execute("CREATE INDEX IF NOT EXISTS outbox_pending_idx ON platform.outbox (status, created_at) WHERE status = 'PENDING';")
        await conn.execute("CREATE INDEX IF NOT EXISTS outbox_aggregate_idx ON platform.outbox (aggregate_type, aggregate_id);")
        
        # Create trigger function
        await conn.execute("""
            CREATE OR REPLACE FUNCTION platform.notify_outbox()
            RETURNS trigger AS $$
            BEGIN
              PERFORM pg_notify('outbox_channel', NEW.outbox_id::text);
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)
        
        # Create trigger
        await conn.execute("DROP TRIGGER IF EXISTS outbox_notify_after_insert ON platform.outbox;")
        await conn.execute("""
            CREATE TRIGGER outbox_notify_after_insert
            AFTER INSERT ON platform.outbox
            FOR EACH ROW EXECUTE FUNCTION platform.notify_outbox();
        """)
        
        # Clear outbox table for clean test run
        await conn.execute("TRUNCATE platform.outbox;")
        logger.info("Database schema and trigger initialized successfully.")
    except Exception as e:
        logger.error(f"Error during schema initialization: {e}")
        raise e
    finally:
        await conn.close()

# Global publisher process reference for clean teardown
publisher_proc = None

def main_test():
    global publisher_proc
    # 1. Init Database Schema
    asyncio.run(init_db_schema())
    
    # 2. Start Publisher in background process
    logger.info("Starting outbox publisher process...")
    import subprocess
    env = os.environ.copy()
    publisher_proc = subprocess.Popen(
        [sys.executable, r"c:\Users\digan\VSCode\Hackathons\AI_Fraud_Detection_System\backend\event-processing\outbox_publisher.py"],
        env=env
    )
    
    # Wait for publisher to initialize
    time.sleep(3)
    
    # 3. Create TestClient
    client = TestClient(app)
    
    # 4. Test Live and Ready healthchecks
    logger.info("Testing Health endpoints...")
    # Call startup events for FastAPI app
    with client as client:
        # Check health
        res = client.get("/health/live")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        assert res.json() == {"status": "ok"}
        logger.info("✔ Live Healthcheck OK")
        
        res = client.get("/health/ready")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        assert res.json() == {"status": "ok"}
        logger.info("✔ Ready Healthcheck OK")
        
        # Ingestions lists to verify later
        ingested_telecom_ids = []
        ingested_bank_ids = []
        ingested_counterfeit_ids = []
        
        # 5. Ingest Telecom Async path
        logger.info("Testing Telecom Event Async Ingestion...")
        telecom_payload = {
            "sessionId": f"sess-{uuid.uuid4()}",
            "callerPhone": "+919876543210",
            "calleePhone": "+918765432109",
            "eventType": "CALL_INITIATED",
            "durationSeconds": 0,
            "timestamp": "2026-07-13T21:42:00Z"
        }
        telecom_str = json.dumps(telecom_payload)
        headers = get_hmac_header(telecom_str, settings.TELECOM_WEBHOOK_SECRET)
        headers["Content-Type"] = "application/json"
        res = client.post("/api/v1/events/telecom-stream", content=telecom_str, headers=headers)
        assert res.status_code == 202, f"Expected 202, got {res.status_code}"
        data = res.json()
        assert data["status"] == "success", f"Expected success envelope, got {data}"
        assert "requestId" in data
        assert "correlationId" in data
        assert data["data"]["acknowledged"] is True
        ingested_telecom_ids.append(telecom_payload["sessionId"])
        logger.info(f"✔ Telecom Async Ingest OK: {data}")
        
        # 6. Ingest Telecom Sync path (SLA < 300ms)
        logger.info("Testing Telecom Event Sync Ingestion (Interdiction path)...")
        telecom_sync_payload = {
            "sessionId": f"sess-{uuid.uuid4()}",
            "callerPhone": "+919876543210",
            "calleePhone": "+918765432108",
            "audioChunkBase64": "SGVsbG8gV29ybGQ=",
            "complaintContext": "Impersonation suspect calling from suspected device"
        }
        telecom_sync_str = json.dumps(telecom_sync_payload)
        headers = get_hmac_header(telecom_sync_str, settings.TELECOM_WEBHOOK_SECRET)
        headers["Content-Type"] = "application/json"
        res = client.post("/api/v1/events/interdict", content=telecom_sync_str, headers=headers)
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        sync_data = res.json()
        assert sync_data["status"] == "success", f"Expected success envelope, got {sync_data}"
        assert "requestId" in sync_data
        assert "correlationId" in sync_data
        assert sync_data["data"]["decision"] == "BLOCK"
        assert sync_data["data"]["confidence"] == 0.94
        assert sync_data["data"]["riskTier"] == "CRITICAL"
        assert "interdictionId" in sync_data["data"]
        ingested_telecom_ids.append(telecom_sync_payload["sessionId"])
        logger.info(f"✔ Telecom Sync Ingest OK: {sync_data}")
        
        # 7. Ingest Bank Transaction path
        logger.info("Testing Bank Transaction Ingestion...")
        bank_payload = {
            "transactionId": f"tx-{uuid.uuid4()}",
            "fromAccount": "ACC-111",
            "toAccount": "ACC-222",
            "amountINR": 45000.0,
            "transactionType": "IMPS",
            "timestamp": "2026-07-13T21:44:00Z"
        }
        bank_str = json.dumps(bank_payload)
        headers = get_hmac_header(bank_str, settings.BANK_WEBHOOK_SECRET)
        headers["Content-Type"] = "application/json"
        res = client.post("/api/v1/events/bank-transaction", content=bank_str, headers=headers)
        assert res.status_code == 202, f"Expected 202, got {res.status_code}"
        data = res.json()
        assert data["status"] == "success", f"Expected success envelope, got {data}"
        assert data["data"]["acknowledged"] is True
        ingested_bank_ids.append(bank_payload["transactionId"])
        logger.info(f"✔ Bank Ingest OK: {data}")
        
        # 8. Ingest Counterfeit Scan path
        logger.info("Testing Counterfeit Scan Ingestion...")
        counterfeit_payload = {
            "scanId": f"scan-{uuid.uuid4()}",
            "deviceFingerprint": "dev-999",
            "scannedAt": "2026-07-13T21:45:00Z",
            "denomination": 500,
            "edgeScore": 87,
            "isAuthentic": False
        }
        counterfeit_str = json.dumps(counterfeit_payload)
        headers = get_hmac_header(counterfeit_str, settings.COUNTERFEIT_WEBHOOK_SECRET)
        headers["Content-Type"] = "application/json"
        res = client.post("/api/v1/events/counterfeit-scan", content=counterfeit_str, headers=headers)
        assert res.status_code == 202, f"Expected 202, got {res.status_code}"
        data = res.json()
        assert data["status"] == "success", f"Expected success envelope, got {data}"
        assert data["data"]["acknowledged"] is True
        ingested_counterfeit_ids.append(counterfeit_payload["scanId"])
        logger.info(f"✔ Counterfeit Ingest OK: {data}")
        
        # Wait a bit for the publisher to pull from Postgres outbox and publish to Kafka
        logger.info("Waiting for the outbox publisher to process the messages (5 seconds)...")
        time.sleep(5)
        
        # 9. Verify Database status is PUBLISHED
        logger.info("Verifying outbox records in Postgres...")
        async def verify_outbox_published():
            import asyncpg
            conn = await asyncpg.connect(settings.DSN)
            try:
                records = await conn.fetch("SELECT event_key, topic, status FROM platform.outbox;")
                for r in records:
                    logger.info(f"Outbox Record: key={r['event_key']}, topic={r['topic']}, status={r['status']}")
                    # All should have been published successfully
                    assert r["status"] == "PUBLISHED", f"Expected PUBLISHED, got {r['status']}"
                assert len(records) >= 5, f"Expected at least 5 outbox entries, got {len(records)}"
                logger.info("✔ All outbox records are PUBLISHED in Database")
            finally:
                await conn.close()
        
        asyncio.run(verify_outbox_published())
        
        # 10. Test consuming from Kafka topics using RetryableKafkaConsumer
        logger.info("Testing Kafka Consumer by reading messages from topics...")
        received_messages = []
        def handle_msg(val):
            logger.info(f"Consumer handler received: {val}")
            received_messages.append(val)
            
        # We start a consumer on topics
        consumer_topics = [
            "telecom.event.ingested",
            "callsession.initiated",
            "intervention.requested",
            "transaction.ingested",
            "counterfeit.scan.submitted"
        ]
        
        consumer = RetryableKafkaConsumer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id="test-verifier-group",
            topics=consumer_topics
        )
        
        # Run consumer in a separate thread for a few seconds to drain messages
        def run_consumer_loop():
            consumer.start_consuming(handle_msg)
            
        consumer_thread = threading.Thread(target=run_consumer_loop, daemon=True)
        consumer_thread.start()
        
        # Wait for consumer to process messages
        time.sleep(6)
        consumer.stop()
        consumer_thread.join()
        
        # Verify messages received
        assert len(received_messages) >= 5, f"Expected at least 5 consumed messages, got {len(received_messages)}"
        logger.info("✔ Kafka Consumer successfully consumed all ingested messages")
        
        # 11. Test Consumer 3-Retry Backoff & DLQ Routing
        logger.info("Testing Consumer 3-Retry Backoff and DLQ routing...")
        
        # Ingest a message that will fail
        fail_payload = {
            "transactionId": f"fail-tx-{uuid.uuid4()}",
            "fromAccount": "ACC-FAIL",
            "toAccount": "ACC-DLQ",
            "amountINR": 999999.0,
            "transactionType": "UPI",
            "timestamp": "2026-07-13T21:46:00Z"
        }
        fail_str = json.dumps(fail_payload)
        headers = get_hmac_header(fail_str, settings.BANK_WEBHOOK_SECRET)
        headers["Content-Type"] = "application/json"
        res = client.post("/api/v1/events/bank-transaction", content=fail_str, headers=headers)
        assert res.status_code == 202, f"Expected 202, got {res.status_code}"
        logger.info("✔ Ingested failure-testing transaction")
        
        # Wait for outbox publisher
        time.sleep(3)
        
        # Create consumer for the failure test
        fail_consumer = RetryableKafkaConsumer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id="test-fail-group",
            topics=["transaction.ingested"]
        )
        # Patch the retry intervals to be very fast for this test
        fail_consumer.retry_intervals = [0.1, 0.2, 0.3]
        
        # Handler that always fails for this specific transaction
        def handle_fail(val):
            if val.get("transactionId") == fail_payload["transactionId"]:
                logger.info(f"Raising mock processing exception for: {val['transactionId']}")
                raise ValueError("Mock processing error")
            else:
                logger.info(f"Skipping processing for different key: {val}")
                
        # Run consumer in background
        def run_fail_consumer():
            fail_consumer.start_consuming(handle_fail)
            
        fail_consumer_thread = threading.Thread(target=run_fail_consumer, daemon=True)
        fail_consumer_thread.start()
        
        # Wait for consumer to run through the retries (0.1s + 0.2s + 0.3s + processing times)
        time.sleep(12)
        fail_consumer.stop()
        fail_consumer_thread.join()
        
        # Now consume from the DLQ topic to verify it arrived there
        logger.info("Consuming from DLQ topic: transaction.ingested.DLQ ...")
        dlq_consumer = RetryableKafkaConsumer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id="test-dlq-group",
            topics=["transaction.ingested.DLQ"]
        )
        
        dlq_received = []
        def handle_dlq(val):
            logger.info(f"DLQ Consumer received: {val}")
            dlq_received.append(val)
            
        dlq_consumer_thread = threading.Thread(target=lambda: dlq_consumer.start_consuming(handle_dlq), daemon=True)
        dlq_consumer_thread.start()
        
        time.sleep(12)
        dlq_consumer.stop()
        dlq_consumer_thread.join()
        
        # Check that the failed message is in the DLQ
        dlq_ids = [m.get("transactionId") for m in dlq_received if m]
        assert fail_payload["transactionId"] in dlq_ids, f"Failed transaction {fail_payload['transactionId']} was not found in DLQ list: {dlq_ids}"
        logger.info("✔ DLQ routing verified. The message was successfully routed to the DLQ after failures.")
        
        logger.info("ALL TESTS COMPLETED SUCCESSFULLY!")

if __name__ == "__main__":
    try:
        main_test()
    except Exception as e:
        logger.exception("Test run failed!")
        sys.exit(1)
    finally:
        if publisher_proc:
            logger.info("Stopping outbox publisher process...")
            publisher_proc.terminate()
            try:
                publisher_proc.wait(timeout=5)
            except Exception:
                publisher_proc.kill()
