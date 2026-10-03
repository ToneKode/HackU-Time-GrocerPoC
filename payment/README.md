# payment — Agentic payment control loop · port 8004

HKT workshop Topic 4 (PoC): scoped delegated payment, rail recommend,
authorize/capture state machine. Agent drafts; user/policy approves; rails execute.

See `HANDOFF.md` for the next-chat context.

## Run

```powershell
Set-Location payment\backend
py -3.13 -m pip install -r requirements.txt
py -3.13 -m uvicorn main:app --host 127.0.0.1 --port 8004
py -3.13 -m pytest -q
```

Records land in the shared `payments` / `payment_jti` tables
(`persistance/backend/schema.sql`) on host MySQL `time_grocer` at
`127.0.0.1:3306`. Leave `DATABASE_URL` unset and the service uses that
database when MySQL answers. Set `DATABASE_URL` empty and the API keeps the
in-memory store. An explicit `DATABASE_URL` is used as-is.

## Endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | ok + `store` (`mysql` or `memory`) |
| POST | `/payment/recommend` | Rank mastercard / unionpay by net benefit |
| POST | `/payment/draft` | Freeze amount + mint one-time scoped token |
| POST | `/payment/authorize` | Consume token; call rail (or mock mall `/pay`). Body `step_up_confirmed` when the draft requires it |
| POST | `/payment/{id}/capture` | Mark captured (idempotent) |
| POST | `/payment/{id}/refund` | Compensating action |
| GET | `/payment/{id}` | Status + evidence |
| GET | `/payment/{id}/evidence` | Dispute pack. Omits the JWT |

## State machine

`DRAFT → AUTHORIZED → CAPTURED` (or `FAILED` / `REFUNDED`)

Token payload (JWT): `iss, sub, aud (merchant), amt, cur, pur, exp, jti, one_time_use, rail`.
