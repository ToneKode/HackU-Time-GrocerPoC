"""Shopper profile, orders, and workflow checkpoints.

Purchase history, last purchase, and per-order amounts are reads over `orders`.
`workflow_checkpoints` keeps every step so a crash does not drop the basket.
`monthly_spend` stays the source of truth for money already charged.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from pymysql.err import IntegrityError

from db import connect
from passwords import hash_password, verify_password
from spend_store import SpendStore, current_year_month, money

BENEFIT_KINDS = ("cash", "asiamiles", "membership_points", "loyalty_points")
DEFAULT_RANK = list(BENEFIT_KINDS)
STARTER_METHODS = (
    ("mastercard", "Mox Mastercard", "4242", True),
    ("alipay", "Alipay", "", False),
    ("visa", "ICBC Visa", "1888", False),
)

FAKE_ADDRESS = {
    "label": "Home",
    "line1": "Flat 8, 12/F, Demo Court",
    "line2": "88 Nathan Road",
    "district": "Tsim Sha Tsui",
    "region": "Kowloon",
}


class AccountExists(Exception):
    pass


class NotFound(Exception):
    pass


class BadPayment(Exception):
    pass


def _ts(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _jsonable(value):
    return json.loads(json.dumps(value if value is not None else {}, default=str))


def _last4(value: str) -> str:
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if len(digits) > 4:
        raise BadPayment("Send the route and the last 4 digits, not the card number")
    return digits[-4:]


class ProfileStore:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.spend = SpendStore(database_url)

    def register(
        self,
        email: str,
        password: str,
        name: str,
        phone: str = "",
        marketing: bool = False,
    ) -> dict:
        account_id = str(uuid.uuid4())
        email = email.strip().lower()
        try:
            with connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO accounts (
                            id, email, password_hash, display_name, phone, marketing
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (account_id, email, hash_password(password), name.strip(), phone.strip(), marketing),
                    )
                    cur.execute(
                        """
                        INSERT INTO addresses (
                            account_id, label, line1, line2, district, region, fake, is_default
                        ) VALUES (%s, %s, %s, %s, %s, %s, TRUE, TRUE)
                        """,
                        (
                            account_id,
                            FAKE_ADDRESS["label"],
                            FAKE_ADDRESS["line1"],
                            FAKE_ADDRESS["line2"],
                            FAKE_ADDRESS["district"],
                            FAKE_ADDRESS["region"],
                        ),
                    )
                    for route, label, last4, is_default in STARTER_METHODS:
                        cur.execute(
                            """
                            INSERT INTO payment_methods (
                                id, account_id, route, label, last4, connected, is_default
                            ) VALUES (%s, %s, %s, %s, %s, TRUE, %s)
                            """,
                            ("pm_" + uuid.uuid4().hex[:10], account_id, route, label, last4, is_default),
                        )
                    cur.execute(
                        """
                        INSERT INTO account_preferences (account_id, benefit_rank)
                        VALUES (%s, %s)
                        """,
                        (account_id, json.dumps(DEFAULT_RANK)),
                    )
        except IntegrityError as exc:
            if exc.args and exc.args[0] == 1062:
                raise AccountExists(email) from exc
            raise
        return self.profile(account_id)

    def authenticate(self, email: str, password: str) -> dict | None:
        email = email.strip().lower()
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, password_hash FROM accounts WHERE email = %s",
                    (email,),
                )
                row = cur.fetchone()
        if row is None or not verify_password(password, row["password_hash"]):
            return None
        return self.profile(row["id"])

    def profile(self, account_id: str) -> dict:
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM accounts WHERE id = %s", (account_id,))
                account = cur.fetchone()
                if account is None:
                    raise NotFound(account_id)
                cur.execute(
                    """
                    SELECT id, label, line1, line2, district, region, fake, is_default
                    FROM addresses WHERE account_id = %s
                    ORDER BY is_default DESC, id
                    """,
                    (account_id,),
                )
                addresses = [_address(row) for row in cur.fetchall()]
                cur.execute(
                    """
                    SELECT id, route, label, last4, connected, is_default
                    FROM payment_methods WHERE account_id = %s
                    ORDER BY is_default DESC, created_at
                    """,
                    (account_id,),
                )
                methods = [_payment(row) for row in cur.fetchall()]
                cur.execute(
                    "SELECT benefit_rank FROM account_preferences WHERE account_id = %s",
                    (account_id,),
                )
                pref = cur.fetchone()
                cur.execute(
                    """
                    SELECT kind, amount FROM benefit_balances
                    WHERE account_id = %s ORDER BY kind
                    """,
                    (account_id,),
                )
                balances = [
                    {"kind": row["kind"], "amount": money(row["amount"])}
                    for row in cur.fetchall()
                ]
        spent = self.spend.get(account_id)
        recent = self.list_orders(account_id, limit=8)
        paid = [row for row in recent if row["status"] == "paid"]
        last = paid[0] if paid else self._last_paid(account_id)
        default = next((item for item in methods if item["is_default"] and item["connected"]), None)
        if default is None:
            default = next((item for item in methods if item["connected"]), None)
        return {
            "id": account["id"],
            "email": account["email"],
            "name": account["display_name"],
            "phone": account["phone"],
            "membership": account["membership"],
            "marketing": bool(account["marketing"]),
            "monthly_cap": money(account["monthly_cap"]),
            "per_order_cap": money(account["per_order_cap"]),
            "bulk_ceiling": money(account["bulk_ceiling"]),
            "monthly_spent": spent["spent"],
            "year_month": spent["year_month"],
            "address": addresses[0] if addresses else None,
            "addresses": addresses,
            "payment_methods": methods,
            "benefit_rank": _rank(pref["benefit_rank"] if pref else None),
            "benefit_balances": balances,
            "monthly_remaining": money(money(account["monthly_cap"]) - spent["spent"]),
            "default_payment_route": default["route"] if default else "",
            "last_purchase": last,
            "recent_orders": recent,
        }

    def update_limits(
        self,
        account_id: str,
        *,
        monthly_cap: float | None = None,
        per_order_cap: float | None = None,
        bulk_ceiling: float | None = None,
        membership: str | None = None,
    ) -> dict:
        sets: list[str] = []
        params: list = []
        if monthly_cap is not None:
            sets.append("monthly_cap = %s")
            params.append(money(monthly_cap))
        if per_order_cap is not None:
            sets.append("per_order_cap = %s")
            params.append(money(per_order_cap))
        if bulk_ceiling is not None:
            sets.append("bulk_ceiling = %s")
            params.append(money(bulk_ceiling))
        if membership is not None:
            sets.append("membership = %s")
            params.append(membership.strip() or "standard")
        if not sets:
            return self.profile(account_id)
        sets.append("updated_at = NOW()")
        params.append(account_id)
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE accounts SET {', '.join(sets)} WHERE id = %s",
                    params,
                )
                if cur.rowcount == 0:
                    raise NotFound(account_id)
        return self.profile(account_id)

    def add_payment_method(
        self,
        account_id: str,
        route: str,
        label: str,
        last4: str = "",
        *,
        connected: bool = True,
        is_default: bool = False,
    ) -> dict:
        self._require_account(account_id)
        method_id = "pm_" + uuid.uuid4().hex[:10]
        cleaned = _last4(last4)
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                if is_default:
                    cur.execute(
                        "UPDATE payment_methods SET is_default = FALSE WHERE account_id = %s",
                        (account_id,),
                    )
                cur.execute(
                    """
                    INSERT INTO payment_methods (
                        id, account_id, route, label, last4, connected, is_default
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (method_id, account_id, route.strip(), label.strip(), cleaned, connected, is_default),
                )
        return self.profile(account_id)

    def save_preferences(
        self,
        account_id: str,
        benefit_rank: list[str] | None = None,
        methods: list[dict] | None = None,
    ) -> dict:
        self._require_account(account_id)
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                if benefit_rank is not None:
                    cur.execute(
                        """
                        INSERT INTO account_preferences (account_id, benefit_rank)
                        VALUES (%s, %s) AS new_row
                        ON DUPLICATE KEY UPDATE benefit_rank = new_row.benefit_rank
                        """,
                        (account_id, json.dumps(_rank(benefit_rank))),
                    )
                for method in methods or []:
                    connected = bool(method.get("connected", True))
                    method_id = str(method.get("id") or "").strip()
                    route = str(method.get("route") or "").strip()
                    if method_id:
                        cur.execute(
                            "SELECT id FROM payment_methods WHERE account_id = %s AND id = %s",
                            (account_id, method_id),
                        )
                        if cur.fetchone() is None:
                            raise NotFound(method_id)
                        cur.execute(
                            """
                            UPDATE payment_methods SET connected = %s
                            WHERE account_id = %s AND id = %s
                            """,
                            (connected, account_id, method_id),
                        )
                    elif route:
                        cur.execute(
                            """
                            UPDATE payment_methods SET connected = %s
                            WHERE account_id = %s AND route = %s
                            """,
                            (connected, account_id, route),
                        )
        return self.profile(account_id)

    def record_paid(
        self,
        account_id: str,
        amount: float,
        *,
        currency: str = "HKD",
        merchant: str = "",
        payment_route: str = "",
        payment_id: str | None = None,
        intent: str = "",
        lines: list[dict] | None = None,
        settlement: dict | None = None,
        benefits: list[dict] | None = None,
    ) -> dict:
        """Store a paid order, the month's spend, and the benefits that order earned."""
        if amount <= 0:
            raise ValueError("amount must be > 0")
        self._require_account(account_id)
        key = (payment_id or "").strip() or None
        order_id = "ord_" + uuid.uuid4().hex[:12]
        duplicate = False
        amt = money(amount)
        ym = current_year_month()
        snapshot = _jsonable(
            {
                "intent": intent,
                "settlement": settlement or {},
                "benefits": benefits or [],
            }
        )
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                # Serialize reward and spend writes for settlement retries.
                cur.execute("SELECT id FROM accounts WHERE id = %s FOR UPDATE", (account_id,))
                if cur.fetchone() is None:
                    raise NotFound(account_id)
                if key:
                    cur.execute(
                        """
                        SELECT id FROM orders
                        WHERE account_id = %s AND payment_id = %s AND status = 'paid'
                        LIMIT 1
                        """,
                        (account_id, key),
                    )
                    found = cur.fetchone()
                    if found:
                        order_id = found["id"]
                        duplicate = True
                if not duplicate:
                    cur.execute(
                        """
                        INSERT INTO orders (
                            id, account_id, intent, status, step, amount, currency,
                            merchant, payment_route, payment_id, snapshot
                        ) VALUES (%s, %s, %s, 'paid', 'payment', %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            order_id,
                            account_id,
                            (intent or "approved basket")[:4000],
                            amt,
                            (currency or "HKD")[:3],
                            (merchant or "")[:80],
                            (payment_route or "")[:40],
                            key,
                            json.dumps(snapshot),
                        ),
                    )
                    for line in lines or []:
                        qty = int(line.get("qty") or 1)
                        if qty < 1:
                            continue
                        cur.execute(
                            """
                            INSERT INTO order_lines (
                                order_id, sku, name, merchant, category, qty, unit_price, line_total
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                order_id,
                                str(line.get("sku") or ""),
                                str(line.get("name") or "")[:255],
                                str(line.get("merchant") or "")[:80],
                                str(line.get("category") or "")[:80],
                                qty,
                                money(line.get("unit_price") or 0),
                                money(line.get("line_total") or 0),
                            ),
                        )
                    cur.execute(
                        """
                        INSERT INTO workflow_checkpoints (order_id, step, status, snapshot)
                        VALUES (%s, 'payment', 'paid', %s)
                        """,
                        (order_id, json.dumps(snapshot)),
                    )
                    cur.execute(
                        """
                        INSERT INTO agent_runs (account_id, order_id, intent, status, step, summary)
                        VALUES (%s, %s, %s, 'paid', 'payment', %s)
                        """,
                        (account_id, order_id, intent or "approved basket", f"paid HK${amt:.2f}"),
                    )
                    idem = key or order_id
                    cur.execute(
                        """
                        INSERT INTO spend_ledger
                            (account_id, `year_month`, amount, currency, payment_id, idempotency_key, note)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (account_id, ym, amt, currency or "HKD", key, idem, (intent or "approved basket")[:255]),
                    )
                    cur.execute(
                        """
                        INSERT INTO monthly_spend (account_id, `year_month`, spent, currency)
                        VALUES (%s, %s, %s, %s) AS new_row
                        ON DUPLICATE KEY UPDATE
                          spent = monthly_spend.spent + new_row.spent,
                          updated_at = CURRENT_TIMESTAMP(6)
                        """,
                        (account_id, ym, amt, currency or "HKD"),
                    )
                    for benefit in benefits or []:
                        kind = str(benefit.get("kind") or "")
                        if kind not in BENEFIT_KINDS:
                            continue
                        gained = money(benefit.get("amount") or 0)
                        if gained == 0:
                            continue
                        note = str(benefit.get("detail") or benefit.get("note") or "")[:255]
                        cur.execute(
                            """
                            INSERT INTO benefit_balances (account_id, kind, amount)
                            VALUES (%s, %s, %s) AS new_row
                            ON DUPLICATE KEY UPDATE amount = benefit_balances.amount + new_row.amount
                            """,
                            (account_id, kind, gained),
                        )
                        cur.execute(
                            """
                            INSERT INTO benefit_ledger (account_id, order_id, kind, amount, note)
                            VALUES (%s, %s, %s, %s, %s)
                            """,
                            (account_id, order_id, kind, gained, note),
                        )
        return {
            "order_id": order_id,
            "order": self.get_order(order_id),
            "profile": self.profile(account_id),
            "duplicate": duplicate,
        }

    def open_order(self, account_id: str, intent: str) -> dict:
        self._require_account(account_id)
        order_id = "ord_" + uuid.uuid4().hex[:12]
        snapshot = {"intent": intent, "step": "route_entry"}
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO orders (id, account_id, intent, status, step, snapshot)
                    VALUES (%s, %s, %s, 'drafting', 'route_entry', %s)
                    """,
                    (order_id, account_id, intent, json.dumps(snapshot)),
                )
                cur.execute(
                    """
                    INSERT INTO workflow_checkpoints (order_id, step, status, snapshot)
                    VALUES (%s, 'route_entry', 'drafting', %s)
                    """,
                    (order_id, json.dumps(snapshot)),
                )
                cur.execute(
                    """
                    INSERT INTO agent_runs (account_id, order_id, intent, status, step, summary)
                    VALUES (%s, %s, %s, 'drafting', 'route_entry', %s)
                    """,
                    (account_id, order_id, intent, "Order opened"),
                )
        return self.get_order(order_id)

    def checkpoint(
        self,
        order_id: str,
        *,
        step: str,
        status: str,
        snapshot: dict | None = None,
        amount: float | None = None,
        merchant: str | None = None,
        payment_route: str | None = None,
        payment_id: str | None = None,
        escalation_id: str | None = None,
        lines: list[dict] | None = None,
    ) -> dict:
        body = _jsonable(snapshot or {})
        summary = status if amount is None else f"{status} HK${money(amount):.2f}"
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM orders WHERE id = %s", (order_id,))
                if cur.fetchone() is None:
                    raise NotFound(order_id)
                sets = ["step = %s", "status = %s", "snapshot = %s", "updated_at = NOW()"]
                params: list = [step, status, json.dumps(body)]
                if amount is not None:
                    sets.append("amount = %s")
                    params.append(money(amount))
                if merchant is not None:
                    sets.append("merchant = %s")
                    params.append(merchant)
                if payment_route is not None:
                    sets.append("payment_route = %s")
                    params.append(payment_route)
                if payment_id is not None:
                    sets.append("payment_id = %s")
                    params.append(payment_id)
                if escalation_id is not None:
                    sets.append("escalation_id = %s")
                    params.append(escalation_id)
                params.append(order_id)
                cur.execute(f"UPDATE orders SET {', '.join(sets)} WHERE id = %s", params)
                cur.execute(
                    """
                    INSERT INTO workflow_checkpoints (order_id, step, status, snapshot)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (order_id, step, status, json.dumps(body)),
                )
                if lines is not None:
                    cur.execute("DELETE FROM order_lines WHERE order_id = %s", (order_id,))
                    for line in lines:
                        qty = int(line.get("qty") or 1)
                        if qty < 1:
                            continue
                        cur.execute(
                            """
                            INSERT INTO order_lines (
                                order_id, sku, name, merchant, category, qty, unit_price, line_total
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                order_id,
                                str(line.get("sku") or ""),
                                str(line.get("name") or ""),
                                str(line.get("merchant") or ""),
                                str(line.get("category") or ""),
                                qty,
                                money(line.get("unit_price") or 0),
                                money(line.get("line_total") or 0),
                            ),
                        )
                cur.execute(
                    """
                    UPDATE agent_runs
                    SET status = %s, step = %s, summary = %s, updated_at = NOW()
                    WHERE order_id = %s
                    """,
                    (status, step, summary, order_id),
                )
        return self.get_order(order_id)

    def get_order(self, order_id: str) -> dict:
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
                row = cur.fetchone()
                if row is None:
                    raise NotFound(order_id)
                cur.execute(
                    """
                    SELECT sku, name, merchant, category, qty, unit_price, line_total
                    FROM order_lines WHERE order_id = %s ORDER BY id
                    """,
                    (order_id,),
                )
                lines = [_line(item) for item in cur.fetchall()]
                cur.execute(
                    """
                    SELECT step, status, created_at FROM workflow_checkpoints
                    WHERE order_id = %s ORDER BY id
                    """,
                    (order_id,),
                )
                steps = [
                    {"step": item["step"], "status": item["status"], "created_at": _ts(item["created_at"])}
                    for item in cur.fetchall()
                ]
        body = _order(row)
        body["lines"] = lines
        body["checkpoints"] = steps
        return body

    def list_orders(self, account_id: str, *, status: str | None = None, limit: int = 20) -> list[dict]:
        self._require_account(account_id)
        limit = max(1, min(int(limit), 50))
        sql = """
            SELECT id, account_id, intent, status, step, amount, currency, merchant,
                   payment_route, payment_id, escalation_id, created_at, updated_at
            FROM orders WHERE account_id = %s
        """
        params: list = [account_id]
        if status:
            sql += " AND status = %s"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [_order(row, include_snapshot=False) for row in rows]

    def add_chat(self, account_id: str, role: str, content: str, order_id: str | None = None) -> dict:
        self._require_account(account_id)
        if role not in {"user", "assistant"}:
            raise ValueError("role must be user or assistant")
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO chat_messages (account_id, order_id, role, content)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (account_id, order_id, role, content),
                )
                cur.execute(
                    """
                    SELECT id, account_id, order_id, role, content, created_at
                    FROM chat_messages WHERE id = %s
                    """,
                    (cur.lastrowid,),
                )
                row = cur.fetchone()
        return _chat(row)

    def list_chat(self, account_id: str, limit: int = 50) -> list[dict]:
        self._require_account(account_id)
        limit = max(1, min(int(limit), 200))
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, account_id, order_id, role, content, created_at
                    FROM (
                        SELECT * FROM chat_messages
                        WHERE account_id = %s
                        ORDER BY created_at DESC, id DESC
                        LIMIT %s
                    ) recent
                    ORDER BY created_at, id
                    """,
                    (account_id, limit),
                )
                rows = cur.fetchall()
        return [_chat(row) for row in rows]

    def clear_chat(self, account_id: str) -> int:
        self._require_account(account_id)
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM chat_messages WHERE account_id = %s", (account_id,))
                return cur.rowcount

    def add_task(self, account_id: str, intent: str, cadence: str = "monthly") -> dict:
        self._require_account(account_id)
        task_id = "task_" + uuid.uuid4().hex[:10]
        cadence = (cadence or "monthly").strip().lower()
        if cadence not in {"weekly", "monthly"}:
            cadence = "monthly"
        next_run = datetime.now(timezone.utc) + (timedelta(days=7) if cadence == "weekly" else timedelta(days=30))
        next_run = next_run.replace(tzinfo=None)
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO recurrent_tasks (id, account_id, intent, cadence, next_run, active)
                    VALUES (%s, %s, %s, %s, %s, TRUE)
                    """,
                    (task_id, account_id, intent.strip(), cadence, next_run),
                )
                cur.execute(
                    """
                    SELECT id, account_id, intent, cadence, next_run, active, last_order_id, created_at
                    FROM recurrent_tasks WHERE id = %s
                    """,
                    (task_id,),
                )
                row = cur.fetchone()
        return _task(row)

    def list_tasks(self, account_id: str) -> list[dict]:
        self._require_account(account_id)
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, account_id, intent, cadence, next_run, active, last_order_id, created_at
                    FROM recurrent_tasks WHERE account_id = %s
                    ORDER BY created_at DESC
                    """,
                    (account_id,),
                )
                rows = cur.fetchall()
        return [_task(row) for row in rows]

    def list_agent_history(self, account_id: str, limit: int = 20) -> list[dict]:
        self._require_account(account_id)
        limit = max(1, min(int(limit), 50))
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, account_id, order_id, intent, status, step, summary, created_at, updated_at
                    FROM agent_runs WHERE account_id = %s
                    ORDER BY created_at DESC LIMIT %s
                    """,
                    (account_id, limit),
                )
                rows = cur.fetchall()
        return [
            {
                "id": row["id"],
                "account_id": row["account_id"],
                "order_id": row["order_id"],
                "intent": row["intent"],
                "status": row["status"],
                "step": row["step"],
                "summary": row["summary"],
                "created_at": _ts(row["created_at"]),
                "updated_at": _ts(row["updated_at"]),
            }
            for row in rows
        ]

    def _require_account(self, account_id: str) -> None:
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM accounts WHERE id = %s", (account_id,))
                if cur.fetchone() is None:
                    raise NotFound(account_id)

    def _last_paid(self, account_id: str) -> dict | None:
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, account_id, intent, status, step, amount, currency, merchant,
                           payment_route, payment_id, escalation_id, created_at, updated_at
                    FROM orders
                    WHERE account_id = %s AND status = 'paid'
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (account_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return _order(row, include_snapshot=False)


def _rank(value) -> list[str]:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = None
    cleaned: list[str] = []
    if isinstance(value, list):
        for item in value:
            kind = str(item)
            if kind in BENEFIT_KINDS and kind not in cleaned:
                cleaned.append(kind)
    else:
        return list(DEFAULT_RANK)
    for kind in DEFAULT_RANK:
        if kind not in cleaned:
            cleaned.append(kind)
    return cleaned


def _address(row: dict) -> dict:
    return {
        "id": row["id"],
        "label": row["label"],
        "line1": row["line1"],
        "line2": row["line2"],
        "district": row["district"],
        "region": row["region"],
        "fake": bool(row["fake"]),
        "is_default": bool(row["is_default"]),
    }


def _payment(row: dict) -> dict:
    return {
        "id": row["id"],
        "route": row["route"],
        "label": row["label"],
        "last4": row["last4"],
        "connected": bool(row["connected"]),
        "is_default": bool(row["is_default"]),
    }


def _line(row: dict) -> dict:
    return {
        "sku": row["sku"],
        "name": row["name"],
        "merchant": row["merchant"],
        "category": row["category"],
        "qty": int(row["qty"]),
        "unit_price": money(row["unit_price"]),
        "line_total": money(row["line_total"]),
    }


def _snapshot(value):
    if value is None or value == "":
        return {}
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    return value


def _order(row: dict, *, include_snapshot: bool = True) -> dict:
    body = {
        "id": row["id"],
        "account_id": row["account_id"],
        "intent": row["intent"],
        "status": row["status"],
        "step": row["step"],
        "amount": None if row["amount"] is None else money(row["amount"]),
        "currency": (row["currency"] or "HKD").strip(),
        "merchant": row["merchant"],
        "payment_route": row["payment_route"],
        "payment_id": row["payment_id"],
        "escalation_id": row["escalation_id"],
        "created_at": _ts(row["created_at"]),
        "updated_at": _ts(row["updated_at"]),
    }
    if include_snapshot:
        body["snapshot"] = _snapshot(row.get("snapshot"))
    return body


def _chat(row: dict) -> dict:
    return {
        "id": row["id"],
        "account_id": row["account_id"],
        "order_id": row["order_id"],
        "role": row["role"],
        "content": row["content"],
        "created_at": _ts(row["created_at"]),
    }


def _task(row: dict) -> dict:
    return {
        "id": row["id"],
        "account_id": row["account_id"],
        "intent": row["intent"],
        "cadence": row["cadence"],
        "next_run": _ts(row["next_run"]),
        "active": bool(row["active"]),
        "last_order_id": row["last_order_id"],
        "created_at": _ts(row["created_at"]),
    }
