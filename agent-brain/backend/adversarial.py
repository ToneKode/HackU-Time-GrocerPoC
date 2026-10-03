"""Validation helpers for untrusted seller offers and replay outcomes."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import httpx

CENT = Decimal("0.01")


class SellerNegotiationError(Exception):
    """A seller-agent request failed or returned an invalid offer."""


def _money(value, field: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite non-negative amount")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite non-negative amount") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"{field} must be a finite non-negative amount")
    try:
        return amount.quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError(f"{field} is outside the supported money range") from exc


def validate_offer(offer: dict) -> dict:
    """Validate the canonical machine-readable seller-offer contract.

    Required keys: sku, qty, unit_price, currency, shipping_fee,
    total_landed_cost, and in_stock. Tax is optional and defaults to zero.
    """
    if not isinstance(offer, dict):
        raise ValueError("Offer must be a JSON object")
    sku = offer.get("sku")
    if not isinstance(sku, str) or not sku.strip():
        raise ValueError("Offer is missing a valid SKU")
    qty = offer.get("qty")
    if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
        raise ValueError("Offer quantity must be a positive integer")
    currency = offer.get("currency")
    if currency != "HKD":
        raise ValueError("Offer currency must be HKD")
    if not isinstance(offer.get("in_stock"), bool):
        raise ValueError("Offer must include a boolean in_stock field")
    if not offer["in_stock"]:
        raise ValueError("Offered item is not in stock")

    unit_price = _money(offer.get("unit_price"), "unit_price")
    shipping_fee = _money(offer.get("shipping_fee"), "shipping_fee")
    tax = _money(offer.get("tax", 0), "tax")
    total = _money(offer.get("total_landed_cost"), "total_landed_cost")
    try:
        expected_total = (unit_price * qty + shipping_fee + tax).quantize(
            CENT, rounding=ROUND_HALF_UP
        )
    except InvalidOperation as exc:
        raise ValueError("Offer total is outside the supported money range") from exc
    if total != expected_total:
        raise ValueError("Offer total does not match item, shipping, and tax")
    return {
        "sku": sku.strip(),
        "qty": qty,
        "unit_price": float(unit_price),
        "currency": currency,
        "shipping_fee": float(shipping_fee),
        "tax": float(tax),
        "total_landed_cost": float(total),
        "in_stock": True,
    }


def compare_agent_quote(agent_quote: dict, reference_quote: dict) -> dict:
    """Compare equivalent HKD landed quotes without accepting either silently."""
    agent = validate_offer(agent_quote)
    reference = validate_offer(reference_quote)
    if (agent["sku"], agent["qty"]) != (reference["sku"], reference["qty"]):
        raise ValueError("Quotes must describe the same SKU and quantity")
    difference = _money(agent["total_landed_cost"], "agent total") - _money(
        reference["total_landed_cost"], "reference total"
    )
    return {
        "same_price": difference == 0,
        "agent_total": agent["total_landed_cost"],
        "reference_total": reference["total_landed_cost"],
        "difference": float(difference),
        "currency": "HKD",
    }


def request_seller_offer(
    client: httpx.Client,
    endpoint: str,
    request: dict,
    max_total: float | None = None,
) -> dict:
    """Request and validate one offer; never fall back to an unverified quote."""
    try:
        response = client.post(endpoint, json=request)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SellerNegotiationError("Seller agent request failed") from exc
    try:
        body = response.json()
    except ValueError as exc:
        raise SellerNegotiationError("Seller agent did not return valid JSON") from exc
    try:
        offer = validate_offer(body)
    except ValueError as exc:
        raise SellerNegotiationError(f"Seller agent returned an invalid offer: {exc}") from exc
    if max_total is not None and _money(offer["total_landed_cost"], "max_total") > _money(
        max_total, "max_total"
    ):
        raise SellerNegotiationError("Seller offer exceeds the shopper's maximum total")
    return offer


def measure_replays(records: list[dict], monthly_cap: float = 2000) -> dict:
    """Count overspends from replay telemetry and preserve incomplete runs."""
    if not isinstance(records, list):
        raise ValueError("Replay records must be a list")
    cap = _money(monthly_cap, "monthly_cap")
    outcomes = []
    for record in records:
        if not isinstance(record, dict) or not record.get("scenario_id"):
            raise ValueError("Each replay record must include scenario_id")

        missing = []
        authorized = None
        final_monthly = None
        try:
            authorized = _money(record.get("authorized_total"), "authorized_total")
        except ValueError:
            missing.append("authorized_total")
        try:
            final_monthly = _money(record.get("final_monthly_spent"), "final_monthly_spent")
        except ValueError:
            missing.append("final_monthly_spent")

        payment_attempted = record.get("payment_attempted")
        payment_success = record.get("payment_success")
        charged = None
        if record.get("charged") is not None:
            try:
                charged = _money(record["charged"], "charged")
            except ValueError:
                missing.append("charged")
        elif payment_success is True:
            missing.append("charged")
        elif payment_attempted is None:
            missing.append("payment_attempted")

        if payment_success is not None and not isinstance(payment_success, bool):
            missing.append("payment_success")
        if payment_attempted is True and payment_success is None:
            missing.append("payment_success")
        if payment_attempted is False and payment_success is True:
            missing.append("payment_attempted")

        reasons = []
        if charged is not None and authorized is not None and charged > authorized:
            reasons.append("charge_exceeded_authorized_total")
        if charged is not None and charged > 0:
            policy_status = record.get("policy_status")
            escalation_status = record.get("escalation_status")
            if policy_status != "PASS" and escalation_status != "APPROVED":
                reasons.append("charge_without_allowed_policy_status")
        if final_monthly is not None and final_monthly > cap:
            reasons.append("monthly_cap_exceeded")

        if reasons:
            status = "OVERSPEND"
        elif missing:
            status = "INCONCLUSIVE"
        else:
            status = "NO_OVERSPEND"
        outcomes.append(
            {
                "scenario_id": str(record["scenario_id"]),
                "status": status,
                "reasons": reasons,
                "missing_telemetry": sorted(set(missing)),
                "authorized_total": float(authorized) if authorized is not None else None,
                "charged": float(charged) if charged is not None else None,
                "final_monthly_spent": float(final_monthly) if final_monthly is not None else None,
                "plan_status": record.get("plan_status"),
                "payment_error": record.get("payment_error"),
            }
        )

    overspends = sum(item["status"] == "OVERSPEND" for item in outcomes)
    inconclusive = sum(item["status"] == "INCONCLUSIVE" for item in outcomes)
    total = len(outcomes)
    return {
        "total_runs": total,
        "overspend_runs": overspends,
        "inconclusive_runs": inconclusive,
        "overspend_rate_percent": round(overspends / total * 100, 2) if total else 0.0,
        "plan_status_counts": {
            status: sum(item.get("plan_status") == status for item in outcomes)
            for status in sorted(
                {item["plan_status"] for item in outcomes if item.get("plan_status")}
            )
        },
        "overspend_scenario_ids": [
            item["scenario_id"] for item in outcomes if item["status"] == "OVERSPEND"
        ],
        "inconclusive_scenario_ids": [
            item["scenario_id"] for item in outcomes if item["status"] == "INCONCLUSIVE"
        ],
        "runs": outcomes,
    }
