# Multi-stage / optimized production Dockerfile for IntervAI Backend
FROM python:3.11-slim as base

# Prevent Python from buffering stdout/stderr and writing bytecode
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install system runtime dependencies:
# - curl: for healthcheck probe
# - ffmpeg: for audio transcoding and slicing
# - libpq-dev & gcc: for PostgreSQL connection driver
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Ensure storage directories exist
RUN mkdir -p storage/sessions storage/cv_uploads

# Health check probe against /health
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

# Start script running migrations then launching uvicorn
CMD ["sh", "-c", "python run_migrations.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
