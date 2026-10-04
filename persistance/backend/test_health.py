def test_health_reports_stores(c):
    body = c.get("/health").json()
    assert body["ok"] is True
    assert body["mysql"] is True and body["redis"] is True
    assert body["store"]["audit"] == "mysql"
    assert body["store"]["spend"] == "mysql"
    assert body["store"]["catalog"] == "mysql"
    assert body["escalation_owner"] == "backend-policy:8001"


def test_demo_reset_clears_everything(c):
    c.post("/log_event", json={"event": "PLAN", "status": "OK"})
    c.post("/spend", json={"account_id": "z", "amount": 1})
    r = c.post("/demo/reset").json()
    assert r["reset"] is True
    assert c.get("/audit_log").json() == []
    assert c.get("/spend/z").json()["spent"] == 0.0
    assert c.get("/health").json()["audit_entries"] == 0


def test_no_public_escalation_routes(c):
    assert c.post(
        "/create_escalation",
        json={
            "amount": 600,
            "merchant": "Watsons",
            "sku": "S",
            "qty": 1,
            "reason": "cap",
        },
    ).status_code == 404
