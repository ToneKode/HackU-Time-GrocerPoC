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


def _cap(value: float | None, default: float) -> float:
    return _money(default) if value is None else _money(value)


def _hk(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}"


def _whole(value: float) -> int:
    return int(value) if value == int(value) else int(round(value))


def evaluate(
    merchant: str,
    category: str,
    amount: float,
    monthly_spent: float,
    monthly_cap: float | None = None,
    per_transaction_cap: float | None = None,
    bulk_ceiling: float | None = None,
) -> dict:
    """Caps default to the contract numbers. A shopper profile may override them."""
    amount, spent = _money(amount), _money(monthly_spent)
    monthly = _cap(monthly_cap, MONTHLY_CAP)
    per_order = _cap(per_transaction_cap, PER_TRANSACTION_CAP)
    bulk = _cap(bulk_ceiling, BULK_CEILING)

    if _in(merchant, MERCHANT_BLACKLIST):
        status, rule, reason = "HALT", "merchant_blacklisted", REASONS["HALT_MERCHANT_BLACKLIST"]
    elif not _in(merchant, MERCHANT_WHITELIST):
        status, rule, reason = "HALT", "merchant_not_whitelisted", REASONS["HALT_MERCHANT"]
    elif _in(category, CATEGORY_BLACKLIST):
        status, rule, reason = "HALT", "category_blacklisted", REASONS["HALT_CATEGORY"]
    elif spent + amount > monthly:
        status, rule = "HALT", "monthly_cap"
        reason = REASONS["HALT_MONTHLY"] if monthly == _money(MONTHLY_CAP) else f"Over HK${_hk(monthly)} monthly cap"
    elif amount > bulk:
        status, rule = "HALT", "over_bulk_ceiling"
        reason = REASONS["HALT_BULK"] if bulk == _money(BULK_CEILING) else f"Over HK${_hk(bulk)} bulk ceiling"
    elif amount > per_order:
        status, rule = "ESCALATE", "over_per_transaction_cap"
        reason = REASONS["ESCALATE"] if per_order == _money(PER_TRANSACTION_CAP) else f"Over HK${_hk(per_order)} per-transaction cap"
    else:
        status, rule = "PASS", "pass"
        reason = REASONS["PASS"] if per_order == _money(PER_TRANSACTION_CAP) else f"Under HK${_hk(per_order)} cap"

    remaining = monthly - spent if status == "HALT" else monthly - spent - amount
    return {
        "status": status,
        "reason": reason,
        "amount": amount,
        "currency": CURRENCY,
        "monthly_spent": spent,
        "monthly_remaining": _money(remaining),
        "per_transaction_cap": _whole(per_order),
        "monthly_cap": _whole(monthly),
        "bulk_ceiling": _whole(bulk),
        "rule": rule,            # extra field: which rule fired (for the trace UI)
    }
