from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # App Settings
    APP_NAME: str = "Azure-SLA-Guardian"
    APP_ENV: str = "development"
    DEBUG: bool = True
    PORT: int = 8000
    HOST: str = "0.0.0.0"

    # Cloud Operation Mode: 'simulator' or 'azure'
    CLOUD_MODE: str = Field(default="simulator", description="Operation mode: 'simulator' or 'azure'")

    # Azure Cloud Credentials (used when CLOUD_MODE == 'azure')
    AZURE_SUBSCRIPTION_ID: Optional[str] = None
    AZURE_TENANT_ID: Optional[str] = None
    AZURE_CLIENT_ID: Optional[str] = None
    AZURE_CLIENT_SECRET: Optional[str] = None
    AZURE_RESOURCE_GROUP: str = "rg-guardian-production"

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./guardian.db"

    # Rate Limiting & Backoff
    RATE_LIMIT_TOKENS_PER_SEC: float = 10.0
    RATE_LIMIT_BUCKET_CAPACITY: int = 25
    MAX_RETRIES: int = 5
    BACKOFF_BASE_SECONDS: float = 0.5
    BACKOFF_MAX_SECONDS: float = 10.0
    BACKOFF_JITTER: bool = True

    # Anomaly / Ransomware Thresholds
    ENTROPY_THRESHOLD: float = 7.2  # Max Shannon entropy is 8.0. Normal data is ~3.5 - 6.0. Encrypted is > 7.2
    SIZE_DELTA_THRESHOLD_PERCENT: float = 50.0  # Alert if data modification spikes >50% between snapshots

    # Scheduler Settings
    SCHEDULER_ENABLED: bool = True
    SLA_EVALUATION_INTERVAL_SECONDS: int = 15
    RETENTION_SWEEPER_INTERVAL_SECONDS: int = 30

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
