#!/usr/bin/env bash
# Load demo seed (mother user, catalog, happy-path order, audit chain).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATABASE_URL="${DATABASE_URL:-postgresql://timegrocer:timegrocer@127.0.0.1:5432/timegrocer}"
REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/0}"

echo "→ seed postgres: $DATABASE_URL"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$ROOT/postgres/seed/001_demo_seed.sql"
echo "✓ postgres seeded"

if command -v redis-cli >/dev/null 2>&1; then
  # Parse redis://host:port/db lightly
  HOST_PORT_DB="${REDIS_URL#redis://}"
  HOST_PORT="${HOST_PORT_DB%%/*}"
  DB="${HOST_PORT_DB##*/}"
  HOST="${HOST_PORT%%:*}"
  PORT="${HOST_PORT##*:}"
  [[ "$HOST" == "$PORT" ]] && PORT=6379
  [[ "$DB" == "$HOST_PORT_DB" || -z "$DB" ]] && DB=0

  echo "→ seed redis escalation TTL key (600s)"
  redis-cli -h "$HOST" -p "$PORT" -n "$DB" SET escalation:esc_demo \
    '{"escalation_id":"esc_demo","status":"PENDING","amount":799.0,"currency":"HKD","merchant":"PARKnSHOP","sku":"SKU003","reason":"Over HK$500 per-transaction cap"}' \
    EX 600 >/dev/null
  redis-cli -h "$HOST" -p "$PORT" -n "$DB" SET idempotency:SKU001:1:PASS:none \
    '{"success":true,"order_id":"ORD-DEMO01","charged":119.9,"payment_route":"mastercard"}' \
    EX 86400 >/dev/null
  echo "✓ redis seeded"
else
  echo "⚠ redis-cli not found; skip Redis seed (see infra/redis/keyspace.md)"
fi
