"""
Service Configuration — Pydantic Settings
==========================================
Reads from environment variables (injected by Docker Compose or Vault Agent).
Falls back to .env file for local development.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── Service identity ───────────────────────────────────────
    SERVICE_NAME: str = "notification"
    SERVICE_VERSION: str = "0.1.0"

    # ── Redis ─────────────────────────────────────────────────
    REDIS_URL: str = "redis://:change_me_redis@redis:6379/0"

    # ── Kafka ─────────────────────────────────────────────────
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    
    # ── Webhooks ──────────────────────────────────────────────
    MHA_WEBHOOK_URL: str = "http://mha-webhook-mock:8000/alert"

    # ── Vault ─────────────────────────────────────────────────
    VAULT_ADDR: str = ""
    VAULT_TOKEN: str = ""

    # ── Observability ──────────────────────────────────────────
    OTEL_ENDPOINT: str = "http://tempo:4317"
    LOG_LEVEL: str = "INFO"

    # ── JWT ───────────────
    JWT_ALGORITHM: str = "RS256"
    JWT_PUBLIC_KEY: str = ""


settings = Settings()
