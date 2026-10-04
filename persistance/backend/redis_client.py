"""Redis factory for escalation TTL keys.

Key scheme (owned by backend-policy escalations, clocked here):
  esc:live:{id}      EX=ttl   open-request timer
  esc:meta:{id}      JSON     escalation record
  esc:decision:{id}  SET NX   APPROVED | REFUSED | EXPIRED
  esc:dedupe:{hash}  EX=ttl   pending dedupe
  esc:pending        set      sweeper membership
"""
from __future__ import annotations

import redis


def make_redis(url: str):
    if url.startswith("fakeredis"):
        import fakeredis
        return fakeredis.FakeRedis(decode_responses=True)
    return redis.Redis.from_url(url, decode_responses=True)


def ping(url: str) -> bool:
    return bool(make_redis(url).ping())


def flush_escalations(r) -> int:
    """Delete escalation keys only (demo reset). Returns number of keys removed."""
    removed = 0
    for pattern in ("esc:live:*", "esc:meta:*", "esc:decision:*", "esc:dedupe:*"):
        keys = list(r.scan_iter(match=pattern, count=200))
        if keys:
            removed += r.delete(*keys)
    if r.exists("esc:pending"):
        removed += r.delete("esc:pending")
    return removed
