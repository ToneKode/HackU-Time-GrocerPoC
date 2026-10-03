"""Hash-chained, append-only audit log backed by Postgres.

Same contract as backend-policy/audit_log.py (FR7 / NFR4):
  hash = sha256("index|ts|event|status|reason|prev_hash")
  `thought` is stored for the UI trace but is NOT part of the hash.
"""
from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timezone

from db import connect

GENESIS = "0" * 64
HASH_FIELDS = ("index", "ts", "event", "status", "reason", "prev_hash")


def now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_hash(e: dict) -> str:
    return hashlib.sha256("|".join(str(e[k]) for k in HASH_FIELDS).encode("utf-8")).hexdigest()


def _row_to_entry(row: dict) -> dict:
    return {
        "index": row["idx"],
        "ts": row["ts"],
        "event": row["event"],
        "status": row["status"],
        "reason": row["reason"],
        "thought": row["thought"],
        "prev_hash": row["prev_hash"],
        "hash": row["hash"],
    }


class PostgresAuditLog:
    """Drop-in replacement for the JSONL AuditLog used by backend-policy."""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self._lock = threading.Lock()

    def append(self, event: str, status: str, reason: str = "", thought: str = "") -> dict:
        with self._lock:
            with connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    # Serialize appends across processes with an advisory lock.
                    cur.execute("SELECT pg_advisory_xact_lock(%s)", (872014,))
                    cur.execute(
                        "SELECT hash FROM audit_entries ORDER BY idx DESC LIMIT 1"
                    )
                    last = cur.fetchone()
                    prev = last["hash"] if last else GENESIS
                    cur.execute("SELECT COALESCE(MAX(idx) + 1, 0) AS next FROM audit_entries")
                    index = int(cur.fetchone()["next"])
                    e = {
                        "index": index,
                        "ts": now_ts(),
                        "event": event,
                        "status": status,
                        "reason": reason,
                        "thought": thought,
                        "prev_hash": prev,
                    }
                    e["hash"] = compute_hash(e)
                    cur.execute(
                        """
                        INSERT INTO audit_entries
                            (idx, ts, event, status, reason, thought, prev_hash, hash)
                        VALUES
                            (%(index)s, %(ts)s, %(event)s, %(status)s, %(reason)s,
                             %(thought)s, %(prev_hash)s, %(hash)s)
                        """,
                        e,
                    )
                conn.commit()
            return e

    def entries(self) -> list[dict]:
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT idx, ts, event, status, reason, thought, prev_hash, hash "
                    "FROM audit_entries ORDER BY idx ASC"
                )
                return [_row_to_entry(r) for r in cur.fetchall()]

    def verify(self) -> dict:
        rows = self.entries()
        prev = GENESIS
        for i, e in enumerate(rows):
            if e.get("index") != i:
                return self._bad(i, "index_mismatch", len(rows))
            if e.get("prev_hash") != prev:
                return self._bad(i, "prev_hash_mismatch", len(rows))
            if compute_hash(e) != e.get("hash"):
                return self._bad(i, "hash_mismatch", len(rows))
            prev = e["hash"]
        return {
            "valid": True,
            "entries": len(rows),
            "head_hash": prev,
            "broken_at": None,
            "reason": None,
        }

    @staticmethod
    def _bad(i: int, why: str, n: int) -> dict:
        return {
            "valid": False,
            "entries": n,
            "head_hash": None,
            "broken_at": i,
            "reason": why,
        }

    def tamper(self, index: int) -> None:
        with self._lock:
            with connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE audit_entries SET reason = reason || ' (edited)' "
                        "WHERE idx = %s",
                        (index,),
                    )
                conn.commit()

    def reset(self) -> None:
        with self._lock:
            with connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("TRUNCATE audit_entries")
                conn.commit()
