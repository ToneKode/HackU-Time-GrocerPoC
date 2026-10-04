import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import fakeredis
import pytest

from audit_log import AuditLog
from conftest import escalate
from escalations import Escalations


def events(c):
    return [e["event"] for e in c.get("/audit_log").json()]


def test_create_matches_contract_shape(c):
    e = escalate(c)
    assert e["escalation_id"].startswith("esc_") and e["status"] == "PENDING"
    assert e["ttl_seconds"] == 2 and e["remaining_seconds"] in (1, 2)
    assert (e["amount"], e["currency"], e["merchant"], e["sku"]) == (799.0, "HKD", "PARKnSHOP", "SKU003")
    assert e["reason"] == "Over HK$500 per-transaction cap" and e["expires_at"].endswith("Z")
    assert c.get(f"/escalations/{e['escalation_id']}").json()["status"] == "PENDING"


def test_approve(c):
    e = escalate(c)
    r = c.post(f"/escalations/{e['escalation_id']}/decision", json={"decision": "APPROVE"}).json()
    assert r["status"] == "APPROVED" and r["decision_applied"] is True and r["remaining_seconds"] == 0
    assert "ESCALATION_APPROVED" in events(c)


def test_refuse_then_cannot_approve(c):
    e = escalate(c)
    url = f"/escalations/{e['escalation_id']}/decision"
    assert c.post(url, json={"decision": "REFUSE"}).json()["status"] == "REFUSED"
    again = c.post(url, json={"decision": "APPROVE"}).json()
    assert again["status"] == "REFUSED" and again["decision_applied"] is False


def test_expiry_and_late_approval_ignored(c):
    e = escalate(c)
    time.sleep(2.3)
    r = c.post(f"/escalations/{e['escalation_id']}/decision", json={"decision": "APPROVE"}).json()
    assert r["status"] == "EXPIRED" and r["decision_applied"] is False and r["late_decision_ignored"] is True
    assert r["remaining_seconds"] == 0 and "decision_attempt_at" in r
    ev = events(c)
    assert ev.count("ESCALATION_EXPIRED") == 1 and "LATE_DECISION_IGNORED" in ev
    assert "ESCALATION_APPROVED" not in ev


def test_sweeper_logs_unattended_expiry(c):
    escalate(c)
    time.sleep(3.3)                       # background sweeper runs every second
    assert events(c).count("ESCALATION_EXPIRED") == 1


def test_duplicate_create_returns_same_pending_then_new_after_decision(c):
    a, b = escalate(c), escalate(c)
    assert a["escalation_id"] == b["escalation_id"]
    c.post(f"/escalations/{a['escalation_id']}/decision", json={"decision": "REFUSE"})
    assert escalate(c)["escalation_id"] != a["escalation_id"]


def test_accounts_have_independent_escalations_and_decisions(c):
    a = escalate(c, account_id="alice", run_id="run-1")
    b = escalate(c, account_id="bob", run_id="run-1")
    assert a["escalation_id"] != b["escalation_id"]
    assert (a["account_id"], a["run_id"]) == ("alice", "run-1")
    assert (b["account_id"], b["run_id"]) == ("bob", "run-1")
    assert c.post(f"/escalations/{a['escalation_id']}/decision",
                  json={"decision": "APPROVE"}).json()["status"] == "APPROVED"
    assert c.get(f"/escalations/{b['escalation_id']}").json()["status"] == "PENDING"
    assert c.post(f"/escalations/{b['escalation_id']}/decision",
                  json={"decision": "REFUSE"}).json()["status"] == "REFUSED"


@pytest.mark.parametrize("scope", ["run_id", "order_id"])
@pytest.mark.parametrize("decision", ["APPROVE", "REFUSE"])
def test_scoped_retries_preserve_decision_and_new_scope_is_independent(c, scope, decision):
    tags = {"account_id": "alice", scope: "first"}
    a = escalate(c, **tags)
    assert escalate(c, **tags)["escalation_id"] == a["escalation_id"]
    c.post(f"/escalations/{a['escalation_id']}/decision", json={"decision": decision})
    retry = escalate(c, **tags)
    assert retry["escalation_id"] == a["escalation_id"]
    assert retry["status"] == ("APPROVED" if decision == "APPROVE" else "REFUSED")
    other = escalate(c, **{**tags, scope: "second"})
    assert other["escalation_id"] != a["escalation_id"] and other["status"] == "PENDING"


def test_run_and_order_are_both_part_of_scope(c):
    a = escalate(c, account_id="alice", run_id="run-1", order_id="order-1")
    b = escalate(c, account_id="alice", run_id="run-1", order_id="order-2")
    assert a["escalation_id"] != b["escalation_id"]
    assert a["order_id"] == "order-1"


def test_empty_account_matches_legacy_pending_retry(c):
    a = escalate(c)
    assert escalate(c, account_id="")["escalation_id"] == a["escalation_id"]
    assert escalate(c, account_id=None)["escalation_id"] == a["escalation_id"]
    assert escalate(c, account_id="alice")["escalation_id"] != a["escalation_id"]


@pytest.fixture()
def store(tmp_path):
    return Escalations(fakeredis.FakeRedis(decode_responses=True),
                       AuditLog(str(tmp_path / "audit.jsonl")), 30, "test-secret")


def create_scoped(store, **tags):
    return store.create(799, "HKD", "PARKnSHOP", "SKU003", 1, "Over cap",
                        account_id="alice", run_id="run-1", **tags)


def test_scoped_expiry_retry_does_not_restart_approval_window(store):
    a = create_scoped(store)
    store.r.delete(store._k("live", a["escalation_id"]))
    retry = create_scoped(store)
    assert retry["escalation_id"] == a["escalation_id"] and retry["status"] == "EXPIRED"
    assert not store.r.exists(store._k("live", a["escalation_id"]))


def test_concurrent_creation_returns_one_escalation(store, monkeypatch):
    original_pipeline = store.r.pipeline
    barrier = Barrier(2)

    def pipeline(*args, **kwargs):
        p = original_pipeline(*args, **kwargs)
        original_get = p.get

        def get(key):
            value = original_get(key)
            if key.startswith("esc:dedupe:") and value is None:
                barrier.wait(timeout=5)
            return value

        p.get = get
        return p

    monkeypatch.setattr(store.r, "pipeline", pipeline)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: create_scoped(store), range(2)))
    assert results[0]["escalation_id"] == results[1]["escalation_id"]
    assert store.r.scard("esc:pending") == 1
    assert len(store.r.keys("esc:meta:*")) == 1


def test_concurrent_decisions_have_one_winner(store):
    a = create_scoped(store)
    barrier = Barrier(2)

    def decide(decision):
        barrier.wait(timeout=5)
        return store.decide(a["escalation_id"], decision, None, False)

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(decide, ["APPROVE", "REFUSE"]))
    assert sum(result["decision_applied"] for result in results) == 1
    assert results[0]["status"] == results[1]["status"]
    assert results[0]["status"] in ("APPROVED", "REFUSED")
    assert len(store.audit.entries()) == 1


def test_expiry_between_live_check_and_commit_cannot_approve(store, monkeypatch):
    a = create_scoped(store)
    live_key = store._k("live", a["escalation_id"])
    original_pipeline = store.r.pipeline

    def pipeline(*args, **kwargs):
        p = original_pipeline(*args, **kwargs)
        original_execute = p.execute

        def execute(*args, **kwargs):
            store.r.delete(live_key)
            return original_execute(*args, **kwargs)

        p.execute = execute
        return p

    monkeypatch.setattr(store.r, "pipeline", pipeline)
    result = store.decide(a["escalation_id"], "APPROVE", None, False)
    assert result["status"] == "EXPIRED" and result["decision_applied"] is False
    assert result["late_decision_ignored"] is True
    assert "ESCALATION_APPROVED" not in [entry["event"] for entry in store.audit.entries()]


def test_expired_legacy_cleanup_preserves_replacement(store):
    a = store.create(799, "HKD", "PARKnSHOP", "SKU003", 1, "Over cap")
    store.r.delete(store._k("live", a["escalation_id"]))
    store.r.delete(store._k("dedupe", store._meta(a["escalation_id"])["_dedupe"]))
    b = store.create(799, "HKD", "PARKnSHOP", "SKU003", 1, "Over cap")
    assert store.get(a["escalation_id"])["status"] == "EXPIRED"
    assert store.create(799, "HKD", "PARKnSHOP", "SKU003", 1, "Over cap")["escalation_id"] == b["escalation_id"]


def test_create_guards(c):
    r = c.post("/create_escalation", json={"amount": 300, "merchant": "Watsons", "category": "Household", "sku": "S", "reason": "x"})
    assert r.status_code == 422
    r = c.post("/create_escalation", json={"amount": 900, "merchant": "Watsons", "category": "Household", "sku": "S", "reason": "x"})
    assert r.status_code == 422
    r = c.post("/create_escalation", json={"amount": 700, "merchant": "DarkWebMart", "category": "Household", "sku": "S", "reason": "x"})
    assert r.status_code == 422


def test_create_guard_applies_category_and_monthly_cap(c):
    def post(**kw):
        body = {"amount": 650, "merchant": "Watsons", "category": "Household", "sku": "S", "reason": "x"}
        return c.post("/create_escalation", json={**body, **kw})
    assert post().status_code == 200
    assert post(category="Health", sku="S2").status_code == 200             # category list is empty
    assert post(monthly_spent=1500, sku="S3").status_code == 422            # 1500 + 650 > 2000
    assert post(category="", sku="S4").status_code == 422                   # blank category
    body = {"amount": 650, "merchant": "Watsons", "sku": "S5", "reason": "x"}
    assert c.post("/create_escalation", json=body).status_code == 422      # category is required


def test_redis_failure_returns_json_503(c, monkeypatch):
    import main
    import redis

    def boom(*_a, **_k):
        raise redis.ConnectionError("down")
    monkeypatch.setattr(main.escalations, "get", boom)
    r = c.get("/escalations/esc_x")
    assert r.status_code == 503 and "unavailable" in r.json()["detail"]


def test_health_reports_redis(c):
    body = c.get("/health").json()
    assert body["ok"] is True and body["redis"] is True
    assert body["store"]["escalations"] == "fakeredis"
    assert body["store"]["audit"] == "jsonl"


def test_unknown_escalation_404(c):
    assert c.get("/escalations/nope").status_code == 404
    assert c.post("/escalations/nope/decision", json={"decision": "APPROVE"}).status_code == 404


def test_bad_decision_value_422(c):
    e = escalate(c)
    assert c.post(f"/escalations/{e['escalation_id']}/decision", json={"decision": "MAYBE"}).status_code == 422


def test_signature_checked_when_supplied(c):
    e = escalate(c)
    url = f"/escalations/{e['escalation_id']}/decision"
    assert c.post(url, json={"decision": "APPROVE", "signature": "forged"}).status_code == 403
    assert c.get(f"/escalations/{e['escalation_id']}").json()["status"] == "PENDING"
    assert c.post(url, json={"decision": "APPROVE", "signature": e["signature"]}).json()["status"] == "APPROVED"
