# Infra — Database & Cache (Person 2)

Postgres + Redis backing the shopping agent: guest catalog browse, logged-in mandates, policy rules (R1–R4), hash-chained audit ledger, escalation TTL, and idempotent payments.

Aligned with:

- `agent-brain/cross_team_config.json`
- `frontend/contract.json`
- `mockup-mall/mock-api/data/*`

Policy API code lives in `backend-policy` (port 8001). This folder is **data plane only**.

## Quick start

```bash
# From repo root
cp .env.example .env
cd infra
docker compose up -d

# Apply schema + seed (also auto-runs via docker entrypoint on first boot)
./scripts/migrate.sh
./scripts/seed.sh
./scripts/verify.sh
```

Local services (no Docker):

```bash
# Postgres + Redis must be running locally
export DATABASE_URL=postgresql://timegrocer:timegrocer@127.0.0.1:5432/timegrocer
export REDIS_URL=redis://127.0.0.1:6379/0
./scripts/migrate.sh
./scripts/seed.sh
./scripts/verify.sh
```

## Layout

```
infra/
  docker-compose.yml
  postgres/
    init/001_schema.sql      # tables, indexes, constraints
    seed/001_demo_seed.sql   # merchants, products, mother user, rules
  redis/
    keyspace.md              # escalation TTL + idempotency keys
  scripts/
    migrate.sh
    seed.sh
    verify.sh
  schema.md                  # entity map → FR / demo scenarios
```

## Defaults (from cross-team config)

| Setting | Value |
|---|---|
| Per-transaction auto cap | HK$500 |
| Bulk approval ceiling | HK$800 |
| Monthly cap | HK$2,000 |
| Escalation TTL | 600s (Redis) |
| Free shipping threshold | HK$400 (shipping HK$30 below) |
| Whitelist | Watsons, HKTVmall, PARKnSHOP, Japan Home Centre |
| Blacklist merchants | DarkWebMart |
| Blacklist categories (seed) | Food, Alcohol, Electronics, Health |

Guest users can read `products` / `merchants`. Agent checkout, ledger writes, escalations, and payments require an authenticated `users` row.
