"""
Event Processing Configuration
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    SERVICE_NAME: str = "event-processing"
    SERVICE_VERSION: str = "0.1.0"
    LOG_LEVEL: str = "INFO"

    DATABASE_URL: str = "postgresql+asyncpg://platform_user:change_me_postgres@postgres:5432/platform"
    # Used by asyncpg directly (not SQLAlchemy) in outbox publisher
    DSN: str = "postgresql://platform_user:change_me_postgres@postgres:5432/platform"

    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    
    # Webhook HMAC secrets
    TELECOM_WEBHOOK_SECRET: str = "change_me_telecom"
    BANK_WEBHOOK_SECRET: str = "change_me_bank"
    COUNTERFEIT_WEBHOOK_SECRET: str = "change_me_counterfeit"
    
settings = Settings()
