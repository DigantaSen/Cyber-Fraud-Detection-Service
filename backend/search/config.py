"""
Search Service — Configuration
Reads environment variables (Docker Compose injects these).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    SERVICE_NAME: str = "search"
    SERVICE_VERSION: str = "0.1.0"
    LOG_LEVEL: str = "INFO"

    # OpenSearch (already running at platform-opensearch:9200)
    OPENSEARCH_URL: str = "http://opensearch:9200"

    # Kafka
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    KAFKA_GROUP_ID: str = "search-indexer"


settings = Settings()
