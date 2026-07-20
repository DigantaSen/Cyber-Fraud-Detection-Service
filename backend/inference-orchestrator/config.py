"""
Inference Orchestrator — Configuration
Reads from environment variables injected by Docker Compose.
Falls back to .env for local development.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── Service identity ────────────────────────────────────────
    SERVICE_NAME: str = "inference-orchestrator"
    SERVICE_VERSION: str = "0.1.0"
    LOG_LEVEL: str = "INFO"

    # ── PostgreSQL ──────────────────────────────────────────────
    # Plain asyncpg DSN (no +asyncpg prefix — asyncpg uses it directly)
    DATABASE_URL: str = "postgresql://platform_user:change_me_postgres@postgres:5432/platform"

    # ── Redis ───────────────────────────────────────────────────
    REDIS_URL: str = "redis://redis:6379/0"

    # ── Kafka ───────────────────────────────────────────────────
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    KAFKA_GROUP_ID: str = "orch-consumer"
    TOPIC_CASE_CREATED: str = "case.created"
    TOPIC_EVIDENCE_UPLOADED: str = "evidence.uploaded"
    TOPIC_PREDICTION_COMPLETED: str = "prediction.completed"
    TOPIC_PREDICTION_FAILED: str = "prediction.failed"

    # ── Internal service URLs (no Kong, no JWT) ─────────────────
    GRAPH_SERVICE_URL: str = "http://graph:8000"
    ML_SCAM_NLP_URL: str = "http://ml-scam-nlp:8000"
    ML_COUNTERFEIT_URL: str = "http://ml-counterfeit-cv:8000"
    ML_GRAPH_URL: str = "http://ml-graph-analyzer:8000"
    ML_AUDIO_URL: str = "http://ml-audio-analyzer:8000"


settings = Settings()
