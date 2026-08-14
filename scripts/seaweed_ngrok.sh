#!/usr/bin/env bash
# Start the Docker ngrok-seaweed service (named domain → seaweedfs:8333).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
exec docker compose up -d ngrok-seaweed
