"""Best-payment recommender — rank rails by net benefit (workshop Topic 4)."""
from __future__ import annotations

from pathlib import Path

RAILS = ("mastercard", "unionpay")

# Simple PoC fee / cashback model (HKD). Promo file can override later.
RAIL_PROFILE = {
    "mastercard": {"fee_rate": 0.0, "cashback_rate": 0.01, "label": "Mastercard"},
    "unionpay": {"fee_rate": 0.0, "cashback_rate": 0.015, "label": "UnionPay"},
}

PROMO_CANDIDATES = [
    Path(__file__).resolve().parents[2]
    / "agent-brain"
    / "backend"
    / "hk_retail_promos_20261003.json",
]


def _load_payment_offers() -> list[dict]:
    import json

    for path in PROMO_CANDIDATES:
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            rows = data if isinstance(data, list) else data.get("offers") or data.get("promos") or []
            return [r for r in rows if str(r.get("category") or "") == "payment"]
    return []


def recommend(
    amount: float,
    *,
    merchants: list[str] | None = None,
    preferred: str | None = None,
) -> list[dict]:
    """Return rails ranked by estimated net benefit (higher is better)."""
    amount = round(float(amount), 2)
    merchants = merchants or []
    offers = _load_payment_offers()
    ranked = []
    for rail in RAILS:
        profile = RAIL_PROFILE[rail]
        fee = round(amount * profile["fee_rate"], 2)
        cashback = round(amount * profile["cashback_rate"], 2)
        promo_bonus = 0.0
        promo_title = ""
        for offer in offers:
            method = str(offer.get("payment_method") or "").strip().casefold()
            retailer = str(offer.get("retailer") or "")
            if method != rail:
                continue
            if merchants and retailer and retailer not in merchants:
                continue
            # Crude: 2% promo if description mentions %
            desc = str(offer.get("description") or "")
            if "%" in desc:
                try:
                    pct = float("".join(ch if ch.isdigit() or ch == "." else " " for ch in desc).split()[0])
                    promo_bonus = max(promo_bonus, round(amount * (pct / 100.0), 2))
                    promo_title = str(offer.get("title") or desc)
                except (ValueError, IndexError):
                    pass
        net = round(cashback + promo_bonus - fee, 2)
        effective = round(amount - net, 2)
        ranked.append(
            {
                "rail": rail,
                "label": profile["label"],
                "amount": amount,
                "fee": fee,
                "cashback": cashback,
                "promo_bonus": promo_bonus,
                "promo_title": promo_title,
                "net_benefit": net,
                "effective_cost": effective,
                "currency": "HKD",
                "preferred": preferred == rail,
            }
        )
    ranked.sort(key=lambda row: (-row["net_benefit"], row["rail"]))
    if preferred:
        ranked.sort(key=lambda row: (0 if row["rail"] == preferred else 1, -row["net_benefit"]))
    for index, row in enumerate(ranked, start=1):
        row["rank"] = index
    return ranked


def pick_rail(amount: float, merchants: list[str] | None = None, preferred: str | None = None) -> dict:
    rows = recommend(amount, merchants=merchants, preferred=preferred)
    return rows[0] if rows else {"rail": "mastercard", "reason": "default"}
