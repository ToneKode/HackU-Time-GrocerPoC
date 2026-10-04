"""Settlement facts and rewards come from a captured payment, not the caller."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import httpx
from fastapi import HTTPException
from market_store import DEFAULT_PAYMENT_PROMOTIONS, PaymentPromotion, price_quote


def _money(value) -> Decimal:
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0 or amount != amount.quantize(Decimal("0.01")):
            raise ValueError("Invalid monetary amount")
        return amount
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("Invalid monetary amount") from exc


def fetch_payment(base_url: str, payment_id: str) -> dict:
    try:
        with httpx.Client(base_url=base_url.rstrip("/"), timeout=5.0) as client:
            response = client.get(f"/payment/{payment_id}")
            if response.status_code == 404:
                raise HTTPException(422, "Unknown payment")
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("Invalid payment response")
            if result.get("rail") == "split":
                captures = []
                for child_id in result.get("children") or []:
                    child_response = client.get(f"/payment/{child_id}")
                    child_response.raise_for_status()
                    child = child_response.json()
                    if not isinstance(child, dict):
                        raise ValueError("Invalid merchant payment response")
                    captures.append(child)
                result["captures"] = captures
            return result
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, "Payment verification unavailable; retry settlement") from exc


def verified_settlement(payment: dict, account_id: str, payment_id: str, amount, currency: str) -> dict:
    if payment.get("payment_id") != payment_id or payment.get("account_id") != account_id:
        raise ValueError("Payment does not belong to this account")
    if payment.get("status") != "CAPTURED" or payment.get("rail_verified") is not True:
        raise ValueError("Payment must have a verified capture")
    if not payment.get("order_id") or not payment.get("receipt_id"):
        raise ValueError("Payment capture evidence missing")
    total = _money(amount)
    if _money(payment.get("amount")) != total or _money(payment.get("charged")) != total:
        raise ValueError("Payment amount mismatch")
    if currency != "HKD" or payment.get("currency") != currency or payment.get("charged_currency") != currency:
        raise ValueError("Payment currency mismatch")
    market = None
    if payment.get("market_quote") is not None:
        stored = payment["market_quote"]
        snapshot = stored.get("promotion_snapshot") or {}
        try:
            market = price_quote(snapshot["requested_lines"], snapshot["products"], snapshot["rules"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Invalid captured promotion snapshot") from exc
        if market != stored:
            raise ValueError("Captured market quote does not match its rules and prices")
        if payment.get("market_merchant"):
            scoped = [r for r in market["merchants"] if r["merchant"] == payment["merchant"]]
            if len(scoped) != 1 or _money(scoped[0]["total"]) != total:
                raise ValueError("Merchant capture does not match priced draft")
            scoped_subtotal = Decimal(str(scoped[0]["subtotal"]))
            scoped_discount = Decimal(str(scoped[0]["discount"]))
            market = dict(market, lines=[r for r in market["lines"] if r["merchant"] == payment["merchant"]],
                          discount=float(scoped_discount), subtotal=float(scoped_subtotal),
                          reward_base=float(scoped_subtotal - scoped_discount))
        elif _money(market["total"]) != total:
            raise ValueError("Capture does not match priced draft")
    market_fields = {"lines": market["lines"], "market_quote": market,
                     "rules_version": market["rules_version"], "discount": market["discount"]} if market else {}
    route = payment.get("rail") or ""
    merchant = payment.get("merchant") or ""
    if route == "split":
        children = payment.get("children") or []
        captures = payment.get("captures") or []
        allocations = payment.get("allocations") or []
        if not children or len(children) != len(set(children)) or len(captures) != len(children) or len(allocations) != len(children):
            raise ValueError("Incomplete merchant capture evidence")
        benefits = []
        verified = []
        for child_id, capture, allocation in zip(children, captures, allocations):
            if capture.get("rail") == "split" or capture.get("rail") != allocation.get("rail") or capture.get("merchant") != allocation.get("merchant"):
                raise ValueError("Merchant capture allocation mismatch")
            child = verified_settlement(capture, account_id, child_id, allocation.get("amount"), currency)
            verified.append(child)
            benefits.extend(child["benefits"])
            if market is not None:
                if capture.get("market_quote") != payment.get("market_quote"):
                    raise ValueError("Merchant snapshot does not match basket snapshot")
        if sum((_money(child["total"]) for child in verified), Decimal(0)) != total:
            raise ValueError("Merchant captures do not match basket total")
        return {"currency": currency, "total": float(total), "merchant": merchant,
                "payment_route": route, "payment_id": payment_id, "benefits": benefits,
                "allocations": verified,
                "merchants": [{"merchant": child["merchant"],
                               "payment": {"route": child["payment_route"], "amount": child["total"]},
                               "benefits": child["benefits"]} for child in verified],
                "payment_order_id": payment["order_id"], "source": "verified_payment_capture", **market_fields}
    promotions = DEFAULT_PAYMENT_PROMOTIONS
    if market is not None:
        promotions = market["promotion_snapshot"]["rules"].get("payment_promotions", promotions)
    selected = {}
    for raw in promotions:
        promotion = PaymentPromotion.model_validate(raw)
        if promotion.route != route or promotion.merchant not in ("", merchant):
            continue
        previous = selected.get(promotion.kind)
        # Merchant-specific rules override the route's general reward, including disabled rules.
        if previous is None or promotion.merchant:
            selected[promotion.kind] = promotion
    rates = [(kind, Decimal(str(rule.rate))) for kind, rule in selected.items() if rule.enabled]
    reward_base = total
    if market is not None:
        goods_total = Decimal(str(market["subtotal"])) - Decimal(str(market["discount"]))
        reward_base = Decimal(str(market.get("reward_base", goods_total)))
    benefits = [
        {"kind": kind, "amount": float((reward_base * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
         "detail": f"Verified {route} capture at {merchant}"}
        for kind, rate in rates
    ]
    return {"currency": currency, "total": float(total), "merchant": merchant,
            "payment_route": route, "payment_id": payment_id, "benefits": benefits,
            "payment_order_id": payment["order_id"], "source": "verified_payment_capture", **market_fields}
