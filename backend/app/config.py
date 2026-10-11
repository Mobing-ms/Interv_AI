from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    # Environment & Server
    ENV: str = "development"  # "development", "staging", "production"
    DEBUG: bool = True
    PUBLIC_API_URL: str = ""   # e.g. "https://api.intervai.com" (used when behind reverse proxy)

    # Database & Cache
    DATABASE_URL: str = "sqlite:///./intervai.db"
    REDIS_URL: str = "redis://localhost:6379/0"

    # Authentication & Security
    JWT_SECRET_KEY: str = "intervai-super-secret-jwt-key-2026-production-ready"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    EMAIL_VERIFICATION_REQUIRED: bool = False
    DEV_MODE: bool = True
    GOOGLE_CLIENT_ID: str = ""
    CORS_ORIGINS: str = "http://localhost:5174,http://localhost:5173,http://127.0.0.1:5174,http://127.0.0.1:5173"

    # Storage Backend Configuration (Local Disk or Cloud Object Storage S3 / Cloudflare R2 / MinIO)
    STORAGE_BACKEND: str = "local"  # "local" or "s3"
    S3_ENDPOINT_URL: str = ""       # e.g. "https://<account_id>.r2.cloudflarestorage.com" for R2
    S3_ACCESS_KEY_ID: str = ""
    S3_SECRET_ACCESS_KEY: str = ""
    S3_BUCKET_NAME: str = "intervai-recordings"
    S3_REGION_NAME: str = "auto"
    S3_PUBLIC_URL_PREFIX: str = ""  # Optional CDN prefix
    RECORDING_RETENTION_DAYS: int = 30

    # Speech-to-Text (STT) Provider
    # Recommended for free-tier deployments: "groq" (fast, free tier, zero RAM usage)
    STT_PROVIDER: str = "mock"       # "mock", "groq", "openai", "deepgram", "local_whisper"
    STT_API_KEY: str = ""
    STT_MODEL: str = "whisper-large-v3-turbo"
    STT_BASE_URL: str = ""

    # LLM Service Configuration
    LLM_PROVIDER: str = "mock"       # "mock", "openai", "gemini", "groq", etc.
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = ""
    LLM_TIMEOUT_SECONDS: float = 30.0
    LLM_MAX_RETRIES: int = 2

    # Session Orchestrator & Timing Configuration
    HEARTBEAT_TIMEOUT_SECONDS: float = 30.0
    ORCHESTRATOR_WARMUP_TIME_SECONDS: int = 60
    ORCHESTRATOR_QUESTION_TIME_SECONDS: int = 120
    ORCHESTRATOR_PRESSURE_QUESTION_TIME_SECONDS: int = 60

    # Guest Practice Mode Configuration
    GUEST_MAX_SESSIONS_PER_IP_PER_DAY: int = 3
    GUEST_MAX_QUESTIONS: int = 3
    GUEST_DURATION_MINUTES: int = 10
    GUEST_MAX_STT_SECONDS: int = 600
    GUEST_MAX_LLM_TOKENS: int = 4000
    GUEST_MAX_UPLOAD_SIZE_BYTES: int = 2 * 1024 * 1024  # 2MB CV upload cap for guests
    GUEST_RETENTION_HOURS: int = 24
    TURNSTILE_SECRET_KEY: str = ""  # Cloudflare Turnstile secret key

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


settings = Settings()
