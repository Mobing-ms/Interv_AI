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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure tables are created
    Base.metadata.create_all(bind=engine)
    # Ensure schema migrations for existing SQLite databases
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN onboarding_status VARCHAR(50) DEFAULT 'not_started'"))
            conn.commit()
        except Exception:
            pass  # column already exists
    yield


app = FastAPI(
    title="IntervAI Backend API",
    version="1.0.0",
    description="Authentication and API services for IntervAI",
    lifespan=lifespan,
)

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

# Routers
app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(cv_router)
app.include_router(interview_router)
app.include_router(session_router)
app.include_router(report_router)


@app.get("/")
def root():
    return {"message": "IntervAI API is running", "version": "1.0.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
