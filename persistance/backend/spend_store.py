"""Monthly spend tracked in MySQL.

Person 2's policy engine still accepts caller-supplied monthly_spent.
When the agent (or UI) is wired to this store, GET /spend becomes the source of truth.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import connect

TWOPLACES = Decimal("0.01")


def current_year_month(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y-%m")


def money(value) -> float:
    return float(Decimal(str(value)).quantize(TWOPLACES, rounding=ROUND_HALF_UP))


class SpendStore:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def get(self, account_id: str, year_month: str | None = None) -> dict:
        ym = year_month or current_year_month()
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT account_id, `year_month`, spent, currency, updated_at "
                    "FROM monthly_spend WHERE account_id = %s AND `year_month` = %s",
                    (account_id, ym),
                )
                row = cur.fetchone()
        if not row:
            return {
                "account_id": account_id,
                "year_month": ym,
                "spent": 0.0,
                "currency": "HKD",
                "updated_at": None,
            }
        return {
            "account_id": row["account_id"],
            "year_month": str(row["year_month"]).strip(),
            "spent": money(row["spent"]),
            "currency": str(row["currency"]).strip(),
            "updated_at": row["updated_at"].strftime("%Y-%m-%dT%H:%M:%SZ")
            if row["updated_at"]
            else None,
        }

    def record(
        self,
        account_id: str,
        amount: float,
        *,
        currency: str = "HKD",
        year_month: str | None = None,
        payment_id: str | None = None,
        idempotency_key: str | None = None,
        note: str = "",
    ) -> dict:
        if amount <= 0:
            raise ValueError("amount must be > 0")
        ym = year_month or current_year_month()
        amt = money(amount)
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                if idempotency_key:
                    cur.execute(
                        "SELECT id FROM spend_ledger "
                        "WHERE account_id = %s AND idempotency_key = %s",
                        (account_id, idempotency_key),
                    )
                    if cur.fetchone():
                        conn.commit()
                        return {**self.get(account_id, ym), "duplicate": True}

                cur.execute(
                    """
                    INSERT INTO spend_ledger
                        (account_id, `year_month`, amount, currency, payment_id,
                         idempotency_key, note)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (account_id, ym, amt, currency, payment_id, idempotency_key, note),
                )
                cur.execute(
                    """
                    INSERT INTO monthly_spend (account_id, `year_month`, spent, currency)
                    VALUES (%s, %s, %s, %s) AS new_row
                    ON DUPLICATE KEY UPDATE
                      spent = monthly_spend.spent + new_row.spent,
                      updated_at = CURRENT_TIMESTAMP(6)
                    """,
                    (account_id, ym, amt, currency),
                )
                cur.execute(
                    "SELECT account_id, `year_month`, spent, currency, updated_at "
                    "FROM monthly_spend WHERE account_id = %s AND `year_month` = %s",
                    (account_id, ym),
                )
                row = cur.fetchone()
            conn.commit()
        return {
            "account_id": row["account_id"],
            "year_month": str(row["year_month"]).strip(),
            "spent": money(row["spent"]),
            "currency": str(row["currency"]).strip(),
            "updated_at": row["updated_at"].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "added": amt,
            "duplicate": False,
        }

    def reset(self, account_id: str | None = None) -> None:
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                if account_id:
                    cur.execute(
                        "DELETE FROM spend_ledger WHERE account_id = %s", (account_id,)
                    )
                    cur.execute(
                        "DELETE FROM monthly_spend WHERE account_id = %s", (account_id,)
                    )
                else:
                    cur.execute("TRUNCATE TABLE spend_ledger")
                    cur.execute("TRUNCATE TABLE monthly_spend")
            conn.commit()
