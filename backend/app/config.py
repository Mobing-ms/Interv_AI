from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./intervai.db"
    JWT_SECRET_KEY: str = "intervai-super-secret-jwt-key-2026-production-ready"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    EMAIL_VERIFICATION_REQUIRED: bool = False
    DEV_MODE: bool = True
    GOOGLE_CLIENT_ID: str = ""
    CORS_ORIGINS: str = "http://localhost:5174,http://localhost:5173,http://127.0.0.1:5174,http://127.0.0.1:5173"
    RECORDING_RETENTION_DAYS: int = 30
    
    # LLM Service Configuration
    LLM_PROVIDER: str = "mock"  # "mock", "openai", "gemini", etc.
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = ""
    LLM_TIMEOUT_SECONDS: float = 30.0
    LLM_MAX_RETRIES: int = 2

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


settings = Settings()
