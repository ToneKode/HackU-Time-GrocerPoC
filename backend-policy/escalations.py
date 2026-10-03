"""Human-in-the-loop escalation with a Redis TTL (10 minutes by default).

Redis keys
  esc:live:{id}      EX=ttl   exists while the request is open; Redis is the clock
  esc:meta:{id}      JSON     the escalation record (kept after the TTL for status/audit)
  esc:decision:{id}  SET NX   first writer wins: APPROVED | REFUSED | EXPIRED
  esc:dedupe:{hash}  EX=ttl   same merchant/sku/qty/amount while PENDING -> same escalation
  esc:pending        set      swept every second so unattended expiries are logged

The decision key is the single source of truth, so approve/refuse/expire can never
both win, and a late APPROVE after the TTL cannot authorise anything.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import time
import uuid
from datetime import datetime, timezone

import redis

from audit_log import AuditLog

META_TTL = 7 * 24 * 3600


def make_redis(url: str):
    if url.startswith("fakeredis"):
        import fakeredis
        return fakeredis.FakeRedis(decode_responses=True)
    return redis.Redis.from_url(url, decode_responses=True)


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class NotFound(Exception): ...
class BadSignature(Exception): ...


class Escalations:
    def __init__(self, r, audit: AuditLog, ttl: int, secret: str):
        self.r, self.audit, self.ttl, self.secret = r, audit, ttl, secret.encode()

    def ping(self) -> bool:
        return bool(self.r.ping())

    def reset_state(self) -> None:
        self.r.flushdb()

    @staticmethod
    def _k(kind: str, id_: str) -> str:
        return f"esc:{kind}:{id_}"

    def _sign(self, esc_id: str, amount: float, expires_at: float) -> str:
        msg = f"{esc_id}|{amount:.2f}|{int(expires_at)}".encode()
        return hmac.new(self.secret, msg, hashlib.sha256).hexdigest()

    def _meta(self, esc_id: str) -> dict:
        raw = self.r.get(self._k("meta", esc_id))
        if raw is None:
            raise NotFound(esc_id)
        return json.loads(raw)

    # ------------------------------------------------------------------
    def create(self, amount: float, currency: str, merchant: str, sku: str, qty: int, reason: str) -> dict:
        dkey = hashlib.sha256(f"{merchant}|{sku}|{qty}|{amount:.2f}".encode()).hexdigest()[:24]
        existing = self.r.get(self._k("dedupe", dkey))
        if existing:                                   # retry / double-click: same pending request
            return self.get(existing)
        esc_id = "esc_" + uuid.uuid4().hex[:10]
        now = time.time()
        expires_at = now + self.ttl
        meta = {"escalation_id": esc_id, "ttl_seconds": self.ttl, "expires_at": iso(expires_at),
                "amount": round(amount, 2), "currency": currency, "merchant": merchant, "sku": sku,
                "qty": qty, "reason": reason, "created_at": iso(now), "_expires_ts": expires_at,
                "_dedupe": dkey, "signature": self._sign(esc_id, amount, expires_at)}
        p = self.r.pipeline()
        p.set(self._k("meta", esc_id), json.dumps(meta), ex=META_TTL)
        p.set(self._k("live", esc_id), "1", ex=self.ttl)          # <- the timer
        p.set(self._k("dedupe", dkey), esc_id, ex=self.ttl)
        p.sadd("esc:pending", esc_id)
        p.execute()
        return self.get(esc_id)

    def get(self, esc_id: str) -> dict:
        meta = self._meta(esc_id)
        decision = self.r.get(self._k("decision", esc_id))
        if decision is None and not self.r.exists(self._k("live", esc_id)):
            decision = self._expire(esc_id, meta)
        status = decision or "PENDING"
        remaining = 0
        if status == "PENDING":
            pttl = self.r.pttl(self._k("live", esc_id))
            remaining = max(0, min(self.ttl, math.ceil(pttl / 1000))) if pttl and pttl > 0 else 0
        out = {k: v for k, v in meta.items() if not k.startswith("_")}
        out.update(status=status, remaining_seconds=remaining)
        return out

    def lookup(self, esc_id: str):
        try:
            return self.get(esc_id)
        except NotFound:
            return None

    def _expire(self, esc_id: str, meta: dict) -> str:
        if self.r.set(self._k("decision", esc_id), "EXPIRED", nx=True):
            self._close(esc_id, meta)
            self.audit.append("ESCALATION_EXPIRED", "EXPIRED",
                              f"No decision within {self.ttl}s. Purchase aborted.",
                              "TTL reached 0. Abort and clear the cart.")
        return self.r.get(self._k("decision", esc_id))

    def _close(self, esc_id: str, meta: dict) -> None:
        self.r.srem("esc:pending", esc_id)
        self.r.delete(self._k("dedupe", meta["_dedupe"]))

    # ------------------------------------------------------------------
    def decide(self, esc_id: str, decision: str, signature: str | None, require_signature: bool) -> dict:
        meta = self._meta(esc_id)
        if signature is not None or require_signature:
            if not signature or not hmac.compare_digest(signature, meta["signature"]):
                self.audit.append("ESCALATION_BAD_SIGNATURE", "REJECTED", f"Invalid signature for {esc_id}")
                raise BadSignature()
        attempt = iso(time.time())
        applied = False
        state = "APPROVED" if decision == "APPROVE" else "REFUSED"

        if self.r.exists(self._k("live", esc_id)) and self.r.set(self._k("decision", esc_id), state, nx=True):
            applied = True
            self._close(esc_id, meta)
            if state == "APPROVED":
                self.audit.append("ESCALATION_APPROVED", "APPROVED", f"Mother approved HK${meta['amount']:.2f}",
                                  "Approved inside the TTL. The agent may pay.")
            else:
                self.audit.append("ESCALATION_REFUSED", "REFUSED", f"Mother refused HK${meta['amount']:.2f}",
                                  "Refused. Abort and clear the cart.")
        out = self.get(esc_id)            # also finalises EXPIRED if the TTL is gone
        out["decision_applied"] = applied
        if not applied:
            out["decision_attempt_at"] = attempt
            if out["status"] == "EXPIRED":
                out["late_decision_ignored"] = True
                self.audit.append("LATE_DECISION_IGNORED", "IGNORED",
                                  f"{decision} for {esc_id} arrived after expiry at {meta['expires_at']} (attempt {attempt})",
                                  "Escalation already expired. No payment authorised.")
        return out

    # ------------------------------------------------------------------
    def sweep(self) -> None:
        for esc_id in list(self.r.smembers("esc:pending")):
            try:
                self.get(esc_id)           # get() finalises + logs expiry
            except NotFound:
                self.r.srem("esc:pending", esc_id)
