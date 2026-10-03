# persistance — durable stores for HacKU Time-Grocer · port 8003

Postgres holds the hash-chained audit ledger and monthly spend.
Redis holds escalation TTL keys; **Person 2 (`backend-policy` :8001) owns
create/decide HTTP**. This API exposes health, audit, and spend only.

## Bring up the stores

```bash
cd persistance
./start-stores.sh          # docker compose, or local Postgres/Redis
# then if API is not already up:
cd backend && pip install -r requirements.txt
python migrate.py
uvicorn main:app --host 127.0.0.1 --port 8003
pytest -q
```

## Auto-wiring Person 2

If `DATABASE_URL` / `REDIS_URL` are unset, `backend-policy` probes
`127.0.0.1:5432` / `:6379` (compose defaults) and uses them when reachable.
Unit tests still force fakeredis + JSONL via `conftest.py`.

## Agent monthly spend

Person 1 reads `GET /spend/{account_id}` before policy (default account `demo`)
and records `POST /spend` after a successful pay. Set
`PERSISTANCE_API_BASE_URL` (default `http://localhost:8003`).

## Endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | `{ok, postgres, redis, store, escalation_owner}` |
| POST | `/log_event` | Audit append (also done by policy when using same DB) |
| GET | `/audit_log` | AuditEntry[] |
| GET | `/audit_log/verify` | Chain verify |
| GET | `/spend/{account_id}` | Monthly spent (UTC `YYYY-MM`) |
| POST | `/spend` | Record payment (idempotent) |
| POST | `/demo/reset`, `/demo/tamper/{i}` | `DEMO_MODE=true` |

Escalation create/decide: **only** on `http://127.0.0.1:8001`.
