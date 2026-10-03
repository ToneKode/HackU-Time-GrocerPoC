import hashlib


def log(c, event="POLICY_CHECK", status="PASS", reason="Under HK$500 cap", **kw):
    return c.post("/log_event", json={"event": event, "status": status, "reason": reason, **kw}).json()


def test_chain_links_and_contract_hash(c):
    a, b = log(c), log(c, "PAYMENT", "COMPLETED", "Payment success", thought="Charge the landed total.")
    assert a["index"] == 0 and a["prev_hash"] == "0" * 64
    assert b["index"] == 1 and b["prev_hash"] == a["hash"]
    expect = hashlib.sha256(f"{a['index']}|{a['ts']}|{a['event']}|{a['status']}|{a['reason']}|{a['prev_hash']}".encode()).hexdigest()
    assert a["hash"] == expect
    assert a["ts"].endswith("Z") and len(a["ts"]) == 20
    assert set(b) >= {"index", "ts", "event", "status", "reason", "thought", "prev_hash", "hash"}


def test_contract_example_hash_is_reproducible():
    from audit_log import compute_hash
    e = {"index": 0, "ts": "2026-10-03T12:00:00Z", "event": "INTENT_RECEIVED", "status": "PARSED",
         "reason": "Model may decide query and qty only", "prev_hash": "0" * 64}
    assert compute_hash(e) == "7c522f3b39ee31ba0f80a1e3d0e811a7f6537df8fb649bbdf6c97b81663a58f5"


def test_audit_log_endpoint_and_verify(c):
    for i in range(3):
        log(c, reason=f"r{i}")
    rows = c.get("/audit_log").json()
    assert [r["index"] for r in rows] == [0, 1, 2]
    assert c.get("/audit_log/verify").json()["valid"] is True


def test_tamper_is_detected(c):
    for i in range(3):
        log(c, reason=f"r{i}")
    v = c.post("/demo/tamper/1").json()
    assert v["valid"] is False and v["broken_at"] == 1 and v["reason"] == "hash_mismatch"


def test_log_event_validation(c):
    assert c.post("/log_event", json={"event": "", "status": "x"}).status_code == 422
