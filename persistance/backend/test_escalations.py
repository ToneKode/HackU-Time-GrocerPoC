"""Escalation store unit tests (Redis TTL). Public HTTP API is on backend-policy:8001."""
from __future__ import annotations

import time
import uuid

from audit_store import PostgresAuditLog
from config import settings
from db import apply_schema
from escalations import Escalations
from redis_client import make_redis


def _store():
    s = settings()
    apply_schema(s["database_url"], s["schema_path"])
    audit = PostgresAuditLog(s["database_url"])
    audit.reset()
    r = make_redis("fakeredis://")
    r.flushdb()
    return Escalations(r, audit, ttl=2, secret="test-secret"), audit


def test_create_matches_contract_shape():
    esc, _ = _store()
    e = esc.create(799.0, "HKD", "PARKnSHOP", "SKU003", 1, "Over HK$500 per-transaction cap")
    assert e["escalation_id"].startswith("esc_") and e["status"] == "PENDING"
    assert e["ttl_seconds"] == 2 and e["remaining_seconds"] in (1, 2)
    assert (e["amount"], e["currency"], e["merchant"], e["sku"]) == (
        799.0,
        "HKD",
        "PARKnSHOP",
        "SKU003",
    )
    assert esc.get(e["escalation_id"])["status"] == "PENDING"


def test_approve_and_refuse():
    esc, audit = _store()
    e = esc.create(650.0, "HKD", "Watsons", "S1", 1, "cap")
    r = esc.decide(e["escalation_id"], "APPROVE", None, False)
    assert r["status"] == "APPROVED" and r["decision_applied"] is True
    assert any(row["event"] == "ESCALATION_APPROVED" for row in audit.entries())

    esc2, audit2 = _store()
    e2 = esc2.create(650.0, "HKD", "Watsons", "S2", 1, "cap")
    url = e2["escalation_id"]
    assert esc2.decide(url, "REFUSE", None, False)["status"] == "REFUSED"
    again = esc2.decide(url, "APPROVE", None, False)
    assert again["status"] == "REFUSED" and again["decision_applied"] is False


def test_expiry_and_late_approval_ignored():
    esc, audit = _store()
    e = esc.create(650.0, "HKD", "Watsons", f"S-{uuid.uuid4().hex[:6]}", 1, "cap")
    time.sleep(2.3)
    r = esc.decide(e["escalation_id"], "APPROVE", None, False)
    assert r["status"] == "EXPIRED" and r["decision_applied"] is False
    assert r["late_decision_ignored"] is True
    events = [row["event"] for row in audit.entries()]
    assert events.count("ESCALATION_EXPIRED") == 1 and "LATE_DECISION_IGNORED" in events


def test_duplicate_create_returns_same_pending():
    esc, _ = _store()
    sku = f"DUP-{uuid.uuid4().hex[:6]}"
    a = esc.create(650.0, "HKD", "Watsons", sku, 1, "cap")
    b = esc.create(650.0, "HKD", "Watsons", sku, 1, "cap")
    assert a["escalation_id"] == b["escalation_id"]
    esc.decide(a["escalation_id"], "REFUSE", None, False)
    assert esc.create(650.0, "HKD", "Watsons", sku, 1, "cap")["escalation_id"] != a["escalation_id"]


def test_sweep_logs_unattended_expiry():
    esc, audit = _store()
    esc.create(650.0, "HKD", "Watsons", f"SW-{uuid.uuid4().hex[:6]}", 1, "cap")
    time.sleep(2.3)
    esc.sweep()
    assert [row["event"] for row in audit.entries()].count("ESCALATION_EXPIRED") == 1
