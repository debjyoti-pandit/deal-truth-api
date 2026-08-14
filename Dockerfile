FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

COPY pyproject.toml uv.lock README.md ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts
COPY fixtures ./fixtures
COPY docs ./docs
COPY LICENSE CONTRIBUTING.md SECURITY.md THIRD_PARTY_LICENSES.md ./

RUN uv sync --frozen --no-dev --no-editable

EXPOSE 8000 5555

# Migrate then serve so Render works when Pre-Deploy is locked.
CMD ["bash", "scripts/render_web.sh"]
