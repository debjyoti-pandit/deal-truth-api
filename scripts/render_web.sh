#!/bin/sh
# Render web start: migrate first (Pre-Deploy is often locked), then serve.
set -eu
cd /app 2>/dev/null || cd "$(dirname "$0")/.."
alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
