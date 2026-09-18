# Cloud Run expects a container that listens on $PORT and can scale to zero.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir ".[adk,gcp,documents]"

# Agents live alongside the harness in the deploying project.
COPY examples/ ./examples/

ENV PORT=8080 \
    HARNESS_PROVIDER=google \
    HARNESS_STORAGE=gcp

EXPOSE 8080

# One worker, because Cloud Run scales by instance rather than by process.
CMD exec uvicorn nonprofit_harness.main:app --host 0.0.0.0 --port ${PORT} --workers 1
