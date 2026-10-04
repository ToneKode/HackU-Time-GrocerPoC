"""Mall stand-in. Reads the JSON files in this folder until person 4's server is up."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def money(value: float) -> float:
    return round(float(value), 2)


class FileMall:
    def __init__(self, folder: Path = ROOT, products: list[dict] | None = None):
        if products is None:
            self.products = json.loads((folder / "products.json").read_text(encoding="utf-8"))
        else:
            self.products = products
        self.merchants = json.loads((folder / "merchants.json").read_text(encoding="utf-8"))
        self.rules = json.loads((folder / "rules.json").read_text(encoding="utf-8"))
        self._by_sku = {item["id"]: item for item in self.products}
        self._paid: dict[str, dict] = {}

    def search(self, query: str) -> list[dict]:
        needle = query.casefold()
        if not needle:
            return list(self.products)
        found = []
        for item in self.products:
            haystack = " ".join(
                [item["name"], item["merchant"], item["category"], item.get("sell_point", "")]
            ).casefold()
            if needle in haystack:
                found.append(item)
        return found

    def product(self, sku: str) -> dict:
        try:
            return self._by_sku[sku]
        except KeyError as exc:
            raise LookupError(f"Unknown SKU: {sku}") from exc

    def cart(self, sku: str, qty: int) -> dict:
        return self.cart_lines([{"sku": sku, "qty": qty}])

    def cart_lines(self, items: list[dict]) -> dict:
        line_items = []
        for item in items:
            product = self.product(item["sku"])
            unit = money(product["price"])
            qty = int(item["qty"])
            line_items.append(
                {
                    "sku": product["id"],
                    "name": product["name"],
                    "merchant": product["merchant"],
                    "category": product["category"],
                    "unit_price": unit,
                    "qty": qty,
                    "line_total": money(unit * qty),
                }
            )
        subtotal = money(sum(line["line_total"] for line in line_items))
        shipping_fee = (
            0.0
            if subtotal >= self.rules["free_shipping_threshold"]
            else money(self.rules["shipping_fee_below_threshold"])
        )
        tax = money(self.rules["tax"])
        return {
            "line_items": line_items,
            "subtotal": subtotal,
            "shipping_fee": shipping_fee,
            "tax": tax,
            "total_landed_cost": money(subtotal + shipping_fee + tax),
            "currency": self.rules["currency"],
            "free_shipping_threshold": self.rules["free_shipping_threshold"],
        }

    def pay(self, cart_total: float, idempotency_key: str, payment_route: str = "mastercard") -> dict:
        if idempotency_key in self._paid:
            return self._paid[idempotency_key]
        total = money(cart_total)
        if total == money(self.rules["decline_cart_total"]):
            result = {
                "success": False,
                "order_id": None,
                "charged": None,
                "currency": None,
                "payment_route": None,
                "ts": None,
                "error": self.rules["decline_error"],
            }
        else:
            result = {
                "success": True,
                "order_id": "ORD-" + uuid.uuid4().hex[:8],
                "charged": total,
                "currency": self.rules["currency"],
                "payment_route": payment_route,
                "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "error": None,
            }
        self._paid[idempotency_key] = result
        return result
