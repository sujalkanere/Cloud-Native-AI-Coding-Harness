# Stage 1: Base runtime with Python 3.12, git, and non-root user
FROM python:3.12-slim-bookworm AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/app/.venv/bin:$PATH"

# Install git (required by backend) and build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -g 1000 appuser && useradd -u 1000 -g appuser -s /bin/bash -m appuser

WORKDIR /app

# Stage 2: Dependency Builder
FROM base AS builder

RUN python -m venv /app/.venv

# Copy package manifests if present
COPY pyproject.toml* requirements.txt* ./

# Install python dependencies with fallback for initial scaffolding
RUN if [ -f pyproject.toml ]; then \
        /app/.venv/bin/pip install --upgrade pip && /app/.venv/bin/pip install . ; \
    elif [ -f requirements.txt ]; then \
        /app/.venv/bin/pip install --upgrade pip && /app/.venv/bin/pip install -r requirements.txt ; \
    else \
        /app/.venv/bin/pip install --upgrade pip && /app/.venv/bin/pip install \
            "fastapi>=0.110.0" \
            "uvicorn[standard]>=0.28.0" \
            "pydantic>=2.6.0" \
            "pydantic-settings>=2.2.0" \
            "sqlalchemy[asyncio]>=2.0.28" \
            "asyncpg>=0.29.0" \
            "alembic>=1.13.1" \
            "docker>=7.0.0" \
            "boto3>=1.34.0" \
            "httpx>=0.27.0" \
            "python-jose[cryptography]>=3.3.0" ; \
    fi

# Stage 3: Production Target (prod)
# Strictly excludes test_support and tests
FROM base AS prod

COPY --from=builder /app/.venv /app/.venv

# Copy backend application code and migration files
COPY alembic.ini* ./
COPY alembic/ ./alembic/
COPY app/ ./app/

# Symlink /app to /app/backend so absolute 'from backend...' imports resolve in containers
RUN ln -s /app /app/backend

# Set ownership
RUN chown -R 1000:1000 /app

USER 1000:1000
EXPOSE 8000

# Run Alembic migrations and start FastAPI server
CMD ["sh", "-c", "alembic upgrade head 2>/dev/null || true; uvicorn app.api.main:app --host 0.0.0.0 --port 8000"]

# Stage 4: Test Target (test)
# Extends prod and includes test_support and tests
FROM prod AS test

USER root

# Install test dependencies
RUN /app/.venv/bin/pip install \
    "pytest>=8.0.0" \
    "pytest-asyncio>=0.23.0" \
    "ruff>=0.3.0"

# Copy test support and test suites
COPY test_support/ ./test_support/
COPY tests/ ./tests/

RUN ln -s /app /app/backend 2>/dev/null || true

RUN chown -R 1000:1000 /app

USER 1000:1000

CMD ["sh", "-c", "alembic upgrade head 2>/dev/null || true; uvicorn app.api.main:app --host 0.0.0.0 --port 8000"]
