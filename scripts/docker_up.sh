#!/usr/bin/env bash
# Bring up the full Deal Truth stack in Docker (env, Postgres, Redis, SeaweedFS, migrate, API, worker).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required to create .env (stdlib only; no packages)" >&2
  exit 1
fi

python3 scripts/bootstrap_env.py

echo "Checking endpoints before starting Docker..."
if [ -x "${ROOT}/.venv/bin/python" ]; then
  "${ROOT}/.venv/bin/python" scripts/check_endpoints.py --in-process
elif command -v uv >/dev/null 2>&1; then
  uv run python scripts/check_endpoints.py --in-process
else
  echo "skip in-process check (need .venv or uv)" >&2
fi

docker compose up --build -d --wait --remove-orphans --force-recreate

echo ""
echo "Deal Truth is up."
echo "  API:     http://localhost:8000"
echo "  Docs:    http://localhost:8000/docs"
echo "  Health:  curl http://localhost:8000/health/live"
echo "  Ngrok:   http://localhost:4040"

TUNNEL="$(python3 scripts/print_ngrok_url.py http://127.0.0.1:4040 30 || true)"
if [ -n "${TUNNEL}" ]; then
  echo "  Public:  ${TUNNEL}"
  echo "  Webhook: ${TUNNEL}/api/v1/webhooks/pyai/transcription"
  python3 scripts/persist_ngrok_domain.py "${TUNNEL}" || true
else
  echo "  Public:  (ngrok inspector not ready — if NGROK_DOMAIN is set, use https://\$NGROK_DOMAIN)"
  echo "  Domain:  NGROK_DOMAIN in .env, token from https://dashboard.ngrok.com/get-started/your-authtoken"
fi
echo "Stop with: make down"

echo ""
echo "Checking live endpoints..."
if [ -x "${ROOT}/.venv/bin/python" ]; then
  "${ROOT}/.venv/bin/python" scripts/check_endpoints.py --base-url http://localhost:8000 --wait 60
else
  python3 scripts/check_endpoints.py --base-url http://localhost:8000 --wait 60
fi
