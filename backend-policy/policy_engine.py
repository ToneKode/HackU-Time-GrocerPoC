"""Deterministic policy engine. The LLM never decides money questions.

Check order (first hit wins) — identical to cross_team_config.json:
  merchant_blacklisted -> merchant_not_whitelisted -> category_blacklisted
  -> monthly_cap -> over_bulk_ceiling -> over_per_transaction_cap -> pass
"""
from __future__ import annotations

from config import (BULK_CEILING, CATEGORY_BLACKLIST, CURRENCY, MERCHANT_BLACKLIST,
                    MERCHANT_WHITELIST, MONTHLY_CAP, PER_TRANSACTION_CAP, REASONS)


def _money(v: float) -> float:
    return round(float(v), 2)


def _in(value: str, options: list[str]) -> bool:
    return value.strip().casefold() in {o.casefold() for o in options}


def evaluate(merchant: str, category: str, amount: float, monthly_spent: float) -> dict:
    amount, spent = _money(amount), _money(monthly_spent)

    if _in(merchant, MERCHANT_BLACKLIST):
        status, rule, reason = "HALT", "merchant_blacklisted", REASONS["HALT_MERCHANT_BLACKLIST"]
    elif not _in(merchant, MERCHANT_WHITELIST):
        status, rule, reason = "HALT", "merchant_not_whitelisted", REASONS["HALT_MERCHANT"]
    elif _in(category, CATEGORY_BLACKLIST):
        status, rule, reason = "HALT", "category_blacklisted", REASONS["HALT_CATEGORY"]
    elif spent + amount > MONTHLY_CAP:
        status, rule, reason = "HALT", "monthly_cap", REASONS["HALT_MONTHLY"]
    elif amount > BULK_CEILING:
        status, rule, reason = "HALT", "over_bulk_ceiling", REASONS["HALT_BULK"]
    elif amount > PER_TRANSACTION_CAP:
        status, rule, reason = "ESCALATE", "over_per_transaction_cap", REASONS["ESCALATE"]
    else:
        status, rule, reason = "PASS", "pass", REASONS["PASS"]

    remaining = MONTHLY_CAP - spent if status == "HALT" else MONTHLY_CAP - spent - amount
    return {
        "status": status,
        "reason": reason,
        "amount": amount,
        "currency": CURRENCY,
        "monthly_spent": spent,
        "monthly_remaining": _money(remaining),
        "per_transaction_cap": int(PER_TRANSACTION_CAP),
        "monthly_cap": int(MONTHLY_CAP),
        "bulk_ceiling": int(BULK_CEILING),
        "rule": rule,            # extra field: which rule fired (for the trace UI)
    }
