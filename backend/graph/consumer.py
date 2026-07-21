import asyncio
import json
import logging
from confluent_kafka import Consumer, Producer, KafkaException
from neo4j import AsyncGraphDatabase
from config import settings

logger = logging.getLogger(__name__)

async def process_message(driver, msg, producer):
    try:
        topic = msg.topic()
        value = json.loads(msg.value().decode('utf-8'))
        event_type = value.get('eventType', topic)
        data = value.get('data', value)
        
        async with driver.session() as session:
            if topic == "case.created":
                case_id = data.get("caseId")
                risk_tier = data.get("riskTier", "UNKNOWN")
                suspect_phone = data.get("suspectPhone")
                
                if case_id and suspect_phone:
                    await session.run("""
                    MERGE (a:Entity:Phone {id: $suspectPhone})
                    MERGE (b:Entity:Case {id: $caseId})
                    SET b.riskTier = $riskTier
                    MERGE (b)-[r:LINKED_TO]->(a)
                    """, suspectPhone=suspect_phone, caseId=case_id, riskTier=risk_tier)
                    
            elif topic == "telecom.event.ingested":
                caller = data.get("caller")
                receiver = data.get("receiver")
                
                if caller and receiver:
                    await session.run("""
                    MERGE (a:Entity:Phone {id: $caller})
                    MERGE (b:Entity:Phone {id: $receiver})
                    MERGE (a)-[r:CALLED]->(b)
                    ON CREATE SET r.count = 1
                    ON MATCH SET r.count = r.count + 1
                    """, caller=caller, receiver=receiver)
                    
            elif topic == "transaction.ingested":
                source = data.get("sourceAccount")
                dest = data.get("destinationAccount")
                amount = data.get("amount", 0)
                
                if source and dest:
                    await session.run("""
                    MERGE (a:Entity:BankAccount {id: $source})
                    MERGE (b:Entity:BankAccount {id: $dest})
                    MERGE (a)-[r:TRANSACTED_WITH]->(b)
                    ON CREATE SET r.count = 1, r.amountTotalINR = $amount
                    ON MATCH SET r.count = r.count + 1, r.amountTotalINR = r.amountTotalINR + $amount
                    """, source=source, dest=dest, amount=amount)
                    
            elif topic == "prediction.completed":
                entity_id = data.get("entityId")
                fraud_score = data.get("fraudScore")
                
                if entity_id and fraud_score is not None:
                    await session.run("""
                    MERGE (e:Entity {id: $entityId})
                    SET e.fraudScore = $fraudScore
                    """, entityId=entity_id, fraudScore=fraud_score)

    except Exception as e:
        logger.error(f"Error processing message from topic {msg.topic()}: {e}")

async def consume():
    driver = AsyncGraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    )
    
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
    
    topics = ['case.created', 'prediction.completed', 'telecom.event.ingested', 'transaction.ingested']
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
                
            await process_message(driver, msg, producer)
            
    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()
        await driver.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(consume())
