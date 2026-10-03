# Redis keyspace (escalation TTL + idempotency)

Postgres is the source of truth for durable rows. Redis owns **short-lived timers** and **hot idempotency** lookups so late approvals and double-pays fail closed.

## Connection

```
REDIS_URL=redis://127.0.0.1:6379/0
```

## Keys

### Escalation TTL (R3 / NFR2)

| Key | Type | TTL | Value |
|---|---|---|---|
| `escalation:{escalation_id}` | STRING | `user_policies.escalation_ttl_seconds` (default **600**) | JSON snapshot of Escalation at create time |

Example:

```
SET escalation:esc_demo '{"escalation_id":"esc_demo","status":"PENDING","amount":799.0,...}' EX 600
```

**Expiry behaviour**

1. Redis key disappears at TTL → policy API marks Postgres `escalations.status = EXPIRED` (lazy on read, or via keyspace notification).
2. Approve while key missing → set `late_approval_ignored = true`, `approval_attempt_at = now()`, **do not pay**. Return `escalation_expired`.
3. Approve while key present → `APPROVED`, delete Redis key, allow `POST /pay` with idempotency key.

### Payment idempotency

| Key | Type | TTL | Value |
|---|---|---|---|
| `idempotency:{key}` | STRING | 86400 (24h) | `public_order_id` or full PayResult JSON |

Template from cross-team config:

```
{sku}:{qty}:{policy_status}:{escalation_id|none}
```

Replay with the same key returns the first successful order (`duplicate_blocked`) and never charges again.

### Optional hot counters

| Key | Type | Notes |
|---|---|---|
| `budget:{user_id}:{YYYYMM}` | STRING | Cache of `monthly_spent`; invalidate on completed payment / refund |

## Demo helper

```bash
# Arm a 10-minute escalation for the seed esc_demo row
redis-cli SET escalation:esc_demo '{"escalation_id":"esc_demo","status":"PENDING"}' EX 600

# Force expire (late-approval race demo)
redis-cli DEL escalation:esc_demo
```
