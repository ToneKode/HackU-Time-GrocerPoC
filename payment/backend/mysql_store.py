"""MySQL payment records — same contract as the in-memory PaymentStore.

Tables live in persistance/backend/schema.sql (`payments`, `payment_jti`).
"""
from __future__ import annotations

import importlib.util
import json
import sys
import threading
from pathlib import Path
from typing import Any

COLUMNS = (
    "payment_id",
    "status",
    "account_id",
    "amount",
    "currency",
    "merchant",
    "rail",
    "purpose",
    "intent",
    "cart_hash",
    "token_jti",
    "token",
    "token_expires_at",
    "recommendation",
    "auth_id",
    "order_id",
    "receipt_id",
    "error",
    "evidence",
    "created_at",
    "updated_at",
)
_COLUMN_SET = set(COLUMNS)


def _load_db():
    """Load persistance/backend/db.py without shadowing payment's modules."""
    name = "tg_persistance_db"
    if name in sys.modules:
        mod = sys.modules[name]
        root = Path(mod.__file__).resolve().parent
        return mod, root / "schema.sql"
    root = Path(__file__).resolve().parents[2] / "persistance" / "backend"
    path = root / "db.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load persistence db helper from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod, root / "schema.sql"


def _money(value: Any) -> float | None:
    if value is None:
        return None
    return round(float(value), 2)


def _json_load(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        return json.loads(text)
    return value


def _row_to_record(row: dict) -> dict:
    record = {key: row[key] for key in COLUMNS}
    record["amount"] = _money(record["amount"])
    record["currency"] = str(record["currency"] or "HKD").strip()
    if record["token_expires_at"] is not None:
        record["token_expires_at"] = int(record["token_expires_at"])
    record["recommendation"] = _json_load(record.get("recommendation"))
    evidence = _json_load(record.get("evidence"))
    record["evidence"] = list(evidence) if evidence else []
    extra = _json_load(row.get("extra")) or {}
    if not isinstance(extra, dict):
        extra = {}
    for key, value in extra.items():
        if key not in record:
            record[key] = value
    return record


def _to_row(record: dict) -> dict:
    row = {key: record.get(key) for key in COLUMNS}
    row["amount"] = _money(row["amount"])
    row["currency"] = str(row.get("currency") or "HKD")
    row["purpose"] = row.get("purpose") or ""
    row["intent"] = row.get("intent") or ""
    row["cart_hash"] = row.get("cart_hash") or ""
    row["token_expires_at"] = int(row["token_expires_at"])
    recommendation = row.get("recommendation")
    row["recommendation"] = (
        json.dumps(recommendation, ensure_ascii=False) if recommendation is not None else None
    )
    row["evidence"] = json.dumps(list(row.get("evidence") or []), ensure_ascii=False)
    extra = {key: value for key, value in record.items() if key not in _COLUMN_SET}
    row["extra"] = json.dumps(extra, ensure_ascii=False)
    return row


class MysqlPaymentStore:
    backend = "mysql"

    def __init__(self, database_url: str):
        self.database_url = database_url
        self._lock = threading.Lock()
        db, schema = _load_db()
        self._connect = db.connect
        db.apply_schema(database_url, schema)

    def put(self, record: dict) -> dict:
        row = _to_row(record)
        with self._lock:
            with self._connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO payments (
                            payment_id, status, account_id, amount, currency, merchant,
                            rail, purpose, intent, cart_hash, token_jti, token,
                            token_expires_at, recommendation, auth_id, order_id,
                            receipt_id, error, evidence, extra, created_at, updated_at
                        ) VALUES (
                            %(payment_id)s, %(status)s, %(account_id)s, %(amount)s,
                            %(currency)s, %(merchant)s, %(rail)s, %(purpose)s, %(intent)s,
                            %(cart_hash)s, %(token_jti)s, %(token)s, %(token_expires_at)s,
                            %(recommendation)s, %(auth_id)s, %(order_id)s, %(receipt_id)s,
                            %(error)s, %(evidence)s, %(extra)s, %(created_at)s, %(updated_at)s
                        ) AS new_row
                        ON DUPLICATE KEY UPDATE
                            status = new_row.status,
                            account_id = new_row.account_id,
                            amount = new_row.amount,
                            currency = new_row.currency,
                            merchant = new_row.merchant,
                            rail = new_row.rail,
                            purpose = new_row.purpose,
                            intent = new_row.intent,
                            cart_hash = new_row.cart_hash,
                            token_jti = new_row.token_jti,
                            token = new_row.token,
                            token_expires_at = new_row.token_expires_at,
                            recommendation = new_row.recommendation,
                            auth_id = new_row.auth_id,
                            order_id = new_row.order_id,
                            receipt_id = new_row.receipt_id,
                            error = new_row.error,
                            evidence = new_row.evidence,
                            extra = new_row.extra,
                            updated_at = new_row.updated_at
                        """,
                        row,
                    )
        return record

    def get(self, payment_id: str) -> dict | None:
        with self._connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payment_id, status, account_id, amount, currency, merchant,
                           rail, purpose, intent, cart_hash, token_jti, token,
                           token_expires_at, recommendation, auth_id, order_id,
                           receipt_id, error, evidence, extra, created_at, updated_at
                    FROM payments WHERE payment_id = %s
                    """,
                    (payment_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return _row_to_record(row)

    def mark_jti_used(self, jti: str) -> bool:
        """Return True if this is the first use (ok to charge)."""
        with self._lock:
            with self._connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT IGNORE INTO payment_jti (jti) VALUES (%s)",
                        (jti,),
                    )
                    inserted = cur.rowcount == 1
        return inserted

    def reset(self) -> None:
        with self._lock:
            with self._connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("TRUNCATE TABLE payment_jti")
                    cur.execute("TRUNCATE TABLE payments")
