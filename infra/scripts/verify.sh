#!/usr/bin/env bash
# Smoke-check schema, seed rows, audit chain, and Redis keys.
set -euo pipefail

DATABASE_URL="${DATABASE_URL:-postgresql://timegrocer:timegrocer@127.0.0.1:5432/timegrocer}"
REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/0}"

echo "→ verify postgres"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 <<'SQL'
\pset tuples_only on
SELECT 'users=' || count(*) FROM users;
SELECT 'whitelist_merchants=' || count(*) FROM merchants WHERE list_status = 'whitelist';
SELECT 'blacklist_merchants=' || count(*) FROM merchants WHERE list_status = 'blacklist';
SELECT 'products=' || count(*) FROM products;
SELECT 'banned_categories=' || count(*) FROM category_rules WHERE user_id IS NULL AND is_banned;
SELECT 'demo_order=' || public_order_id FROM orders WHERE public_order_id = 'ORD-DEMO01';
SELECT 'audit_entries=' || count(*) FROM audit_log
  WHERE chain_id = '00000000-0000-0000-0000-000000000001';
SELECT CASE
  WHEN EXISTS (SELECT 1 FROM audit_verify_chain('00000000-0000-0000-0000-000000000001'))
  THEN 'audit_chain=BROKEN'
  ELSE 'audit_chain=OK'
END;
SELECT 'guest_catalog_skus=' || string_agg(sku, ',' ORDER BY sku)
FROM products WHERE is_active;
SQL

if command -v redis-cli >/dev/null 2>&1; then
  HOST_PORT_DB="${REDIS_URL#redis://}"
  HOST_PORT="${HOST_PORT_DB%%/*}"
  DB="${HOST_PORT_DB##*/}"
  HOST="${HOST_PORT%%:*}"
  PORT="${HOST_PORT##*:}"
  [[ "$HOST" == "$PORT" ]] && PORT=6379
  [[ "$DB" == "$HOST_PORT_DB" || -z "$DB" ]] && DB=0

  echo "→ verify redis"
  TTL="$(redis-cli -h "$HOST" -p "$PORT" -n "$DB" TTL escalation:esc_demo)"
  IDEM="$(redis-cli -h "$HOST" -p "$PORT" -n "$DB" EXISTS idempotency:SKU001:1:PASS:none)"
  echo "escalation_ttl=$TTL"
  echo "idempotency_exists=$IDEM"
  if [[ "$TTL" -lt 1 ]]; then
    echo "✗ escalation key missing or expired" >&2
    exit 1
  fi
  if [[ "$IDEM" != "1" ]]; then
    echo "✗ idempotency key missing" >&2
    exit 1
  fi
else
  echo "⚠ redis-cli not found; skip Redis verify"
fi

echo "✓ infra verify passed"
