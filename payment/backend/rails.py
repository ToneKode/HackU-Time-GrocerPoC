"""Mock open-loop rails (Mastercard / UnionPay).

When MOCK_ACQUIRER_URL is set, authorize posts to that mall's /pay.
Otherwise charges in-process (decline cart_total == 666.00).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

DECLINE_TOTAL = 666.0


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def charge_local(amount: float, rail: str, idempotency_key: str) -> dict[str, Any]:
    amount = round(float(amount), 2)
    if amount == DECLINE_TOTAL:
        return {
            "success": False,
            "error": "card_declined",
            "auth_id": None,
            "order_id": None,
            "charged": None,
            "currency": "HKD",
            "payment_route": rail,
            "ts": _ts(),
        }
    order_id = "ORD-" + uuid.uuid4().hex[:8]
    auth_id = "AUTH-" + uuid.uuid4().hex[:10]
    return {
        "success": True,
        "error": None,
        "auth_id": auth_id,
        "order_id": order_id,
        "charged": amount,
        "currency": "HKD",
        "payment_route": rail,
        "reward_points_earned": int(amount // 10),
        "ts": _ts(),
        "idempotency_key": idempotency_key,
    }


def charge_remote(
    base_url: str,
    amount: float,
    rail: str,
    idempotency_key: str,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    own_client = client is None
    client = client or httpx.Client(base_url=base_url.rstrip("/"), timeout=5.0)
    try:
        return _charge_remote(client, amount, rail, idempotency_key)
    finally:
        if own_client:
            client.close()


def _charge_remote(
    client: httpx.Client,
    amount: float,
    rail: str,
    idempotency_key: str,
) -> dict[str, Any]:
    response = client.post(
        "/pay",
        json={
            "cart_total": round(float(amount), 2),
            "payment_route": rail,
            "idempotency_key": idempotency_key,
        },
    )
    response.raise_for_status()
    body = response.json()
    return {
        "success": bool(body.get("success")),
        "error": body.get("error"),
        "auth_id": body.get("order_id") and ("AUTH-" + str(body["order_id"])),
        "order_id": body.get("order_id"),
        "charged": body.get("charged"),
        "currency": body.get("currency") or "HKD",
        "payment_route": body.get("payment_route") or rail,
        "reward_points_earned": body.get("reward_points_earned"),
        "ts": body.get("ts") or _ts(),
        "idempotency_key": idempotency_key,
    }


def charge(
    *,
    amount: float,
    rail: str,
    idempotency_key: str,
    acquirer_url: str = "",
) -> dict[str, Any]:
    if acquirer_url:
        return charge_remote(acquirer_url, amount, rail, idempotency_key)
    return charge_local(amount, rail, idempotency_key)
