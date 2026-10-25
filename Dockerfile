# Training analytics – one image for the Streamlit UI and the daily `training morning` loop (PLAN phase 8).
# Build: docker compose build   ·   docs/OPERATIONS.md has the token bootstrap and the daily operations.
FROM python:3.12-slim

# tzdata: the morning loop runs at local time (TZ); uv from its official image
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

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
    HOME=/tmp

WORKDIR /app
# dependencies first (cached layer), then the project
COPY pyproject.toml uv.lock CLAUDE.md ./
RUN uv sync --frozen --no-dev --extra ai --no-install-project
COPY . .
RUN uv sync --frozen --no-dev --extra ai && chmod -R a+rX /opt/venv /app
# the compose file runs the containers as the host user (UID/GID), so the bind-mounted token file and data/
# stay owned by that user – a root container would leave ~/.garminconnect unreadable on the host

EXPOSE 8501
CMD ["uv", "run", "--no-sync", "streamlit", "run", "ui-streamlit/app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
