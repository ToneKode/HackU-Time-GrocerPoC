"""Read-only shopper dashboard: order history, spend by category, lifetime
spend, and benefits earned (by kind and by payment method).

Sources (all in MySQL):
  orders (status='paid')     lifetime spend, order history, payment route
  order_lines                spend by category; empty category falls back to
                             catalog_products.category for the same SKU
  benefit_ledger             benefits earned per order and kind (written by
                             /accounts/{id}/orders/settle)
  orders.snapshot.settlement per-merchant tender, used to split benefits by
                             method when one order paid several merchants
  payment_methods            label and last4 for each route
  payments                   payment service rows, when it runs on MySQL
"""
from __future__ import annotations

import json

from db import connect
from profile_store import BENEFIT_KINDS, NotFound, _snapshot, _ts
from spend_store import money

UNCATEGORISED = "Uncategorised"


def _num(value) -> float:
    return money(value or 0)


class DashboardStore:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def dashboard(self, account_id: str, *, recent: int = 20) -> dict:
        recent = max(1, min(int(recent), 100))
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, display_name, created_at FROM accounts WHERE id = %s", (account_id,))
                account = cur.fetchone()
                if account is None:
                    raise NotFound(account_id)
                cur.execute(
                    """
                    SELECT id, intent, status, amount, currency, merchant, payment_route,
                           payment_id, snapshot, created_at
                    FROM orders WHERE account_id = %s AND status = 'paid'
                    ORDER BY created_at DESC, id
                    """,
                    (account_id,),
                )
                orders = cur.fetchall()
                cur.execute(
                    "SELECT status, COUNT(*) AS n FROM orders WHERE account_id = %s GROUP BY status",
                    (account_id,),
                )
                by_status = {row["status"]: int(row["n"]) for row in cur.fetchall()}
                cur.execute(
                    """
                    SELECT ol.order_id, ol.sku, ol.name, ol.merchant, ol.category, ol.qty,
                           ol.unit_price, ol.line_total, cp.category AS catalog_category
                    FROM order_lines ol
                    JOIN orders o ON o.id = ol.order_id
                    LEFT JOIN catalog_products cp ON cp.id = ol.sku
                    WHERE o.account_id = %s AND o.status = 'paid'
                    ORDER BY ol.id
                    """,
                    (account_id,),
                )
                lines = cur.fetchall()
                cur.execute(
                    """
                    SELECT order_id, kind, amount, note, created_at
                    FROM benefit_ledger WHERE account_id = %s ORDER BY id
                    """,
                    (account_id,),
                )
                ledger = cur.fetchall()
                cur.execute(
                    "SELECT route, label, last4, connected, is_default FROM payment_methods WHERE account_id = %s",
                    (account_id,),
                )
                methods = cur.fetchall()
                cur.execute(
                    "SELECT COALESCE(SUM(amount), 0) AS total FROM spend_ledger WHERE account_id = %s",
                    (account_id,),
                )
                spend_ledger_total = _num(cur.fetchone()["total"])
                payments = None
                try:
                    cur.execute(
                        """
                        SELECT status, COUNT(*) AS n, COALESCE(SUM(amount), 0) AS total
                        FROM payments WHERE account_id = %s GROUP BY status
                        """,
                        (account_id,),
                    )
                    payments = {
                        row["status"]: {"count": int(row["n"]), "amount": _num(row["total"])}
                        for row in cur.fetchall()
                    }
                except Exception:
                    payments = None

        labels = {}
        for row in methods:
            labels.setdefault(row["route"], {"label": row["label"], "last4": row["last4"]})

        def method(route: str) -> dict:
            known = labels.get(route) or {}
            return {"route": route or "", "label": known.get("label") or route or "unknown", "last4": known.get("last4") or ""}

        lines_by_order: dict[str, list[dict]] = {}
        categories: dict[str, dict] = {}
        for row in lines:
            category = row["category"] or row["catalog_category"] or UNCATEGORISED
            total = _num(row["line_total"])
            item = {
                "sku": row["sku"],
                "name": row["name"],
                "merchant": row["merchant"],
                "category": category,
                "qty": int(row["qty"]),
                "unit_price": _num(row["unit_price"]),
                "line_total": total,
            }
            lines_by_order.setdefault(row["order_id"], []).append(item)
            slot = categories.setdefault(category, {"category": category, "amount": 0.0, "items": 0, "orders": set()})
            slot["amount"] += total
            slot["items"] += item["qty"]
            slot["orders"].add(row["order_id"])
        goods_total = money(sum(slot["amount"] for slot in categories.values()))
        pie = []
        for slot in sorted(categories.values(), key=lambda s: -s["amount"]):
            pie.append(
                {
                    "category": slot["category"],
                    "amount": money(slot["amount"]),
                    "share": round(slot["amount"] / goods_total, 4) if goods_total else 0,
                    "items": slot["items"],
                    "orders": len(slot["orders"]),
                }
            )

        ledger_by_order: dict[str, list[dict]] = {}
        totals = {kind: 0.0 for kind in BENEFIT_KINDS}
        for row in ledger:
            amount = _num(row["amount"])
            totals[row["kind"]] = totals.get(row["kind"], 0.0) + amount
            ledger_by_order.setdefault(row["order_id"] or "", []).append(
                {"kind": row["kind"], "amount": amount, "note": row["note"]}
            )

        by_method: dict[tuple[str, str], float] = {}
        history = []
        lifetime = 0.0
        months: dict[str, float] = {}
        for row in orders:
            amount = _num(row["amount"])
            lifetime += amount
            created = _ts(row["created_at"])
            month = (created or "")[:7]
            months[month] = months.get(month, 0.0) + amount
            snapshot = _snapshot(row.get("snapshot"))
            settlement = snapshot.get("settlement") if isinstance(snapshot, dict) else {}
            settlement = settlement if isinstance(settlement, dict) else {}
            gifts = [line for line in settlement.get("lines", []) if line.get("is_gift")]
            order_lines = lines_by_order.get(row["id"], [])
            for line in order_lines:
                if line["unit_price"] == 0 and any(gift["sku"] == line["sku"] for gift in gifts):
                    line["is_gift"] = True
            earned = ledger_by_order.get(row["id"], [])
            groups = [
                group for group in settlement.get("merchants") or []
                if isinstance(group, dict) and (group.get("payment") or {}).get("route")
            ]
            routes = {group["payment"]["route"] for group in groups}
            tenders = []
            if groups:
                # Each merchant's verified capture carries its own tender and rewards.
                for group in groups:
                    route = group["payment"]["route"]
                    tenders.append({**method(route), "amount": _num(group["payment"].get("amount")), "merchant": group.get("merchant")})
                    for benefit in group.get("benefits") or []:
                        key = (route, str(benefit.get("kind")))
                        by_method[key] = by_method.get(key, 0.0) + _num(benefit.get("amount"))
            else:
                route = row["payment_route"] or (next(iter(routes)) if routes else "")
                tenders.append({**method(route), "amount": amount, "merchant": row["merchant"]})
                for benefit in earned:
                    key = (route, benefit["kind"])
                    by_method[key] = by_method.get(key, 0.0) + benefit["amount"]
            history.append(
                {
                    "id": row["id"],
                    "created_at": created,
                    "intent": row["intent"],
                    "amount": amount,
                    "currency": (row["currency"] or "HKD").strip(),
                    "merchant": row["merchant"],
                    "payment_id": row["payment_id"],
                    "payment_order_id": settlement.get("payment_order_id"),
                    "tenders": tenders,
                    "benefits": earned,
                    "items": sum(line["qty"] for line in order_lines),
                    "lines": order_lines,
                    "gifts": [line for line in settlement.get("lines", []) if line.get("is_gift")],
                    "goods": money(sum(line["line_total"] for line in order_lines)),
                    "shipping": _num(settlement.get("shipping_fee")),
                    "discount": _num(settlement.get("discount")),
                }
            )

        methods_out: dict[str, dict] = {}
        for (route, kind), amount in by_method.items():
            entry = methods_out.setdefault(route, {**method(route), "benefits": {}})
            entry["benefits"][kind] = money(entry["benefits"].get(kind, 0.0) + amount)
        lifetime = money(lifetime)
        return {
            "account_id": account_id,
            "name": account["display_name"],
            "member_since": _ts(account["created_at"]),
            "lifetime_spent": lifetime,
            "currency": "HKD",
            "orders_paid": len(orders),
            "average_order": money(lifetime / len(orders)) if orders else 0,
            "first_order_at": history[-1]["created_at"] if history else None,
            "last_order_at": history[0]["created_at"] if history else None,
            "spend_ledger_total": spend_ledger_total,
            "orders_by_status": by_status,
            "monthly": [{"month": key, "amount": money(value)} for key, value in sorted(months.items())],
            "categories": pie,
            "goods_total": goods_total,
            "fees_and_offers": money(lifetime - goods_total),
            "benefits": {
                "totals": {kind: money(value) for kind, value in totals.items()},
                "by_method": sorted(methods_out.values(), key=lambda item: item["route"]),
                "entries": len(ledger),
            },
            "payments": payments,
            "orders": history[:recent],
        }
