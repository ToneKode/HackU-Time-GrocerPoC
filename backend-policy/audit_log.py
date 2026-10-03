"""Hash-chained, append-only audit log (FR7 / NFR4).

hash = sha256("index|ts|event|status|reason|prev_hash")   (cross_team_config.json -> audit)
`thought` is stored for the UI trace but is NOT part of the hash, per that contract.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone

GENESIS = "0" * 64
HASH_FIELDS = ("index", "ts", "event", "status", "reason", "prev_hash")


def now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_hash(e: dict) -> str:
    return hashlib.sha256("|".join(str(e[k]) for k in HASH_FIELDS).encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        if not os.path.exists(path):
            open(path, "w").close()
        self._entries = self._read()

    def _read(self) -> list[dict]:
        with open(self.path, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def append(self, event: str, status: str, reason: str = "", thought: str = "") -> dict:
        with self._lock:
            prev = self._entries[-1]["hash"] if self._entries else GENESIS
            e = {"index": len(self._entries), "ts": now_ts(), "event": event, "status": status,
                 "reason": reason, "thought": thought, "prev_hash": prev}
            e["hash"] = compute_hash(e)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
            self._entries.append(e)
            return e

    def entries(self) -> list[dict]:
        return list(self._entries)

    def verify(self) -> dict:
        """Re-reads the file from disk so edits made behind our back are caught."""
        prev, rows = GENESIS, self._read()
        for i, e in enumerate(rows):
            if e.get("index") != i:
                return self._bad(i, "index_mismatch", len(rows))
            if e.get("prev_hash") != prev:
                return self._bad(i, "prev_hash_mismatch", len(rows))
            if compute_hash(e) != e.get("hash"):
                return self._bad(i, "hash_mismatch", len(rows))
            prev = e["hash"]
        return {"valid": True, "entries": len(rows), "head_hash": prev, "broken_at": None, "reason": None}

    @staticmethod
    def _bad(i: int, why: str, n: int) -> dict:
        return {"valid": False, "entries": n, "head_hash": None, "broken_at": i, "reason": why}

    # ---- demo helpers ----
    def tamper(self, index: int) -> None:
        rows = self._read()
        rows[index]["reason"] = rows[index]["reason"] + " (edited)"
        with self._lock, open(self.path, "w", encoding="utf-8") as f:
            for e in rows:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        self._entries = rows

    def reset(self) -> None:
        with self._lock:
            open(self.path, "w").close()
            self._entries = []
