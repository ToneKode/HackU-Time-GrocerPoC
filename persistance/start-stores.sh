#!/usr/bin/env bash
# Bring up Postgres + Redis for the PoC (Docker Compose preferred).
set -euo pipefail
cd "$(dirname "$0")"

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  echo "Starting persistance stores via Docker Compose..."
  docker compose up -d postgres redis
  docker compose up -d --build persistance-api
  echo "Postgres :5432  Redis :6379  API :8003"
  exit 0
fi

echo "Docker not available — checking local Postgres/Redis..."
if command -v redis-cli >/dev/null 2>&1; then
  redis-cli ping >/dev/null 2>&1 || redis-server --daemonize yes --bind 127.0.0.1 --port 6379
  echo "Redis OK"
fi
if command -v pg_isready >/dev/null 2>&1; then
  pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1 || {
    echo "Start Postgres locally (e.g. sudo pg_ctlcluster 16 main start), then:"
    echo "  createuser -s tg; createdb -O tg time_grocer  (password tg)"
    exit 1
  }
  echo "Postgres OK"
fi

cd backend
python3 migrate.py
echo "Schema applied. Start API with: cd persistance/backend && uvicorn main:app --port 8003"
