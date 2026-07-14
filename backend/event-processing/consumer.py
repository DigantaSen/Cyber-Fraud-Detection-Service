import json
import logging
import time
from typing import Callable, Any
from kafka import KafkaConsumer, KafkaProducer
from prometheus_client import Counter

logger = logging.getLogger("kafka-consumer")

# Expose a Prometheus counter for the DLQ depth
# Note: In a real environment, each service consuming this library would
# expose these metrics on their /metrics endpoint.
dlq_depth_counter = Counter(
    "kafka_dlq_depth",
    "Number of messages routed to the Dead Letter Queue",
    ["topic"]
)

class RetryableKafkaConsumer:
    """
    A Kafka consumer wrapper that provides 3-retry logic with exponential backoff.
    If a message fails after 3 retries, it is routed to the corresponding DLQ topic.
    """
    
    def __init__(self, bootstrap_servers: str, group_id: str, topics: list[str]):
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self.topics = topics
        self.running = False
        
        self.consumer = KafkaConsumer(
            *self.topics,
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.group_id,
            enable_auto_commit=False, # We commit manually after processing
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            auto_offset_reset="earliest"
        )
        
        self.dlq_producer = KafkaProducer(
            bootstrap_servers=self.bootstrap_servers,
            client_id=f"{self.group_id}-dlq-producer",
            value_serializer=lambda v: json.dumps(v).encode("utf-8")
        )
        
        # Backoff intervals in seconds (1s, 5s, 30s)
        self.retry_intervals = [1, 5, 30]

    def _route_to_dlq(self, msg):
        """Send the failed message to the DLQ topic."""
        dlq_topic = f"{msg.topic}.DLQ"
        try:
            logger.warning(f"Routing message to DLQ: {dlq_topic}")
            # Use raw message value as dict, since we already deserialized it
            self.dlq_producer.send(dlq_topic, key=msg.key, value=msg.value)
            self.dlq_producer.flush()
            # Increment Prometheus counter
            dlq_depth_counter.labels(topic=msg.topic).inc()
        except Exception as e:
            logger.error(f"FATAL: Could not route message to DLQ: {e}")

    def start_consuming(self, message_handler: Callable[[Any], None]):
        """
        Starts consuming messages.
        The message_handler should be a function that takes a Kafka message value.
        It should raise an exception if processing fails.
        """
        self.running = True
        logger.info(f"Started consuming topics: {self.topics}")
        
        try:
            for msg in self.consumer:
                if not self.running:
                    break
                    
                success = False
                attempts = 0
                max_attempts = len(self.retry_intervals) + 1
                
                while attempts < max_attempts and not success:
                    try:
                        logger.debug(f"Processing message from {msg.topic}, attempt {attempts + 1}")
                        # Call the user-provided handler
                        message_handler(msg.value)
                        success = True
                    except Exception as e:
                        attempts += 1
                        logger.error(f"Error processing message from {msg.topic}: {e}")
                        
                        if attempts < max_attempts:
                            backoff = self.retry_intervals[attempts - 1]
                            logger.info(f"Retrying in {backoff} seconds...")
                            time.sleep(backoff)
                            
                if not success:
                    logger.error(f"Message failed after {max_attempts} attempts. Routing to DLQ.")
                    self._route_to_dlq(msg)
                    
                # Commit offset after processing (whether success or routed to DLQ)
                self.consumer.commit()
                
        except KeyboardInterrupt:
            logger.info("Consumer stopped via KeyboardInterrupt.")
        finally:
            self.stop()

    def stop(self):
        self.running = False
        if self.consumer:
            self.consumer.close()
        if self.dlq_producer:
            self.dlq_producer.close()
