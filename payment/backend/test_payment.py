def test_memory_store_when_database_url_empty():
    from store import PaymentStore, open_store

    store = open_store("", "")
    assert isinstance(store, PaymentStore)
    assert store.backend == "memory"


def test_health(c):
    body = c.get("/health").json()
    assert body["ok"] is True and body["service"] == "payment"
    assert body["store"] == "memory"
    assert "mastercard" in body["rails"]


def test_recommend_ranks_rails(c):
    body = c.post("/payment/recommend", json={"amount": 200, "merchants": ["Watsons"]}).json()
    assert body["currency"] == "HKD"
    assert len(body["options"]) == 2
    assert body["options"][0]["rank"] == 1
    assert "effective_cost" in body["options"][0]


def test_draft_authorize_capture_flow(c):
    draft = c.post(
        "/payment/draft",
        json={
            "account_id": "demo",
            "amount": 59.9,
            "merchant": "Watsons",
            "intent": "cheap toilet paper",
            "sku": "SKU001",
            "qty": 1,
            "rail": "mastercard",
        },
    ).json()
    assert draft["status"] == "DRAFT" and draft["payment_id"].startswith("pay_")
    assert draft["token_jti"].startswith("tok_")
    # token is not in public payload
    assert "token" not in draft

    # fetch full via authorize using stored token server-side
    auth = c.post(
        "/payment/authorize",
        json={"payment_id": draft["payment_id"], "idempotency_key": "k1"},
    ).json()
    assert auth["status"] == "CAPTURED"
    assert auth["order_id"] and auth["receipt_id"]
    assert "captured" in auth["evidence"]

    again = c.post(
        "/payment/authorize",
        json={"payment_id": draft["payment_id"], "idempotency_key": "k1"},
    ).json()
    assert again["status"] == "CAPTURED" and again["order_id"] == auth["order_id"]


def test_decline_666(c):
    draft = c.post(
        "/payment/draft",
        json={"amount": 666.0, "merchant": "Watsons", "sku": "X", "rail": "unionpay"},
    ).json()
    auth = c.post("/payment/authorize", json={"payment_id": draft["payment_id"]}).json()
    assert auth["status"] == "FAILED" and auth["error"] == "card_declined"


def test_refund(c):
    draft = c.post(
        "/payment/draft",
        json={"amount": 72.0, "merchant": "HKTVmall", "sku": "SKU004", "rail": "mastercard"},
    ).json()
    c.post("/payment/authorize", json={"payment_id": draft["payment_id"]})
    ref = c.post(
        f"/payment/{draft['payment_id']}/refund", json={"reason": "changed_mind"}
    ).json()
    assert ref["status"] == "REFUNDED" and "refunded" in ref["evidence"]


def test_token_is_one_time(c):
    from tokens import mint
    from config import settings

    s = settings()
    draft = c.post(
        "/payment/draft",
        json={"amount": 10, "merchant": "Watsons", "sku": "S", "rail": "mastercard"},
    ).json()
    # Burn by authorizing
    c.post("/payment/authorize", json={"payment_id": draft["payment_id"]})
    # Force status back to DRAFT in store to attempt reuse — jti should block
    from main import store

    rec = store.get(draft["payment_id"])
    rec["status"] = "DRAFT"
    store.put(rec)
    bad = c.post("/payment/authorize", json={"payment_id": draft["payment_id"]})
    assert bad.status_code == 409
