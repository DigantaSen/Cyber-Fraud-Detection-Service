"""
Audit Service — Configuration

Reads environment variables injected by Docker Compose.
Mirrors the pattern in event-processing/config.py — raw asyncpg DSN,
no SQLAlchemy layer (append-only INSERT path doesn't need an ORM).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    SERVICE_NAME: str = "audit"
    SERVICE_VERSION: str = "0.1.0"
    LOG_LEVEL: str = "INFO"

    # Raw asyncpg DSN — same format as event-processing/outbox_publisher.py
    # docker-compose injects: postgresql://platform_user:...@postgres:5432/platform
    DATABASE_URL: str = "postgresql://platform_user:change_me_postgres@postgres:5432/platform"

    # Kafka
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    KAFKA_GROUP_ID: str = "audit-consumer"


settings = Settings()
