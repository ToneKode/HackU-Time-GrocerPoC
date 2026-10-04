"""Payment record store.

MySQL (`persistance` schema) is the durable path. Memory / optional Redis
is the zero-dependency fallback used by unit tests and when MySQL is down.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any

STATUSES = ("DRAFT", "PENDING", "AUTHORIZED", "CAPTURED", "FAILED", "REFUNDED")


def new_id() -> str:
    return "pay_" + uuid.uuid4().hex[:12]


class PaymentStore:
    backend = "memory"

    def __init__(self, redis_url: str = ""):
        self._lock = threading.Lock()
        self._mem: dict[str, dict] = {}
        self._jti_used: set[str] = set()
        self._r = None
        if redis_url and not redis_url.startswith("fakeredis"):
            import redis
            self._r = redis.Redis.from_url(redis_url, decode_responses=True)
        elif redis_url.startswith("fakeredis"):
            import fakeredis
            self._r = fakeredis.FakeRedis(decode_responses=True)

    def put(self, record: dict) -> dict:
        with self._lock:
            self._mem[record["payment_id"]] = record.copy()
            if self._r is not None:
                self._r.set(f"pay:rec:{record['payment_id']}", json.dumps(record), ex=7 * 24 * 3600)
        return record

    def get(self, payment_id: str) -> dict | None:
        if self._r is not None:
            raw = self._r.get(f"pay:rec:{payment_id}")
            if raw:
                return json.loads(raw)
        record = self._mem.get(payment_id)
        return record.copy() if record else None

    def mark_jti_used(self, jti: str) -> bool:
        """Return True if this is the first use (ok to charge)."""
        with self._lock:
            if self._r is not None:
                return bool(self._r.set(f"pay:jti:{jti}", "1", nx=True, ex=7 * 24 * 3600))
            if jti in self._jti_used:
                return False
            self._jti_used.add(jti)
            return True

    def begin_attempt(self, record: dict) -> dict:
        """Persist retry context before the first rail request."""
        with self._lock:
            current = self.get(record["payment_id"])
            if current and current["status"] in {"PENDING", "CAPTURED"}:
                return current
            jti = record["token_jti"]
            if self._r is not None:
                if not self._r.set(f"pay:jti:{jti}", "1", nx=True, ex=7 * 24 * 3600):
                    raise ValueError("Token already used")
            elif jti in self._jti_used:
                raise ValueError("Token already used")
            self._jti_used.add(jti)
            self._mem[record["payment_id"]] = record.copy()
            if self._r is not None:
                self._r.set(f"pay:rec:{record['payment_id']}", json.dumps(record), ex=7 * 24 * 3600)
            return record

    def reset(self) -> None:
        with self._lock:
            self._mem.clear()
            self._jti_used.clear()
            if self._r is not None:
                for pattern in ("pay:rec:*", "pay:jti:*"):
                    keys = list(self._r.scan_iter(match=pattern, count=200))
                    if keys:
                        self._r.delete(*keys)


def open_store(database_url: str = "", redis_url: str = ""):
    """MySQL when the URL starts with mysql. Empty URL keeps memory."""
    url = (database_url or "").strip()
    if url.startswith("mysql"):
        from mysql_store import MysqlPaymentStore

        return MysqlPaymentStore(url)
    if url.startswith("postgres"):
        from pg_store import PostgresPaymentStore

        return PostgresPaymentStore(url)
    return PaymentStore(redis_url)


def draft_record(
    *,
    account_id: str,
    amount: float,
    currency: str,
    merchant: str,
    rail: str,
    purpose: str,
    intent: str,
    cart_hash: str,
    token: dict,
    recommendation: dict | None,
) -> dict[str, Any]:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return {
        "payment_id": new_id(),
        "status": "DRAFT",
        "account_id": account_id,
        "amount": round(float(amount), 2),
        "currency": currency,
        "merchant": merchant,
        "rail": rail,
        "purpose": purpose,
        "intent": intent,
        "cart_hash": cart_hash,
        "token_jti": token["jti"],
        "token": token["token"],
        "token_expires_at": token["expires_at"],
        "recommendation": recommendation,
        "auth_id": None,
        "order_id": None,
        "receipt_id": None,
        "error": None,
        "evidence": ["intent", "cart_frozen", "token_minted"],
        "created_at": now,
        "updated_at": now,
    }
