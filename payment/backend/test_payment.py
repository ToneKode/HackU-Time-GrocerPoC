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
    auth = c.post(
        "/payment/authorize",
        json={"payment_id": draft["payment_id"], "step_up_confirmed": True},
    ).json()
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


def test_step_up_blocks_until_confirmed(c):
    draft = c.post(
        "/payment/draft",
        json={"amount": 420.0, "merchant": "Watsons", "sku": "SKU001", "rail": "unionpay"},
    ).json()
    assert draft["step_up_required"] is True
    assert draft["risk_score"] >= 50
    blocked = c.post("/payment/authorize", json={"payment_id": draft["payment_id"]})
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "step_up_required"
    auth = c.post(
        "/payment/authorize",
        json={"payment_id": draft["payment_id"], "step_up_confirmed": True},
    ).json()
    assert auth["status"] == "CAPTURED"
    assert "step_up_confirmed" in auth["evidence"]


def test_small_payment_does_not_step_up(c):
    draft = c.post(
        "/payment/draft",
        json={"amount": 59.9, "merchant": "Watsons", "sku": "SKU001", "rail": "mastercard"},
    ).json()
    assert draft["step_up_required"] is False
    assert draft["risk_score"] < 50


def test_evidence_pack_omits_token(c):
    draft = c.post(
        "/payment/draft",
        json={"amount": 72.0, "merchant": "HKTVmall", "sku": "SKU004", "rail": "mastercard"},
    ).json()
    c.post("/payment/authorize", json={"payment_id": draft["payment_id"]})
    c.post(f"/payment/{draft['payment_id']}/refund", json={"reason": "not_received"})
    pack = c.get(f"/payment/{draft['payment_id']}/evidence").json()
    assert pack["pack_id"] == "ev_" + draft["payment_id"]
    assert pack["status"] == "REFUNDED"
    assert pack["refund_reason"] == "not_received"
    assert "refunded" in pack["evidence"]
    assert "token" not in pack
    assert pack["merchant"] == "HKTVmall"


def test_remote_acquirer_is_posted(c, monkeypatch):
    import json

    import httpx

    from rails import charge_remote

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path == "/pay"
        assert body["payment_route"] == "unionpay"
        assert body["cart_total"] == 40.0
        return httpx.Response(
            200,
            json={
                "success": True,
                "order_id": "ORD-mall01",
                "charged": body["cart_total"],
                "currency": "HKD",
                "payment_route": body["payment_route"],
                "reward_points_earned": 4,
                "ts": "2026-10-03T00:00:00Z",
                "error": None,
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://mall")
    remote = charge_remote("http://mall", 40, "unionpay", "idem-1", client=client)
    assert remote["success"] is True
    assert remote["order_id"] == "ORD-mall01"
    assert remote["auth_id"] == "AUTH-ORD-mall01"

    monkeypatch.setitem(__import__("main").S, "mock_acquirer_url", "http://mall")
    monkeypatch.setattr("rails.charge_remote", lambda *args, **kwargs: remote)
    draft = c.post(
        "/payment/draft",
        json={"amount": 40.0, "merchant": "Watsons", "sku": "S", "rail": "mastercard"},
    ).json()
    auth = c.post("/payment/authorize", json={"payment_id": draft["payment_id"]}).json()
    assert auth["status"] == "CAPTURED"
    assert auth["order_id"] == "ORD-mall01"


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


def test_recommend_uses_agent_brain_rates(c):
    """The draft estimate agrees with agent-brain benefits.py (Mox Mastercard 2.4%)."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent-brain" / "backend"))
    from benefits import INSTRUMENTS

    rate = next(row["cashback"] for row in INSTRUMENTS if row["route"] == "mastercard")
    body = c.post("/payment/recommend", json={"amount": 499.3}).json()
    card = next(row for row in body["options"] if row["rail"] == "mastercard")
    assert card["cashback_rate"] == rate == 0.024
    assert card["cashback"] == 11.98
    union = next(row for row in body["options"] if row["rail"] == "unionpay")
    assert union["cashback"] == 0.0  # agent-brain gives this rail no benefit
