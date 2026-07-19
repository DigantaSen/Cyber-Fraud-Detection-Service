"""
Service Configuration — Pydantic Settings
==========================================
Reads from environment variables (injected by Docker Compose or Vault Agent).
Falls back to .env file for local development.
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    # ── Service identity ───────────────────────────────────────
    SERVICE_NAME: str = "auth-service"           # Override in each service
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

    # Auth-specific
    JWT_PRIVATE_KEY: str = ""       # RS256 private key — from env
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    MFA_TOTP_ISSUER: str = "CyberFraudShield"
    ALLOWED_ORIGINS: str = "http://localhost:5173,http://localhost:5174,http://localhost:5175"


settings = Settings()
