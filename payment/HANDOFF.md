# HANDOFF — Payment module (HKT workshop Topic 4)

**Status: IMPLEMENTED on branch `cursor/payment-module-c31f`.**  
Use this doc to continue (Postgres persistence for payments, frontend rail UI, etc.).

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

### State machine
`DRAFT → AUTHORIZED → CAPTURED` (auto-capture on success) · `FAILED` · `REFUNDED`

### Verify
```bash
cd payment/backend && pytest -q   # 6 passed
uvicorn main:app --port 8004
# Agent: PAYMENT_API_BASE_URL=http://127.0.0.1:8004 USE_SCRIPTED_PLANNER=true
```

---

## Goal (from the deck) — still the north star

Payment is a **controlled process**: scoped token, rail recommend, authorize/capture, evidence — not a naked mall `/pay`.

## Next-chat backlog

1. Persist payment records in Postgres (`persistance` schema) instead of memory
2. Risk score → step-up MFA flag (beyond existing >HK$500 escalate)
3. Refund UI + dispute evidence pack export
4. Frontend: show recommended rail + draft before execute
5. Apply `payment_route` discount into mall cart totals (Person 4)
6. Optional: set `MOCK_ACQUIRER_URL=http://127.0.0.1:8000` to charge via real mock mall

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
