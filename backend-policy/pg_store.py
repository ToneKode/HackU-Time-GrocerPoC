"""Postgres backing for the audit ledger and escalation rows.

The public methods match AuditLog and Escalations. Tests leave DATABASE_URL empty
and keep using the jsonl file plus in-process fakeredis.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import threading
import time
import uuid
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

from audit_log import GENESIS, compute_hash, now_ts

DEMO_USER = "11111111-1111-1111-1111-111111111111"


def _ts(value) -> str:
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _money(value) -> float:
    return round(float(value), 2)


class PostgresAuditLog:
    def __init__(self, url: str):
        self.url = url
        self._lock = threading.Lock()

    def _conn(self):
        return psycopg.connect(self.url, row_factory=dict_row)

    def _row(self, raw: dict) -> dict:
        return {
            "index": raw["chain_index"],
            "ts": _ts(raw["ts"]),
            "event": raw["event"],
            "status": raw["status"],
            "reason": raw["reason"],
            "thought": raw["thought"] or "",
            "prev_hash": raw["prev_hash"].strip(),
            "hash": raw["hash"].strip(),
        }

    def append(self, event: str, status: str, reason: str = "", thought: str = "") -> dict:
        with self._lock, self._conn() as conn:
            prev = conn.execute(
                "SELECT chain_index, hash FROM audit_log ORDER BY chain_index DESC LIMIT 1 FOR UPDATE"
            ).fetchone()
            if prev is None:
                index, prev_hash = 0, GENESIS
            else:
                index, prev_hash = prev["chain_index"] + 1, prev["hash"].strip()
            entry = {
                "index": index,
                "ts": now_ts(),
                "event": event,
                "status": status,
                "reason": reason,
                "thought": thought,
                "prev_hash": prev_hash,
            }
            entry["hash"] = compute_hash(entry)
            conn.execute(
                """
                INSERT INTO audit_log
                  (chain_index, user_id, ts, event, status, reason, thought, prev_hash, hash)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (index, DEMO_USER, entry["ts"], event, status, reason, thought, prev_hash, entry["hash"]),
            )
            return entry

    def entries(self) -> list[dict]:
        with self._lock, self._conn() as conn:
            rows = conn.execute("SELECT * FROM audit_log ORDER BY chain_index").fetchall()
        return [self._row(row) for row in rows]

    def verify(self) -> dict:
        prev, rows = GENESIS, self.entries()
        for i, entry in enumerate(rows):
            if entry.get("index") != i:
                return _bad(i, "index_mismatch", len(rows))
            if entry.get("prev_hash") != prev:
                return _bad(i, "prev_hash_mismatch", len(rows))
            if compute_hash(entry) != entry.get("hash"):
                return _bad(i, "hash_mismatch", len(rows))
            prev = entry["hash"]
        return {"valid": True, "entries": len(rows), "head_hash": prev, "broken_at": None, "reason": None}

    def tamper(self, index: int) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                "UPDATE audit_log SET reason = reason || ' (edited)' WHERE chain_index = %s",
                (index,),
            )

    def reset(self) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM audit_log")

    def ping(self) -> bool:
        with self._conn() as conn:
            return conn.execute("SELECT 1").fetchone() is not None


def _bad(i: int, why: str, n: int) -> dict:
    return {"valid": False, "entries": n, "head_hash": None, "broken_at": i, "reason": why}


class PostgresEscalations:
    def __init__(self, url: str, audit: PostgresAuditLog, ttl: int, secret: str):
        self.url, self.audit, self.ttl, self.secret = url, audit, ttl, secret.encode()
        self._lock = threading.Lock()

    def _conn(self):
        return psycopg.connect(self.url, row_factory=dict_row)

    def ping(self) -> bool:
        with self._conn() as conn:
            return conn.execute("SELECT 1").fetchone() is not None

    def reset_state(self) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM escalations")

    def _sign(self, esc_id: str, amount: float, expires_at: float) -> str:
        msg = f"{esc_id}|{amount:.2f}|{int(expires_at)}".encode()
        return hmac.new(self.secret, msg, hashlib.sha256).hexdigest()

    def _public(self, row: dict, status: str, remaining: int) -> dict:
        return {
            "escalation_id": row["escalation_id"],
            "ttl_seconds": row["ttl_seconds"],
            "expires_at": _ts(row["expires_at"]),
            "amount": _money(row["amount"]),
            "currency": str(row["currency"]).strip(),
            "merchant": row["merchant"],
            "sku": row["sku"],
            "qty": row["qty"],
            "reason": row["reason"],
            "created_at": _ts(row["created_at"]),
            "signature": row["signature"],
            "status": status,
            "remaining_seconds": remaining,
        }

    def _load(self, conn, esc_id: str) -> dict:
        row = conn.execute(
            "SELECT * FROM escalations WHERE escalation_id = %s FOR UPDATE",
            (esc_id,),
        ).fetchone()
        if row is None:
            from escalations import NotFound
            raise NotFound(esc_id)
        return row

    def create(self, amount: float, currency: str, merchant: str, sku: str, qty: int, reason: str) -> dict:
        amount = round(float(amount), 2)
        with self._lock, self._conn() as conn:
            existing = conn.execute(
                """
                SELECT escalation_id FROM escalations
                WHERE merchant = %s AND sku = %s AND qty = %s AND amount = %s
                  AND status = 'PENDING' AND expires_at > now()
                """,
                (merchant, sku, qty, amount),
            ).fetchone()
            if existing:
                esc_id = existing["escalation_id"]
            else:
                esc_id = "esc_" + uuid.uuid4().hex[:10]
                now = time.time()
                expires_at = now + self.ttl
                conn.execute(
                    """
                    INSERT INTO escalations (
                      escalation_id, user_id, status, ttl_seconds, amount, currency,
                      merchant, sku, qty, reason, signature, created_at, expires_at
                    ) VALUES (
                      %s, %s, 'PENDING', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        esc_id, DEMO_USER, self.ttl, amount, currency, merchant, sku, qty, reason,
                        self._sign(esc_id, amount, expires_at), _ts(datetime.fromtimestamp(now, timezone.utc)),
                        _ts(datetime.fromtimestamp(expires_at, timezone.utc)),
                    ),
                )
        return self.get(esc_id)

    def get(self, esc_id: str) -> dict:
        with self._lock, self._conn() as conn:
            row = self._load(conn, esc_id)
            status = row["status"]
            expired_now = False
            if status == "PENDING" and row["expires_at"] <= datetime.now(timezone.utc):
                updated = conn.execute(
                    """
                    UPDATE escalations SET status = 'EXPIRED'
                    WHERE escalation_id = %s AND status = 'PENDING'
                    RETURNING escalation_id
                    """,
                    (esc_id,),
                ).fetchone()
                status = "EXPIRED"
                expired_now = updated is not None
            remaining = 0
            if status == "PENDING":
                seconds = (row["expires_at"] - datetime.now(timezone.utc)).total_seconds()
                remaining = max(0, min(self.ttl, math.ceil(seconds)))
            public = self._public(row, status, remaining)
        if expired_now:
            self.audit.append(
                "ESCALATION_EXPIRED", "EXPIRED",
                f"No decision within {self.ttl}s. Purchase aborted.",
                "TTL reached 0. Abort and clear the cart.",
            )
        return public

    def lookup(self, esc_id: str):
        from escalations import NotFound
        try:
            return self.get(esc_id)
        except NotFound:
            return None

    def decide(self, esc_id: str, decision: str, signature: str | None, require_signature: bool) -> dict:
        from escalations import BadSignature
        with self._lock, self._conn() as conn:
            row = self._load(conn, esc_id)
            if signature is not None or require_signature:
                if not signature or not hmac.compare_digest(signature, row["signature"] or ""):
                    self.audit.append("ESCALATION_BAD_SIGNATURE", "REJECTED", f"Invalid signature for {esc_id}")
                    raise BadSignature()
            attempt = now_ts()
            state = "APPROVED" if decision == "APPROVE" else "REFUSED"
            verb = "APPROVE" if decision == "APPROVE" else "REFUSE"
            applied_row = None
            if row["status"] == "PENDING" and row["expires_at"] > datetime.now(timezone.utc):
                applied_row = conn.execute(
                    """
                    UPDATE escalations
                    SET status = %s, decision = %s, decided_at = now()
                    WHERE escalation_id = %s AND status = 'PENDING' AND expires_at > now()
                    RETURNING escalation_id
                    """,
                    (state, verb, esc_id),
                ).fetchone()
        applied = applied_row is not None
        if applied:
            if state == "APPROVED":
                self.audit.append(
                    "ESCALATION_APPROVED", "APPROVED", f"Mother approved HK${_money(row['amount']):.2f}",
                    "Approved inside the TTL. The agent may pay.",
                )
            else:
                self.audit.append(
                    "ESCALATION_REFUSED", "REFUSED", f"Mother refused HK${_money(row['amount']):.2f}",
                    "Refused. Abort and clear the cart.",
                )
        out = self.get(esc_id)
        out["decision_applied"] = applied
        if not applied:
            out["decision_attempt_at"] = attempt
            if out["status"] == "EXPIRED":
                out["late_decision_ignored"] = True
                with self._conn() as conn:
                    conn.execute(
                        """
                        UPDATE escalations
                        SET late_approval_ignored = TRUE, approval_attempt_at = %s
                        WHERE escalation_id = %s
                        """,
                        (attempt, esc_id),
                    )
                self.audit.append(
                    "LATE_DECISION_IGNORED", "IGNORED",
                    f"{decision} for {esc_id} arrived after expiry at {out['expires_at']} (attempt {attempt})",
                    "Escalation already expired. No payment authorised.",
                )
        return out

    def sweep(self) -> None:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT escalation_id FROM escalations WHERE status = 'PENDING' AND expires_at <= now()"
            ).fetchall()
        for row in rows:
            self.get(row["escalation_id"])
