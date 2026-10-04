def test_spend_starts_at_zero(c):
    body = c.get("/spend/acct-1").json()
    assert body["account_id"] == "acct-1"
    assert body["spent"] == 0.0
    assert body["currency"] == "HKD"
    assert len(body["year_month"]) == 7


def test_record_and_idempotency(c):
    a = c.post(
        "/spend",
        json={
            "account_id": "acct-2",
            "amount": 120.5,
            "idempotency_key": "pay-1",
            "payment_id": "tx-1",
        },
    ).json()
    assert a["spent"] == 120.5 and a["added"] == 120.5 and a["duplicate"] is False

    again = c.post(
        "/spend",
        json={
            "account_id": "acct-2",
            "amount": 120.5,
            "idempotency_key": "pay-1",
        },
    ).json()
    assert again["spent"] == 120.5 and again["duplicate"] is True

    b = c.post(
        "/spend",
        json={"account_id": "acct-2", "amount": 10, "idempotency_key": "pay-2"},
    ).json()
    assert b["spent"] == 130.5

    got = c.get("/spend/acct-2").json()
    assert got["spent"] == 130.5


def test_spend_validation(c):
    assert (
        c.post("/spend", json={"account_id": "x", "amount": 0}).status_code == 422
    )
