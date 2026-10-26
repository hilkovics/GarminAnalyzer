# Training analytics – one image for the app (React + API), the daily `training morning` loop and the optional
# Streamlit UI. Build: docker compose build · docs/SERVER.md (home server) · docs/OPERATIONS.md (operations).
# Multi-arch base images: the same Dockerfile builds on x86-64 and on a Raspberry Pi (arm64).
# uv pinned for reproducible builds (bump together with the uv used for uv.lock)
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.8.17
FROM ${UV_IMAGE} AS uv

FROM python:3.12-slim

# tzdata: the morning loop runs at local time (TZ); uv from its official image
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    TZ=Europe/Bratislava \
    GARMINTOKENS=/tokens \
    TRAINING_DB_PATH=/app/data/training.db \
    TRAINING_LOG_DIR=/app/data/logs \
    TRAINING_REPORTS_DIR=/app/data/reports \
    UV_NO_SYNC=1 \
    UV_CACHE_DIR=/tmp/uv-cache \
    PATH=/opt/venv/bin:$PATH \
    HOME=/tmp

WORKDIR /app
# dependencies first (cached layer), then the project
COPY pyproject.toml uv.lock CLAUDE.md ./
RUN uv sync --frozen --no-dev --extra ai --no-install-project && rm -rf /tmp/uv-cache
COPY . .
RUN uv sync --frozen --no-dev --extra ai && rm -rf /tmp/uv-cache && chmod -R a+rX /opt/venv /app
# the compose file runs the containers as the host user (UID/GID), so the bind-mounted token file and data/
# stay owned by that user – a root container would leave ~/.garminconnect unreadable on the host.
# The commands run from /opt/venv/bin directly (no `uv run` at runtime: the build's uv cache belongs to root).

# frontend/dist is committed, so no Node.js build stage is needed
EXPOSE 8000
CMD ["training", "api", "--host", "0.0.0.0", "--port", "8000"]
