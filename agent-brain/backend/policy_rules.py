"""The frozen policy numbers. Person 2 owns the live engine.

Person 1 calls POST /check_policy. These rules are the fallback when that
service is down, so the frontend still receives PASS, ESCALATE, or HALT.
"""

from __future__ import annotations

PER_TRANSACTION_CAP = 500
BULK_CEILING = 800
MONTHLY_CAP = 2000
TTL_SECONDS = 600

WHITELIST = ["Watsons", "HKTVmall", "PARKnSHOP", "Japan Home Centre"]
BLACKLIST = ["DarkWebMart"]
# Same list as backend-policy/config.py. Empty means every category is allowed.
CATEGORY_BLACKLIST = []


def money(value: float) -> float:
    return round(float(value), 2)


def _listed(value: str, options: list[str]) -> bool:
    return value.strip().casefold() in {item.casefold() for item in options}


def _label(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}"


def _whole(value: float) -> int:
    return int(value) if value == int(value) else int(round(value))


def decide(
    merchant: str,
    category: str,
    amount: float,
    monthly_spent: float,
    monthly_cap: float | None = None,
    per_transaction_cap: float | None = None,
    bulk_ceiling: float | None = None,
) -> dict:
    """Same fallback as the policy service. Profile caps override the defaults."""
    amount = money(amount)
    monthly_spent = money(monthly_spent)
    monthly = money(MONTHLY_CAP if monthly_cap is None else monthly_cap)
    per_order = money(PER_TRANSACTION_CAP if per_transaction_cap is None else per_transaction_cap)
    bulk = money(BULK_CEILING if bulk_ceiling is None else bulk_ceiling)
    status = "PASS"
    reason = "Under HK$500 cap" if per_order == money(PER_TRANSACTION_CAP) else f"Under HK${_label(per_order)} cap"
    rule = "pass"
    if _listed(merchant, BLACKLIST):
        status, reason, rule = "HALT", "Merchant blacklisted", "merchant_blacklisted"
    elif not _listed(merchant, WHITELIST):
        status, reason, rule = "HALT", "Merchant not whitelisted", "merchant_not_whitelisted"
    elif _listed(category, CATEGORY_BLACKLIST):
        status, reason, rule = "HALT", "Category blacklisted", "category_blacklisted"
    elif money(monthly_spent + amount) > monthly:
        status, rule = "HALT", "monthly_cap"
        reason = "Over HK$2000 monthly cap" if monthly == money(MONTHLY_CAP) else f"Over HK${_label(monthly)} monthly cap"
    elif amount > bulk:
        status, rule = "HALT", "over_bulk_ceiling"
        reason = "Over HK$800 bulk ceiling" if bulk == money(BULK_CEILING) else f"Over HK${_label(bulk)} bulk ceiling"
    elif amount > per_order:
        status, rule = "ESCALATE", "over_per_transaction_cap"
        reason = (
            "Over HK$500 per-transaction cap"
            if per_order == money(PER_TRANSACTION_CAP)
            else f"Over HK${_label(per_order)} per-transaction cap"
        )

    if status == "HALT":
        remaining = money(monthly - monthly_spent)
    else:
        remaining = money(monthly - monthly_spent - amount)
    return {
        "status": status,
        "reason": reason,
        "amount": amount,
        "currency": "HKD",
        "monthly_spent": monthly_spent,
        "monthly_remaining": remaining,
        "per_transaction_cap": _whole(per_order),
        "monthly_cap": _whole(monthly),
        "bulk_ceiling": _whole(bulk),
        "rule": rule,
    }
