# Schema map → product idea & demos

## Access model

| Actor | Can do | Tables |
|---|---|---|
| Guest (unlogged) | Browse official merchant prices | `merchants`, `products` (SELECT) |
| Logged-in user | NL mandate → agent plan → pay / escalate / halt | all transactional tables |

## Decision engine persistence

| Rule | Condition | DB / Redis |
|---|---|---|
| R1 | Merchant not whitelisted / blacklisted / banned category | `merchants.list_status`, `category_rules` |
| R2 | TLC ≤ per_tx AND monthly+TLC ≤ monthly | `user_policies` + order amount |
| R3 | TLC > per_tx (and ≤ bulk_ceiling) | `escalations` + Redis TTL key |
| R4 | TLC ≤ per_tx but monthly breached | `user_policies.monthly_spent` → HALT |

`total_landed_cost` is always stored on quotes/orders (item + shipping − rewards). Never decide on shelf price alone.

## Demo coverage

| Scenario | Status / outcome | Where |
|---|---|---|
| Success payment | `orders.status = completed` | seed demo order |
| Exceeds tx / monthly cap | `mandates.status = halted` + audit reason | reason codes |
| Whitelist / category violation | `policy_violations` rows | R1 |
| Escalation pending / approved / refused / expired | `escalations.status` | Redis TTL |
| Late approval after expiry | `late_approval_ignored = true` | escalations |
| Duplicate / replay | `idempotency_keys` unique | Redis + PG |
| Mandate revoked mid-flight | `mandates.revoked_at` | check before pay |
| Malicious product listing | `products.name` treated untrusted | catalog only |
| Mixed basket partial ban | `mandate_line_items` + violations | per-SKU category |
| Ambiguous mandate | `mandates.status = needs_clarification` | no pay |
| Hash-chained trust ledger | `audit_log` | SHA-256 chain |

## Hash chain (FR7 / NFR4)

```
hash = sha256_hex( index | ts | event | status | reason | prev_hash )
genesis prev_hash = 64 zero hex chars
```

Fields and join delimiter match `cross_team_config.audit` and `frontend/contract.json`.
