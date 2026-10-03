# HANDOFF — Payment module (HKT workshop Topic 4)

**Status: payment records persist in Postgres** (`payments`, `payment_jti` in `persistance/backend/schema.sql`).  
In-memory store remains when `DATABASE_URL` is empty, or when it is unset and Postgres is unreachable.  
Use this doc to continue (frontend rail UI, risk step-up, refund evidence).

**Workshop source:** `20261002 Hackathon Workshop_HKT.pptx` (Fintech track, Topic 4).  
**Base:** `main` (includes merged `persistance`).

---

## What shipped

| Piece | Path |
|---|---|
| Payment API :8004 | `payment/backend/` |
| Scoped JWT tokens | `tokens.py` |
| Mock Mastercard / UnionPay rails | `rails.py` (decline `666.00`) |
| Net-benefit recommender | `recommender.py` |
| Agent `PaymentClient` | `agent-brain/backend/clients.py` |
| Agent `_pay` → draft+authorize | `agent_graph.py` (mall.pay fallback if :8004 down) |
| Postgres payment records | `persistance/backend/schema.sql` (`002_payments`), `payment/backend/pg_store.py` |
| Risk score + step-up | `payment/backend/risk.py` (HK$400+ flags MFA; policy HK$500 gate is unchanged) |
| Evidence pack | `GET /payment/{id}/evidence` |
| Mall rail discount | `POST /cart` `payment_route` → reduced `total_landed_cost` |
| Agent holds the draft | `POST /agent/intent` returns `payment_draft` when :8004 is up; `POST /agent/payment/authorize` captures |

### State machine
`DRAFT → AUTHORIZED → CAPTURED` (auto-capture on success) · `FAILED` · `REFUNDED`

### Verify
```bash
cd payment/backend && pytest -q   # memory suite always; Postgres suite when :5432 is up
uvicorn main:app --port 8004
# Agent: PAYMENT_API_BASE_URL=http://127.0.0.1:8004 USE_SCRIPTED_PLANNER=true
# Unset DATABASE_URL auto-detects postgresql://tg:tg@127.0.0.1:5432/time_grocer
```

---

## Goal (from the deck) — still the north star

Payment is a **controlled process**: scoped token, rail recommend, authorize/capture, evidence — not a naked mall `/pay`.

## Next-chat backlog

1. Frontend refund screen (the refund API and `GET /payment/{id}/evidence` already exist)
2. Frontend: show `payment_draft` (rail, amount, step-up flag) and call `POST /agent/payment/authorize`

## Ports

| Port | Service |
|---|---|
| 8000 | mock mall |
| 8001 | policy |
| 8002 | agent |
| 8003 | persistance |
| **8004** | **payment** |
| 5173 | frontend |

## Explicit non-goals

Real OpenID4VCI/DID, FPS/BNPL/FX/split-pay, replacing Person 2 policy, storing PAN/CVV.
