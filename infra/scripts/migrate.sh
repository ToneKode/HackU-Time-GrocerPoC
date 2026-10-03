#!/usr/bin/env bash
# Apply Postgres schema. Idempotent only on a fresh DB (CREATE TYPE/TABLE).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATABASE_URL="${DATABASE_URL:-postgresql://timegrocer:timegrocer@127.0.0.1:5432/timegrocer}"

echo "→ migrate: $DATABASE_URL"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$ROOT/postgres/init/001_schema.sql"
echo "✓ schema applied"
