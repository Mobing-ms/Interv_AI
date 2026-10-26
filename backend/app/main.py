import re
import json
import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response, JSONResponse

from app.config import settings
from app.database import engine, Base
import app.models  # Register all models
from app.routers.auth import router as auth_router, limiter
from app.routers.profile import router as profile_router
from app.routers.cv import router as cv_router
from app.routers.interview import router as interview_router
from app.routers.session import router as session_router
from app.routers.report import router as report_router
from app.routers.guest import router as guest_router


# =============================================================================
# 1. STRUCTURED LOGGING & PII REDACTION
# =============================================================================

class PIIRedactionFilter(logging.Filter):
    """
    Strips Sensitive Personally Identifiable Information (PII) from all logger outputs:
    - Email addresses
    - Phone numbers
    - Bearer and access tokens
    - Raw passwords in payloads
    """
    EMAIL_REGEX = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b')
    PHONE_REGEX = re.compile(r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}')
    TOKEN_REGEX = re.compile(r'(Bearer\s+|token=)[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.?[A-Za-z0-9-_.+/=]*')
    PASSWORD_REGEX = re.compile(r'("password"\s*:\s*)"[^"]+"', re.IGNORECASE)

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            msg = record.msg
            msg = self.EMAIL_REGEX.sub("[EMAIL_REDACTED]", msg)
            msg = self.PHONE_REGEX.sub("[PHONE_REDACTED]", msg)
            msg = self.TOKEN_REGEX.sub(r"\1[TOKEN_REDACTED]", msg)
            msg = self.PASSWORD_REGEX.sub(r'\1"[REDACTED]"', msg)
            record.msg = msg
        return True


class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as structured single-line JSON in production."""
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


# Configure logging
root_logger = logging.getLogger()
root_logger.addFilter(PIIRedactionFilter())

if settings.ENV == "production" and not root_logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredJsonFormatter())
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)


# =============================================================================
# 2. LIFESPAN & DATABASE STARTUP
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure tables are created
    Base.metadata.create_all(bind=engine)
    # Ensure schema migrations for existing SQLite databases
    with engine.connect() as conn:
        for col_query in [
            "ALTER TABLE users ADD COLUMN onboarding_status VARCHAR(50) DEFAULT 'not_started'",
            "ALTER TABLE interview_configs ADD COLUMN is_guest BOOLEAN DEFAULT 0",
            "ALTER TABLE interview_sessions ADD COLUMN is_guest BOOLEAN DEFAULT 0",
            "ALTER TABLE interview_sessions ADD COLUMN guest_id VARCHAR(100)",
            "ALTER TABLE user_consents ADD COLUMN is_guest BOOLEAN DEFAULT 0",
            "ALTER TABLE user_consents ADD COLUMN guest_id VARCHAR(100)",
            "ALTER TABLE session_results ADD COLUMN is_guest BOOLEAN DEFAULT 0",
            "ALTER TABLE session_reports ADD COLUMN is_guest BOOLEAN DEFAULT 0",
            "ALTER TABLE cv_documents ADD COLUMN is_guest BOOLEAN DEFAULT 0",
        ]:
            try:
                conn.execute(text(col_query))
                conn.commit()
            except Exception:
                pass  # column already exists or table freshly created
    yield


app = FastAPI(
    title="IntervAI Backend API",
    version="1.0.0",
    description="Enterprise-grade Multimodal AI Interview Platform",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG or settings.ENV != "production" else None,
    redoc_url="/redoc" if settings.DEBUG or settings.ENV != "production" else None,
)


# =============================================================================
# 3. SECURITY HEADERS & REQUEST SIZE MIDDLEWARE
# =============================================================================

class SecurityHardeningMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # 1. Enforce max request content length (25MB for CV uploads/recordings)
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                length_int = int(content_length)
                max_bytes = 25 * 1024 * 1024  # 25 MB
                if length_int > max_bytes:
                    return JSONResponse(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        content={"detail": "Payload too large. Maximum allowed size is 25MB."},
                    )
            except ValueError:
                pass

        # 2. Process downstream request
        response: Response = await call_next(request)

        # 3. Inject strict security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; frame-ancestors 'none'; "
            "img-src 'self' data: blob: https:; media-src 'self' data: blob: https:;"
        )
        return response


# Rate limiting setup
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# =============================================================================
# 4. PRODUCTION CORS POLICY
# =============================================================================

configured_origins = settings.cors_origins_list

if "*" in configured_origins:
    cors_origins = ["*"]
    allow_credentials = False
else:
    cors_origins = list(configured_origins)
    allow_credentials = True
    if settings.DEV_MODE or settings.ENV != "production":
        for dev_url in [
            "http://localhost:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:5174",
        ]:
            if dev_url not in cors_origins:
                cors_origins.append(dev_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=allow_credentials,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

app.add_middleware(SecurityHardeningMiddleware)


# =============================================================================
# 5. HEALTH CHECKS & PROBES
# =============================================================================

@app.get("/health", tags=["system"])
@app.get("/healthz", tags=["system"])
def health_check():
    """
    Production health check probe for load balancers, Kubernetes, and uptime monitors.
    Returns status 200 when healthy, or 503 if primary components fail.
    """
    health = {
        "status": "healthy",
        "environment": settings.ENV,
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {},
    }

    # 1. Database Check
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        health["checks"]["database"] = {"status": "ok", "dialect": engine.dialect.name}
    except Exception:
        logging.getLogger("intervai.health").exception("Database health check failed")
        health["status"] = "degraded"
        health["checks"]["database"] = {"status": "error"}

    # 2. Cache / State Store Check
    try:
        from app.services.session_state import default_state_store
        client = default_state_store._get_client()
        client_name = type(client).__name__
        is_redis = "Redis" in client_name and "Fake" not in client_name and "Dict" not in client_name
        health["checks"]["cache_state"] = {
            "status": "ok",
            "mode": "redis" if is_redis else "in_memory_fallback",
        }
    except Exception:
        logging.getLogger("intervai.health").exception("State store health check failed")
        health["checks"]["cache_state"] = {"status": "warning"}

    # 3. Storage Backend Check
    try:
        from app.services.storage_service import default_storage_provider, S3StorageProvider
        health["checks"]["storage"] = {
            "status": "ok",
            "backend": "s3" if isinstance(default_storage_provider, S3StorageProvider) else "local",
        }
    except Exception:
        logging.getLogger("intervai.health").exception("Storage health check failed")
        health["checks"]["storage"] = {"status": "warning"}

    # 4. Speech-to-Text Provider Check
    health["checks"]["stt_provider"] = {
        "status": "ok",
        "provider": settings.STT_PROVIDER,
    }

    status_code = status.HTTP_200_OK if health["status"] == "healthy" else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=status_code, content=health)


# =============================================================================
# 6. ROUTER REGISTRATION
# =============================================================================

app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(cv_router)
app.include_router(interview_router)
app.include_router(session_router)
app.include_router(report_router)
app.include_router(guest_router)


@app.get("/")
def root():
    return {
        "app": "IntervAI Backend API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs" if settings.DEBUG or settings.ENV != "production" else "disabled in production",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
