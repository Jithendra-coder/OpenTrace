# OpenTrace — Hardened Production Container
FROM python:3.12-slim-bookworm

# Set strict production environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OPENTRACE_HOME=/app/data \
    TMPDIR=/tmp

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged application user
RUN useradd -m -u 1000 -s /bin/bash opentrace

WORKDIR /app

# Copy dependency specifications first for layer caching
COPY pyproject.toml /app/

# Install OpenTrace and dependencies
COPY backend /app/backend
COPY frontend /app/frontend
RUN pip install -e ".[dev]"

# Create writable data directories and assign permissions
RUN mkdir -p /app/data /tmp && \
    chown -R opentrace:opentrace /app /tmp

USER opentrace

# Expose default HTTP port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default launch command
CMD ["uvicorn", "opentrace.main:app", "--host", "0.0.0.0", "--port", "8000"]
