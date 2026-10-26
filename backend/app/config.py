import logging
import os
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("intervai.config")

# Runtime data (SQLite db, uploads, recordings, TTS cache) lives outside the
# application source tree by default. Override with DATA_DIR.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DATA_DIR = os.environ.get("DATA_DIR") or str(_BACKEND_ROOT.parent / ".data" / "backend")

# Secrets that must never be accepted outside local development.
_KNOWN_WEAK_SECRETS = {
    "",
    "intervai-super-secret-jwt-key-2026-production-ready",
    "intervai-local-development-secret-key-32chars-min",
    "dev-insecure-change-me",
    "changeme",
    "secret",
}
_MIN_SECRET_LEN = 32


class ConfigError(RuntimeError):
    """Raised when the configuration is unsafe for the selected ENV."""


class Settings(BaseSettings):
    # Environment & Server
    ENV: str = "development"  # "development", "staging", "production"
    DEBUG: bool = False
    DATA_DIR: str = _DEFAULT_DATA_DIR
    # Only trust X-Forwarded-For / X-Forwarded-Proto when running behind a known proxy.
    TRUST_PROXY_HEADERS: bool = False
    PUBLIC_API_URL: str = ""   # e.g. "https://api.intervai.com" (used when behind reverse proxy)

    # Database & Cache
    DATABASE_URL: str = ""  # empty -> sqlite file inside DATA_DIR
    REDIS_URL: str = "redis://localhost:6379/0"

    # Authentication & Security
    # No usable default: development gets an ephemeral random key (tokens die on restart),
    # production refuses to start without a strong key.
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    EMAIL_VERIFICATION_REQUIRED: bool = False
    DEV_MODE: bool = False
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
    TURNSTILE_SECRET_KEY: str = ""  # Cloudflare Turnstile secret key (required when ENV=production)
    # Shared secret for the /session/maintenance/* endpoints (header X-Maintenance-Token).
    MAINTENANCE_TOKEN: str = ""
    WS_SERVER_PING_SECONDS: float = 15.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def is_production(self) -> bool:
        return self.ENV.lower() == "production"

    @property
    def database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return f"sqlite:///{Path(self.DATA_DIR) / 'intervai.db'}"

    def data_path(self, *parts: str) -> str:
        p = Path(self.DATA_DIR).joinpath(*parts)
        p.mkdir(parents=True, exist_ok=True)
        return str(p)

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


def validate_settings(s: "Settings") -> None:
    """Fail closed in production; make insecure dev defaults loud elsewhere."""
    problems: List[str] = []
    if s.is_production:
        if s.JWT_SECRET_KEY in _KNOWN_WEAK_SECRETS or len(s.JWT_SECRET_KEY) < _MIN_SECRET_LEN:
            problems.append(f"JWT_SECRET_KEY must be set to a random value of at least {_MIN_SECRET_LEN} chars")
        if s.DEBUG or s.DEV_MODE:
            problems.append("DEBUG and DEV_MODE must be false in production")
        if s.LLM_PROVIDER.lower() == "mock" or not s.LLM_API_KEY and s.LLM_PROVIDER.lower() != "ollama":
            problems.append("LLM_PROVIDER must be a real provider with LLM_API_KEY in production (mock is dev/test only)")
        if s.STT_PROVIDER.lower() == "mock":
            problems.append("STT_PROVIDER must be a real provider in production (mock is dev/test only)")
        if not s.TURNSTILE_SECRET_KEY:
            problems.append("TURNSTILE_SECRET_KEY is required in production (guest mode abuse protection)")
        if problems:
            raise ConfigError("Refusing to start with unsafe production config: " + "; ".join(problems))
        return

    if not s.JWT_SECRET_KEY:
        import secrets as _secrets
        s.JWT_SECRET_KEY = _secrets.token_urlsafe(48)
        logger.warning("JWT_SECRET_KEY is not set: using an ephemeral random key (all tokens are invalidated on restart).")
    if s.LLM_PROVIDER.lower() == "mock":
        logger.warning("*** LLM_PROVIDER=mock: question generation/evaluation use canned heuristics, NOT a real model. ***")
    if s.STT_PROVIDER.lower() == "mock":
        logger.warning("*** STT_PROVIDER=mock: speech is NOT transcribed; only client-sent text is used. ***")


settings = Settings()
validate_settings(settings)
