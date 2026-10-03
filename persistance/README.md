# persistance — durable stores for HacKU Time-Grocer · port 8003

MySQL holds the hash-chained audit ledger, monthly spend, shopper
profiles, orders, and the product shelf. The app connects to host MySQL on
**127.0.0.1:3306**, database `time_grocer`. Redis holds escalation TTL keys; **Person 2
(`backend-policy` :8001) owns create/decide HTTP**.

## Bring up the stores

```bash
cd persistance
./start-stores.sh          # optional compose Postgres/Redis; the app database is host MySQL :3306
# then if API is not already up:
cd backend && pip install -r requirements.txt
python migrate.py
uvicorn main:app --host 127.0.0.1 --port 8003
pytest -q
```

## Auto-wiring Person 2

If `DATABASE_URL` / `REDIS_URL` are unset, `backend-policy` probes
`mysql://127.0.0.1:3306/time_grocer` / `:6379` and uses them when reachable.
Unit tests still force fakeredis + JSONL via `conftest.py`.
Persistance tests use database `time_grocer_test` on the same MySQL server so
`/demo/reset` cannot truncate the shop database.

## Agent monthly spend

Person 1 reads `GET /spend/{account_id}` before policy (default account `demo`)
and records `POST /spend` after a successful pay. Set
`PERSISTANCE_API_BASE_URL` (default `http://localhost:8003`).

## Endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | `{ok, mysql, redis, store, catalog_products, escalation_owner}` |
| POST | `/log_event` | Audit append (also done by policy when using same DB) |
| GET | `/audit_log` | AuditEntry[] |
| GET | `/audit_log/verify` | Chain verify |
| GET | `/spend/{account_id}` | Monthly spent (UTC `YYYY-MM`) |
| POST | `/spend` | Record payment (idempotent) |
| POST | `/accounts/register`, `/accounts/login` | Password is hashed. The response has no password. |
| GET | `/accounts/{id}/profile` | Caps, spent, address, payment methods, last purchase, recent orders |
| POST | `/orders`, `/orders/{id}/checkpoint` | Open a run, then save each workflow step |
| GET/POST/DELETE | `/accounts/{id}/chat` | Chat history for that account |
| GET/POST | `/accounts/{id}/tasks` | Recurrent tasks |
| GET | `/accounts/{id}/agent-history` | One row per shopping run |
| GET | `/catalog/products?q=&merchant=&category=&limit=` | Shelf rows. `limit` max 6000 |
| GET | `/catalog/products/{sku}`, `/catalog/categories` | One product, or category counts |
| POST | `/demo/reset`, `/demo/tamper/{i}` | Clears audit and spend only. Accounts and the catalog stay. |

Load the shop shelf once credentials work:

```bash
cd persistance/backend
python load_catalog.py
```

That reads `agent-brain/hk_products_full.json` and upserts `catalog_products`. Restart the agent on port 8002 afterwards so it prices those SKUs. The model still sees at most 40 matching rows.

Escalation create/decide: **only** on `http://127.0.0.1:8001`.
