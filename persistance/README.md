# persistance — durable stores for HacKU Time-Grocer · port 8003

Postgres holds the hash-chained audit ledger and monthly spend.
Redis is the escalation TTL clock (default 600 s).

Contract shapes match `agent-brain/cross_team_config.json` and
`backend-policy` (Person 2). Policy can keep serving `/check_policy` on 8001
while pointing `DATABASE_URL` / `REDIS_URL` at these same stores, or call this
API for ledger / spend / escalation state.

## Bring up the stores

```bash
cd persistance
cp .env.example .env
docker compose up -d          # postgres:5432, redis:6379, api:8003
```

Without Docker, point `DATABASE_URL` / `REDIS_URL` at local Postgres 16 + Redis 7,
then:

```bash
cd persistance/backend
pip install -r requirements.txt
python migrate.py
uvicorn main:app --host 127.0.0.1 --port 8003
pytest -q
```

## Wire Person 2 (backend-policy)

```bash
# in the shell that runs backend-policy
export DATABASE_URL=postgresql://tg:tg@127.0.0.1:5432/time_grocer
export REDIS_URL=redis://127.0.0.1:6379/0
```

With those set, policy uses Postgres for the ledger and real Redis for
escalation TTL (instead of `data/ledger.jsonl` + in-process fakeredis).

## Endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | `{ok, postgres, redis, audit_entries, store}` |
| POST | `/log_event` | `{event, status, reason?, thought?}` → AuditEntry |
| GET | `/audit_log` | AuditEntry[] ascending by index |
| GET | `/audit_log/verify` | `{valid, broken_at, reason}` |
| POST | `/create_escalation` | Starts Redis TTL. Store-only — no policy re-check |
| GET | `/escalations/{id}` | PENDING / APPROVED / REFUSED / EXPIRED |
| POST | `/escalations/{id}/decision` | `{decision: APPROVE\|REFUSE}` |
| GET | `/spend/{account_id}` | Monthly spent (UTC `YYYY-MM`) |
| POST | `/spend` | Record a payment against monthly spend (idempotent) |
| POST | `/demo/reset`, `/demo/tamper/{i}` | need `DEMO_MODE=true` |

## Redis keys

```
esc:live:{id}      EX=ttl   open-request timer
esc:meta:{id}      JSON     escalation record (7-day TTL)
esc:decision:{id}  SET NX   APPROVED | REFUSED | EXPIRED
esc:dedupe:{hash}  EX=ttl   pending dedupe
esc:pending        set      sweeper membership
```

## Postgres tables

- `audit_entries` — append-only hash chain (`index|ts|event|status|reason|prev_hash`)
- `monthly_spend` — per-account UTC month totals
- `spend_ledger` — idempotent payment increments
