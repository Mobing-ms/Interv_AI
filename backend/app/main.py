from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

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
    description="Authentication and API services for IntervAI",
    lifespan=lifespan,
)

import re
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response, JSONResponse

# =============================================================================
# PII REDACTION LOGGING FILTER
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

# Apply filter to root logger
root_logger = logging.getLogger()
root_logger.addFilter(PIIRedactionFilter())


# =============================================================================
# SECURITY HEADERS & REQUEST SIZE MIDDLEWARE
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
                        status_code=413,
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
            "img-src 'self' data: blob:; media-src 'self' data: blob:;"
        )
        return response


# SlowAPI rate limiting setup
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS setup
origins = settings.cors_origins_list
if "http://localhost:5174" not in origins:
    origins.append("http://localhost:5174")
if "http://localhost:5173" not in origins:
    origins.append("http://localhost:5173")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(SecurityHardeningMiddleware)

# Routers
app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(cv_router)
app.include_router(interview_router)
app.include_router(session_router)
app.include_router(report_router)
app.include_router(guest_router)


@app.get("/")
def root():
    return {"message": "IntervAI API is running", "version": "1.0.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
