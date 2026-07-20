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
    SERVICE_NAME: str = "investigator-bff"           
    SERVICE_VERSION: str = "0.1.0"

    # ── Downstream Services ───────────────────────────────────
    CASE_SERVICE_URL: str = "http://case:8000"
    SEARCH_SERVICE_URL: str = "http://search:8000"
    GEO_SERVICE_URL: str = "http://geo:8000"
    GRAPH_SERVICE_URL: str = "http://graph:8000"
    EVIDENCE_SERVICE_URL: str = "http://evidence:8000"
    REPORTING_SERVICE_URL: str = "http://reporting:8000"
    NOTIFICATION_SERVICE_URL: str = "http://notification:8000"

    # ── Observability ──────────────────────────────────────────
    OTEL_ENDPOINT: str = "http://tempo:4317"
    LOG_LEVEL: str = "INFO"

    # ── JWT (RS256) ───────────────────────────────────────────
    JWT_ALGORITHM: str = "RS256"
    JWT_PUBLIC_KEY: str = ""    

    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

settings = Settings()
