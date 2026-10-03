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


def decide(
    merchant: str,
    category: str,
    amount: float,
    monthly_spent: float,
) -> dict:
    amount = money(amount)
    monthly_spent = money(monthly_spent)
    status = "PASS"
    reason = "Under HK$500 cap"
    rule = "pass"
    if _listed(merchant, BLACKLIST):
        status, reason, rule = "HALT", "Merchant blacklisted", "merchant_blacklisted"
    elif not _listed(merchant, WHITELIST):
        status, reason, rule = "HALT", "Merchant not whitelisted", "merchant_not_whitelisted"
    elif _listed(category, CATEGORY_BLACKLIST):
        status, reason, rule = "HALT", "Category blacklisted", "category_blacklisted"
    elif money(monthly_spent + amount) > MONTHLY_CAP:
        status, reason, rule = "HALT", "Over HK$2000 monthly cap", "monthly_cap"
    elif amount > BULK_CEILING:
        status, reason, rule = "HALT", "Over HK$800 bulk ceiling", "over_bulk_ceiling"
    elif amount > PER_TRANSACTION_CAP:
        status, reason, rule = "ESCALATE", "Over HK$500 per-transaction cap", "over_per_transaction_cap"

    if status == "HALT":
        remaining = money(MONTHLY_CAP - monthly_spent)
    else:
        remaining = money(MONTHLY_CAP - monthly_spent - amount)
    return {
        "status": status,
        "reason": reason,
        "amount": amount,
        "currency": "HKD",
        "monthly_spent": monthly_spent,
        "monthly_remaining": remaining,
        "per_transaction_cap": PER_TRANSACTION_CAP,
        "monthly_cap": MONTHLY_CAP,
        "bulk_ceiling": BULK_CEILING,
        "rule": rule,
    }
