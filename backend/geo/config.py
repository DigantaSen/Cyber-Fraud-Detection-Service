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
    SERVICE_NAME: str = "geo"
    SERVICE_VERSION: str = "0.1.0"

    # ── PostgreSQL (via PgBouncer) ─────────────────────────────
    DATABASE_URL: str = "postgresql://geo_user:change_me_postgis@postgis:5432/geospatial"

    # ── Redis ─────────────────────────────────────────────────
    REDIS_URL: str = "redis://:change_me_redis@redis:6379/0"

    # ── Kafka ─────────────────────────────────────────────────
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    KAFKA_GROUP_ID: str = "geo-service-consumer"

    # ── MinIO ─────────────────────────────────────────────────
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "change_me_minio"

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
