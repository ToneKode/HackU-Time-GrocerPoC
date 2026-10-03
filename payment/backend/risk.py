"""Payment risk score and step-up flag.

This is separate from the policy service. Policy already escalates a basket
over HK$500. A payment can still require step-up while that check would PASS,
for example a charge of HK$400–499.
"""
from __future__ import annotations

STEP_UP_AT = 50


def assess(amount: float, rail: str, recommended_rail: str | None = None) -> dict:
    amount = round(float(amount), 2)
    factors: list[str] = []
    if amount >= 400:
        score = 55
        factors.append("amount_at_least_400")
    elif amount >= 150:
        score = 25
        factors.append("amount_at_least_150")
    else:
        score = 5
        factors.append("amount_under_150")
    if recommended_rail and rail and rail != recommended_rail:
        score += 25
        factors.append("rail_not_recommended")
    score = min(score, 100)
    required = score >= STEP_UP_AT
    return {
        "risk_score": score,
        "step_up_required": required,
        "step_up_reason": (
            "Confirm this payment before the rail is charged." if required else ""
        ),
        "risk_factors": factors,
    }
