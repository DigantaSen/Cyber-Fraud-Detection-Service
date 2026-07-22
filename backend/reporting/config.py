# pyrefly: ignore [missing-import]
from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    SERVICE_NAME: str = "reporting-service"
    SERVICE_VERSION: str = "0.1.0"

    DATABASE_URL: str = "postgresql+asyncpg://platform_user:change_me_postgres@postgres:5432/platform"
    
    MINIO_ENDPOINT: str = "http://minio:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "change_me_minio"
    MINIO_BUCKET_REPORTS: str = "reports"
    
    NEO4J_URI: str = "bolt://neo4j:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "change_me_neo4j"
    
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    
    VAULT_ADDR: str = ""
    VAULT_TOKEN: str = ""

    MOCK_RS256_PRIVATE_KEY: str = ""
    
    OTEL_ENDPOINT: str = "http://tempo:4317"
    ENVIRONMENT: str = "development"

    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'

settings = Settings()
