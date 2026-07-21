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
                complaint_type = data.get("complaintType", "UNKNOWN")
                suspect_phone = data.get("suspectPhone")
                suspect_account = data.get("suspectAccount")
                reporter_phone = data.get("reporterPhone")
                
                if not case_id:
                    return

                # 1. Always create/merge the Case node
                await session.run(
                    "MERGE (b:Entity:Case {id: $caseId}) SET b.riskTier = $riskTier, b.complaintType = $complaintType",
                    caseId=case_id, riskTier=risk_tier, complaintType=complaint_type
                )

                # 2. Link Suspect Phone to Case
                if suspect_phone:
                    await session.run(
                        "MERGE (a:Entity:Phone {id: $suspectPhone}) MERGE (b:Entity:Case {id: $caseId}) MERGE (b)-[r:LINKED_TO]->(a)",
                        suspectPhone=suspect_phone, caseId=case_id
                    )

                # 3. Link Suspect Bank/UPI Account to Case & Phone
                if suspect_account:
                    await session.run(
                        "MERGE (b:Entity:Case {id: $caseId}) MERGE (acc:Entity:BankAccount {id: $suspectAccount}) MERGE (b)-[r:HAS_ACCOUNT]->(acc)",
                        caseId=case_id, suspectAccount=suspect_account
                    )
                    if suspect_phone:
                        await session.run(
                            "MERGE (p:Entity:Phone {id: $suspectPhone}) MERGE (acc:Entity:BankAccount {id: $suspectAccount}) MERGE (p)-[r:HAS_ACCOUNT]->(acc)",
                            suspectPhone=suspect_phone, suspectAccount=suspect_account
                        )

                # 4. Link Reporter/Victim Phone to Case
                if reporter_phone:
                    await session.run(
                        "MERGE (b:Entity:Case {id: $caseId}) MERGE (v:Entity:Phone {id: $reporterPhone}) SET v.isVictim = true MERGE (v)-[r:REPORTED]->(b)",
                        caseId=case_id, reporterPhone=reporter_phone
                    )
                    
            elif topic == "telecom.event.ingested":
                caller = data.get("caller")
                receiver = data.get("receiver")
                
                if caller and receiver:
                    await session.run(
                        "MERGE (a:Entity:Phone {id: $caller}) MERGE (b:Entity:Phone {id: $receiver}) MERGE (a)-[r:CALLED]->(b) ON CREATE SET r.count = 1 ON MATCH SET r.count = r.count + 1",
                        caller=caller, receiver=receiver
                    )
                    
            elif topic == "transaction.ingested":
                source = data.get("sourceAccount")
                dest = data.get("destinationAccount")
                amount = data.get("amount", 0)
                
                if source and dest:
                    await session.run(
                        "MERGE (a:Entity:BankAccount {id: $source}) MERGE (b:Entity:BankAccount {id: $dest}) MERGE (a)-[r:TRANSACTED_WITH]->(b) ON CREATE SET r.count = 1, r.amountTotalINR = $amount ON MATCH SET r.count = r.count + 1, r.amountTotalINR = r.amountTotalINR + $amount",
                        source=source, dest=dest, amount=amount
                    )
                    
            elif topic == "prediction.completed":
                entity_id = data.get("entityId")
                fraud_score = data.get("fraudScore")
                
                if entity_id and fraud_score is not None:
                    await session.run(
                        "MERGE (e:Entity {id: $entityId}) SET e.fraudScore = $fraudScore",
                        entityId=entity_id, fraudScore=fraud_score
                    )

            elif topic in ["case.updated", "prediction.overridden"]:
                case_id = data.get("caseId")
                status = data.get("status") or data.get("verdictStatus") or data.get("newState") or data.get("newStatus")
                decision = data.get("decision")
                if case_id and (status in ["Action_Taken", "CONFIRMED_FRAUD"] or decision == "APPROVE"):
                    await session.run(
                        "MERGE (c:Entity:Case {id: $caseId}) SET c.status = 'Action_Taken', c.isConfirmed = true",
                        caseId=case_id
                    )

    except Exception as e:
        logger.error(f"Error processing message from topic {msg.topic()}: {e}")

async def consume():
    driver = AsyncGraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    )
    
    conf = {
        'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS,
        'group.id': 'graph-consumer-service',
        'auto.offset.reset': 'earliest'
    }
    
    consumer = Consumer(conf)
    topics = ['case.created', 'case.updated', 'prediction.completed', 'prediction.overridden', 'telecom.event.ingested', 'transaction.ingested']
    consumer.subscribe(topics)
    
    logger.info("Starting Graph Consumer service...")
    
    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None:
                await asyncio.sleep(0.1)
                continue
            if msg.error():
                logger.error(f"Consumer error: {msg.error()}")
                continue
                
            await process_message(driver, msg, None)
            
    finally:
        consumer.close()
        await driver.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(consume())
