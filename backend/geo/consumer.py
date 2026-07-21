import asyncio
import json
import logging
from confluent_kafka import Consumer, Producer
import asyncpg
import hashlib
from config import settings

logger = logging.getLogger(__name__)

async def process_message(db_pool, msg, producer):
    try:
        topic = msg.topic()
        value = json.loads(msg.value().decode('utf-8'))
        data = value.get('data', value)
        
        status = data.get("status") or data.get("verdictStatus") or data.get("newState") or data.get("newStatus")
        decision = data.get("decision")
        is_confirmed = status in ["Action_Taken", "CONFIRMED_FRAUD"] or decision == "APPROVE" or topic == "CounterfeitScan.Submitted"
        
        if topic in ["case.updated", "prediction.overridden", "case.created"] and is_confirmed:
            case_id = data.get("caseId")
            jurisdiction = data.get("jurisdictionId", "UNKNOWN")
            lat = data.get("complaintLat")
            lon = data.get("complaintLon")
            risk_tier = data.get("riskTier", "LOW")
            
            if case_id and lat is not None and lon is not None:
                # Truncate location to some precision to cluster nearby incidents
                # or just use lat,lon hash. The contract says location_hash.
                loc_hash = hashlib.sha256(f"{round(lat,4)},{round(lon,4)}".encode()).hexdigest()
                
                async with db_pool.acquire() as conn:
                    await conn.execute("""
                    INSERT INTO fraud_hotspot (
                      jurisdiction_id,
                      geom,
                      location_hash,
                      risk_tier,
                      source_case_ids,
                      last_incident_at
                    )
                    VALUES (
                      $1,
                      ST_SetSRID(ST_MakePoint($2, $3), 4326),
                      $4,
                      $5,
                      ARRAY[$6::uuid],
                      NOW()
                    )
                    ON CONFLICT (jurisdiction_id, location_hash)
                    DO UPDATE SET
                      incident_count = fraud_hotspot.incident_count + 1,
                      risk_tier = EXCLUDED.risk_tier,
                      source_case_ids = array_append(fraud_hotspot.source_case_ids, $6::uuid),
                      last_incident_at = NOW(),
                      updated_at = NOW();
                    """, jurisdiction, lon, lat, loc_hash, risk_tier, case_id)
                    logger.info(f"Upserted geo point for case {case_id}")
                    
                    # Produce GeoLayer.Updated
                    producer.produce(
                        "GeoLayer.Updated",
                        value=json.dumps({"eventType": "GeoLayer.Updated", "data": {"jurisdictionId": jurisdiction, "locationHash": loc_hash}}).encode('utf-8')
                    )
                    producer.poll(0)
                    
    except Exception as e:
        logger.error(f"Error processing message from topic {msg.topic()}: {e}")

async def consume():
    db_pool = await asyncpg.create_pool(settings.DATABASE_URL, min_size=1, max_size=5)
    
    conf = {
        'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS,
        'group.id': settings.KAFKA_GROUP_ID,
        'auto.offset.reset': 'earliest'
    }
    
    producer_conf = {
        'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS
    }

    consumer = Consumer(conf)
    producer = Producer(producer_conf)
    
    topics = ['case.created', 'case.updated', 'prediction.overridden']
    consumer.subscribe(topics)
    
    logger.info(f"Subscribed to {topics}")
    
    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None:
                await asyncio.sleep(0.1)
                continue
            if msg.error():
                logger.error(f"Consumer error: {msg.error()}")
                continue
                
            await process_message(db_pool, msg, producer)
            
    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()
        producer.flush()
        await db_pool.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(consume())
