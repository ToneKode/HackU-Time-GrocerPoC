def test_health_reports_stores(c):
    body = c.get("/health").json()
    assert body["ok"] is True
    assert body["postgres"] is True and body["redis"] is True
    assert body["store"]["audit"] == "postgres"
    assert body["store"]["escalations"] == "fakeredis"
    assert body["store"]["spend"] == "postgres"


def test_demo_reset_clears_everything(c):
    c.post("/log_event", json={"event": "PLAN", "status": "OK"})
    c.post("/spend", json={"account_id": "z", "amount": 1})
    c.post(
        "/create_escalation",
        json={
            "amount": 600,
            "merchant": "Watsons",
            "sku": "S",
            "qty": 1,
            "reason": "cap",
        },
    )
    r = c.post("/demo/reset").json()
    assert r["reset"] is True
    assert c.get("/audit_log").json() == []
    assert c.get("/spend/z").json()["spent"] == 0.0
    assert c.get("/health").json()["audit_entries"] == 0
