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
    SERVICE_NAME: str = "platform-service"           # Override in each service
    SERVICE_VERSION: str = "0.1.0"

    # ── PostgreSQL (via PgBouncer) ─────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://platform_user:change_me_postgres@postgres:5432/platform"

    # ── Redis ─────────────────────────────────────────────────
    REDIS_URL: str = "redis://:change_me_redis@redis:6379/0"

    # ── Kafka ─────────────────────────────────────────────────
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    KAFKA_SCHEMA_REGISTRY_URL: str = ""

    # ── Vault ─────────────────────────────────────────────────
    VAULT_ADDR: str = ""
    VAULT_TOKEN: str = ""

    # ── Observability ──────────────────────────────────────────
    # Services send telemetry directly to Tempo in local docker-compose
    OTEL_ENDPOINT: str = "http://tempo:4317"   # gRPC port on Tempo
    LOG_LEVEL: str = "INFO"

    # ── JWT (RS256 — public key for validation) ───────────────
    JWT_ALGORITHM: str = "RS256"
    JWT_PUBLIC_KEY: str = ""    # Loaded from Vault in production

    # ── MinIO ──────────────────────────────────────────────────
    MINIO_ENDPOINT: str = "http://minio:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "change_me_minio"
    MINIO_BUCKET: str = "evidence"

    # ── ClamAV ─────────────────────────────────────────────────
    CLAMAV_HOST: str = "clamav"
    CLAMAV_PORT: int = 3310

settings = Settings()
