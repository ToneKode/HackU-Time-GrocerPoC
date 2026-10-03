"""HTTP calls person 1 is allowed to make.

The mall is person 4. Policy, escalation, and the ledger are person 2.
If person 2 is down, policy and escalation fall back to the local rules
so POST /agent/intent can still answer the frontend.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from policy_rules import TTL_SECONDS, decide

PUBLIC_ESCALATION_KEYS = (
    "escalation_id",
    "status",
    "ttl_seconds",
    "expires_at",
    "remaining_seconds",
    "amount",
    "currency",
    "merchant",
    "sku",
    "reason",
)


def zulu(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def policy_snapshot(result: dict) -> dict:
    return {
        "status": result["status"],
        "rule": result.get("rule") or "",
        "reason": result["reason"],
        "amount": result["amount"],
        "currency": result.get("currency", "HKD"),
        "monthly_spent": result["monthly_spent"],
        "monthly_remaining": result["monthly_remaining"],
        "per_transaction_cap": result["per_transaction_cap"],
        "monthly_cap": result["monthly_cap"],
        "bulk_ceiling": result["bulk_ceiling"],
    }


def engine_thought(result: dict) -> str:
    snap = policy_snapshot(result)
    return (
        f"Policy engine result: status {snap['status']}, rule {snap['rule']}, "
        f"reason {snap['reason']}, amount HK${snap['amount']:.2f}, "
        f"monthly_remaining HK${snap['monthly_remaining']:.2f}, "
        f"caps {snap['per_transaction_cap']}/{snap['bulk_ceiling']}/{snap['monthly_cap']}."
    )


def _policy_event(reason: str, result: dict) -> dict:
    return {
        "event": "POLICY_CHECK",
        "status": result["status"],
        "reason": reason,
        "thought": engine_thought(result),
        "result": policy_snapshot(result),
    }


def public_escalation(record: dict) -> dict:
    return {key: record[key] for key in PUBLIC_ESCALATION_KEYS}


class MallClient:
    def __init__(self, base_url: str = "http://localhost:8000", http: httpx.Client | None = None):
        self.http = http or httpx.Client(base_url=base_url.rstrip("/"), timeout=5.0)

    def search(self, query: str) -> list[dict]:
        response = self.http.get("/products", params={"q": query})
        response.raise_for_status()
        body = response.json()
        if isinstance(body, list):
            return body
        return list(body.get("products", []))

    def product(self, sku: str) -> dict:
        response = self.http.get(f"/products/{sku}")
        response.raise_for_status()
        return response.json()

    def cart(self, sku: str, qty: int, payment_route: str | None = None) -> dict:
        return self.cart_lines([{"sku": sku, "qty": qty}], payment_route=payment_route)

    def cart_lines(self, items: list[dict], payment_route: str | None = None) -> dict:
        payload: dict[str, Any] = {
            "items": [{"sku": item["sku"], "qty": int(item["qty"])} for item in items],
        }
        if payment_route:
            payload["payment_route"] = payment_route
        response = self.http.post(
            "/cart",
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    def pay(self, cart_total: float, idempotency_key: str, payment_route: str = "mastercard") -> dict:
        response = self.http.post(
            "/pay",
            json={
                "cart_total": cart_total,
                "payment_route": payment_route,
                "idempotency_key": idempotency_key,
            },
        )
        response.raise_for_status()
        body = response.json()
        return {
            "success": bool(body.get("success")),
            "order_id": body.get("order_id"),
            "charged": body.get("charged"),
            "currency": body.get("currency"),
            "payment_route": body.get("payment_route"),
            "ts": body.get("ts"),
            "error": body.get("error"),
        }


class PolicyClient:
    def __init__(
        self,
        base_url: str = "http://localhost:8001",
        http: httpx.Client | None = None,
        offline: bool = False,
    ):
        self.offline = offline
        self.http = http or httpx.Client(base_url=base_url.rstrip("/"), timeout=0.4)
        self.memory: dict[str, dict] = {}

    def check(
        self,
        merchant: str,
        category: str,
        amount: float,
        monthly_spent: float,
        sku: str = "",
        qty: int = 1,
    ) -> dict:
        remote = self._post(
            "/check_policy",
            {
                "merchant": merchant,
                "category": category,
                "amount": amount,
                "currency": "HKD",
                "sku": sku,
                "qty": qty,
                "monthly_spent": monthly_spent,
            },
        )
        if remote and remote.get("status") in {"PASS", "ESCALATE", "HALT"} and remote.get("reason"):
            filled = decide(merchant, category, amount, monthly_spent)
            filled.update({key: remote[key] for key in filled if key in remote})
            return filled
        return decide(merchant, category, amount, monthly_spent)

    def check_lines(self, lines: list[dict], amount: float, monthly_spent: float) -> tuple[dict, list[dict]]:
        """Judge every line, then the landed total. Each call becomes one audit row."""
        events = []
        halted = None
        for index, line in enumerate(lines, start=1):
            result = self.check(
                merchant=line["merchant"],
                category=line["category"],
                amount=line["line_total"],
                monthly_spent=monthly_spent,
                sku=line["sku"],
                qty=int(line["qty"]),
            )
            events.append(_policy_event(f"line {index} {line['sku']} {line['merchant']}: {result['reason']}", result))
            if halted is None and result.get("rule") in {"category_blacklisted", "merchant_blacklisted", "merchant_not_whitelisted"}:
                halted = dict(result)
                halted["amount"] = round(float(amount), 2)
        if halted is not None:
            return halted, events
        categories = {line["category"] for line in lines}
        merchants = {line["merchant"] for line in lines}
        # Port 8001 rejects a blank category. A blocked line already returned above.
        category = next(iter(categories))
        merchant = merchants.pop() if len(merchants) == 1 else lines[0]["merchant"]
        total = self.check(
            merchant=merchant,
            category=category,
            amount=amount,
            monthly_spent=monthly_spent,
            sku=lines[0]["sku"],
            qty=1,
        )
        landed = f"{round(float(amount), 2):.2f}"
        events.append(_policy_event(f"basket landed {landed}: {total['reason']}", total))
        return total, events

    def create_escalation(self, draft: dict) -> dict:
        escalation_id = "esc_" + uuid.uuid4().hex[:8]
        expires = datetime.now(timezone.utc) + timedelta(seconds=TTL_SECONDS)
        record = {
            **draft,
            "escalation_id": escalation_id,
            "status": "PENDING",
            "ttl_seconds": TTL_SECONDS,
            "expires_at": zulu(expires),
            "remaining_seconds": TTL_SECONDS,
            "_expires_at": expires.isoformat(),
        }
        remote = self._post(
            "/create_escalation",
            {
                "amount": record["amount"],
                "currency": record["currency"],
                "merchant": record["merchant"],
                "category": record.get("category") or (record.get("product") or {}).get("category") or "",
                "sku": record["sku"],
                "qty": int(draft.get("qty") or 1),
                "reason": record["reason"],
                "monthly_spent": float(record.get("monthly_spent") or 0),
            },
        )
        if remote and remote.get("escalation_id"):
            record["escalation_id"] = remote["escalation_id"]
            for key in PUBLIC_ESCALATION_KEYS:
                if key in remote:
                    record[key] = remote[key]
        self.memory[record["escalation_id"]] = record
        return public_escalation(record)

    def get_escalation(self, escalation_id: str) -> dict | None:
        remote = self._get(f"/escalations/{escalation_id}")
        local = self.memory.get(escalation_id)
        if remote is None and local is None:
            return None
        record = dict(local or {})
        if remote:
            record.update(remote)
        self._refresh_ttl(record)
        if escalation_id in self.memory:
            self.memory[escalation_id].update(record)
        return record

    def log_event(self, event: str, status: str, reason: str) -> None:
        self._post("/log_event", {"event": event, "status": status, "reason": reason})

    def _refresh_ttl(self, record: dict) -> None:
        raw = record.get("_expires_at") or record.get("expires_at")
        if not raw or record.get("status") != "PENDING":
            return
        expires = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        remaining = int((expires - datetime.now(timezone.utc)).total_seconds())
        record["remaining_seconds"] = max(0, remaining)
        if remaining <= 0:
            record["status"] = "EXPIRED"
            record["remaining_seconds"] = 0

    def _post(self, path: str, payload: dict) -> dict | None:
        return self._request("POST", path, payload)

    def _get(self, path: str) -> dict | None:
        return self._request("GET", path, None)

    def _request(self, method: str, path: str, payload: dict | None) -> Any:
        if self.offline:
            return None
        try:
            response = self.http.request(method, path, json=payload)
        except httpx.HTTPError:
            self.offline = True
            return None
        if response.status_code >= 400:
            return None
        body = response.json()
        return body if isinstance(body, dict) else None


class SpendClient:
    """Monthly spend from persistance :8003. Falls back silently when offline."""

    def __init__(
        self,
        base_url: str = "http://localhost:8003",
        http: httpx.Client | None = None,
        account_id: str = "demo",
        offline: bool = False,
    ):
        self.offline = offline
        self.account_id = account_id
        self.http = http or httpx.Client(base_url=base_url.rstrip("/"), timeout=0.5)

    def get_monthly_spent(self, account_id: str | None = None) -> float | None:
        account = account_id or self.account_id
        body = self._request("GET", f"/spend/{account}", None)
        if body is None or "spent" not in body:
            return None
        return float(body["spent"])

    def record_payment(
        self,
        amount: float,
        *,
        account_id: str | None = None,
        payment_id: str | None = None,
        idempotency_key: str | None = None,
        note: str = "",
    ) -> dict | None:
        if amount <= 0:
            return None
        return self._request(
            "POST",
            "/spend",
            {
                "account_id": account_id or self.account_id,
                "amount": amount,
                "currency": "HKD",
                "payment_id": payment_id,
                "idempotency_key": idempotency_key,
                "note": note,
            },
        )

    def _request(self, method: str, path: str, payload: dict | None) -> Any:
        if self.offline:
            return None
        try:
            response = self.http.request(method, path, json=payload)
        except httpx.HTTPError:
            self.offline = True
            return None
        if response.status_code >= 400:
            return None
        body = response.json()
        return body if isinstance(body, dict) else None


class PaymentClient:
    """Agentic payment control loop on :8004. Falls back to None when offline."""

    def __init__(
        self,
        base_url: str = "http://localhost:8004",
        http: httpx.Client | None = None,
        offline: bool = False,
    ):
        self.offline = offline
        self.http = http or httpx.Client(base_url=base_url.rstrip("/"), timeout=2.0)

    def draft(
        self,
        *,
        amount: float,
        merchant: str,
        account_id: str = "demo",
        intent: str = "",
        sku: str = "",
        qty: int = 1,
        rail: str | None = None,
    ) -> dict | None:
        return self._request(
            "POST",
            "/payment/draft",
            {
                "account_id": account_id,
                "amount": amount,
                "currency": "HKD",
                "merchant": merchant,
                "intent": intent,
                "sku": sku,
                "qty": qty,
                "rail": rail,
            },
        )

    def authorize(
        self,
        payment_id: str,
        idempotency_key: str | None = None,
        step_up_confirmed: bool = False,
    ) -> dict | None:
        return self._request(
            "POST",
            "/payment/authorize",
            {
                "payment_id": payment_id,
                "idempotency_key": idempotency_key,
                "step_up_confirmed": step_up_confirmed,
            },
        )

    def charge(
        self,
        *,
        amount: float,
        merchant: str,
        account_id: str,
        intent: str,
        sku: str,
        qty: int,
        rail: str,
        idempotency_key: str,
    ) -> dict | None:
        """Draft + authorize. Returns a mall-shaped payment dict or None if offline."""
        draft = self.draft(
            amount=amount,
            merchant=merchant,
            account_id=account_id,
            intent=intent,
            sku=sku,
            qty=qty,
            rail=rail,
        )
        if not draft or not draft.get("payment_id"):
            return None
        result = self.authorize(draft["payment_id"], idempotency_key=idempotency_key)
        if result is None:
            return None
        ok = result.get("status") == "CAPTURED"
        return {
            "success": ok,
            "order_id": result.get("order_id"),
            "charged": result.get("charged") if ok else None,
            "currency": result.get("currency") or "HKD",
            "payment_route": result.get("rail") or rail,
            "ts": result.get("rail_ts") or result.get("updated_at"),
            "error": result.get("error"),
            "payment_id": result.get("payment_id"),
            "receipt_id": result.get("receipt_id"),
            "auth_id": result.get("auth_id"),
        }

    def _request(self, method: str, path: str, payload: dict | None) -> Any:
        if self.offline:
            return None
        try:
            response = self.http.request(method, path, json=payload)
        except httpx.HTTPError:
            self.offline = True
            return None
        if response.status_code >= 400:
            return None
        body = response.json()
        return body if isinstance(body, dict) else None
