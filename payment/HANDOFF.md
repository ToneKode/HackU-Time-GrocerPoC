# HANDOFF — Payment module (HKT workshop Topic 4)

**For the next chat / agent.** Branch base: `main` (includes merged `persistance`).  
Workshop source: `20261002 Hackathon Workshop_HKT.pptx` (Fintech track).  
This PR implements a **PoC payment service** under `payment/` and wires the agent through it.

---

## Goal (from the deck)

Payment is a **controlled state machine**, not a single mall `/pay` call:

`Intent → Cart frozen → Authenticated → Authorized (scoped token) → Capture → Receipt → Refunds`

Principles: permissioned, least privilege, transparent, resilient, auditable, user in control.

## What this PR should contain

| Piece | Path | Notes |
|---|---|---|
| Payment API :8004 | `payment/backend/` | recommend → draft → authorize → capture → refund |
| Scoped tokens | `tokens.py` | one-time JWT: amt, merchant, currency, purpose, exp, jti |
| Rails | `rails.py` | mock Mastercard / UnionPay (open-loop shape); decline on 666.00 |
| Recommender | `recommender.py` | rank rails by net benefit (promo JSON + fees) |
| Agent client | `agent-brain/backend/clients.py` | `PaymentClient` |
| Agent `_pay` | `agent_graph.py` | draft+authorize via :8004; fallback to mall.pay if offline |
| Spend | unchanged | still `POST` persistance `/spend` after success |

## Ports / env

```
PAYMENT_API_PORT=8004
PAYMENT_API_BASE_URL=http://127.0.0.1:8004
PAYMENT_TOKEN_SECRET=dev-payment-secret
PAYMENT_TOKEN_TTL_SECONDS=600
MOCK_ACQUIRER_URL=   # empty = in-process mock rail; or http://127.0.0.1:8000 to hit mall /pay
REDIS_URL=           # optional; in-memory if unset
```

## Explicit non-goals (leave for follow-ups)

- Real OpenID4VCI / DID wallets
- FPS / BNPL / FX / split-pay
- Replacing Person 2 policy (payment **asks** policy; does not own budgets)
- Putting PAN/CVV anywhere — only tokenised rails

## How to verify

```bash
cd payment/backend && pip install -r requirements.txt && pytest -q
uvicorn main:app --port 8004
# with agent USE_SCRIPTED_PLANNER=true and persistance up:
# buy → payment health shows capture; spend increments
```

## Next-chat backlog (if not done here)

1. Persist payment records in Postgres (`persistance` schema) instead of memory/Redis
2. Risk score → step-up MFA flag (beyond existing >HK$500 escalate)
3. Refund UI + dispute evidence pack export
4. Frontend: show recommended rail + draft before execute
5. Wire `payment_route` discount into mall cart totals (Person 4)

## Related services

| Port | Service |
|---|---|
| 8000 | mock mall |
| 8001 | policy |
| 8002 | agent |
| 8003 | persistance |
| 8004 | **payment (this)** |
| 5173 | frontend |
