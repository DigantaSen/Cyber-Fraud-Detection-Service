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
    SERVICE_NAME: str = "graph"
    SERVICE_VERSION: str = "0.1.0"

    # ── Neo4j ─────────────────────────────
    NEO4J_URI: str = "bolt://neo4j:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "change_me_neo4j"

    # ── Kafka ─────────────────────────────────────────────────
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    KAFKA_GROUP_ID: str = "graph-service-consumer"

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
