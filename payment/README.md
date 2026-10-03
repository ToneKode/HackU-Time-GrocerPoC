# payment — Agentic payment control loop · port 8004

HKT workshop Topic 4 (PoC): scoped delegated payment, rail recommend,
authorize/capture state machine. Agent drafts; user/policy approves; rails execute.

See `HANDOFF.md` for the next-chat context.

## Run

```bash
cd payment/backend
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8004
pytest -q
```

## Endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | ok + store |
| POST | `/payment/recommend` | Rank mastercard / unionpay by net benefit |
| POST | `/payment/draft` | Freeze amount + mint one-time scoped token |
| POST | `/payment/authorize` | Consume token; call rail (or mock mall `/pay`) |
| POST | `/payment/{id}/capture` | Mark captured (idempotent) |
| POST | `/payment/{id}/refund` | Compensating action |
| GET | `/payment/{id}` | Status + evidence |

## State machine

`DRAFT → AUTHORIZED → CAPTURED` (or `FAILED` / `REFUNDED`)

Token payload (JWT): `iss, sub, aud (merchant), amt, cur, pur, exp, jti, one_time_use, rail`.
