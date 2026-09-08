# ---------------------------------------------------------------------------
# Operon — single-container image (FastAPI + pre-built React dashboard).
# No Node needed at build time: the React bundle is committed under frontend/dist.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS base

# uv for fast, reproducible installs (from the official uv image).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# 1) Install dependencies from the lockfile (cached unless deps change).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 2) Copy the app.
COPY . .

# 3) Pre-train + cache the health model so container start is fast.
RUN python -m core.model

# The public demo defaults to the deterministic agent (no AWS credentials, no
# cost). Provide AWS creds + unset this to run the live Bedrock agent.
ENV POC_FORCE_DETERMINISTIC=1 \
    POC_HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000

# Honour $PORT (Render/Railway/Fly inject it); default 8000 locally.
CMD ["sh", "-c", "uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-8000} --log-level warning"]
