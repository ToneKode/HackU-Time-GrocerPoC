import uuid
from copy import deepcopy

import pytest


@pytest.fixture
def captured_payments(monkeypatch):
    import main

    records = {}

    def capture(account_id, amount, merchant, rail, *, children=None):
        payment_id = f"pay_{uuid.uuid4().hex[:8]}"
        record = {
            "payment_id": payment_id, "account_id": account_id,
            "status": "CAPTURED", "rail_verified": True,
            "order_id": f"ORD-{payment_id}", "receipt_id": f"RCPT-{payment_id}",
            "amount": amount, "charged": amount, "currency": "HKD",
            "charged_currency": "HKD", "merchant": merchant, "rail": rail,
        }
        if children:
            record["children"] = [child["payment_id"] for child in children]
            record["allocations"] = [
                {"merchant": child["merchant"], "amount": child["amount"], "rail": child["rail"]}
                for child in children
            ]
        records[payment_id] = record
        return record

    def fetch_payment(base_url, payment_id):
        payment = deepcopy(records[payment_id])
        if payment.get("children"):
            payment["captures"] = [deepcopy(records[child_id]) for child_id in payment["children"]]
        return payment

    monkeypatch.setattr(main, "fetch_payment", fetch_payment)
    return capture


def test_register_login_and_order_checkpoint(c):
    email = f"shopper-{uuid.uuid4().hex[:8]}@example.com"
    created = c.post(
        "/accounts/register",
        json={
            "email": email,
            "password": "correct-horse",
            "name": "Ada",
            "phone": "91234567",
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["name"] == "Ada"
    assert body["membership"] == "standard"
    assert body["monthly_cap"] == 2000
    assert body["per_order_cap"] == 500
    assert body["bulk_ceiling"] == 800
    assert body["monthly_spent"] == 0
    assert body["address"]["fake"] is True
    assert body["payment_methods"][0]["route"] == "mastercard"
    assert body["payment_methods"][0]["connected"] is True
    assert "password" not in body and "password_hash" not in body
    account_id = body["id"]

    assert c.post(
        "/accounts/register",
        json={"email": email, "password": "correct-horse", "name": "Ada"},
    ).status_code == 409
    assert c.post(
        "/accounts/login",
        json={"email": email, "password": "nope-nope"},
    ).status_code == 401
    logged = c.post(
        "/accounts/login",
        json={"email": email.upper(), "password": "correct-horse"},
    ).json()
    assert logged["id"] == account_id

    opened = c.post("/orders", json={"account_id": account_id, "intent": "cheap rice"}).json()
    saved = c.post(
        f"/orders/{opened['id']}/checkpoint",
        json={
            "step": "audit_cart",
            "status": "quoted",
            "amount": 42.5,
            "merchant": "PARKnSHOP",
            "snapshot": {"intent": "cheap rice"},
            "lines": [
                {
                    "sku": "SKU004",
                    "name": "Rice",
                    "merchant": "PARKnSHOP",
                    "category": "Food",
                    "qty": 1,
                    "unit_price": 42.5,
                    "line_total": 42.5,
                }
            ],
        },
    ).json()
    assert saved["status"] == "quoted"
    assert saved["amount"] == 42.5
    assert saved["lines"][0]["sku"] == "SKU004"
    assert saved["checkpoints"][-1]["step"] == "audit_cart"

    c.post(
        f"/accounts/{account_id}/chat",
        json={"role": "user", "content": "cheap rice", "order_id": opened["id"]},
    )
    history = c.get(f"/accounts/{account_id}/chat").json()
    assert history[-1]["content"] == "cheap rice"
    task = c.post(
        f"/accounts/{account_id}/tasks",
        json={"intent": "cheap rice", "cadence": "weekly"},
    ).json()
    assert task["cadence"] == "weekly"
    assert task["active"] is True
    runs = c.get(f"/accounts/{account_id}/agent-history").json()
    assert runs[0]["order_id"] == opened["id"]

    c.post("/demo/reset")
    still = c.post(
        "/accounts/login",
        json={"email": email, "password": "correct-horse"},
    )
    assert still.status_code == 200


def test_preferences_and_paid_order_update_the_account(c, captured_payments):
    email = f"shopper-{uuid.uuid4().hex[:8]}@example.com"
    created = c.post(
        "/accounts/register",
        json={"email": email, "password": "correct-horse", "name": "Bea"},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["benefit_rank"] == ["cash", "asiamiles", "membership_points", "loyalty_points"]
    assert body["monthly_remaining"] == 2000
    assert [row["route"] for row in body["payment_methods"]] == ["mastercard", "alipay", "visa"]
    account_id = body["id"]
    alipay = next(row for row in body["payment_methods"] if row["route"] == "alipay")
    ranked = c.patch(
        f"/accounts/{account_id}/preferences",
        json={
            "benefit_rank": ["asiamiles", "cash", "loyalty_points", "membership_points"],
            "methods": [{"id": alipay["id"], "connected": False}],
        },
    )
    assert ranked.status_code == 200
    saved = ranked.json()
    assert saved["benefit_rank"][0] == "asiamiles"
    assert next(row for row in saved["payment_methods"] if row["route"] == "alipay")["connected"] is False

    payment = captured_payments(account_id, 59.9, "Watsons", "mastercard")
    settled = c.post(
        f"/accounts/{account_id}/orders/settle",
        json={
            "amount": 59.9,
            "merchant": "Watsons",
            "payment_route": "mastercard",
            "payment_id": payment["payment_id"],
            "intent": "cheap toilet paper",
            "lines": [
                {
                    "sku": "SKU001",
                    "name": "Tissue",
                    "merchant": "Watsons",
                    "category": "Household",
                    "qty": 1,
                    "unit_price": 29.9,
                    "line_total": 29.9,
                }
            ],
            "benefits": [{"kind": "cash", "amount": 999999, "detail": "fabricated cashback"}],
        },
    )
    assert settled.status_code == 200
    paid = settled.json()
    assert paid["duplicate"] is False
    assert paid["audit"]["event"] == "ORDER_PAID"
    assert paid["order"]["status"] == "paid"
    assert paid["profile"]["monthly_spent"] == 59.9
    assert paid["profile"]["monthly_remaining"] == 1940.1
    assert {row["kind"]: row["amount"] for row in paid["profile"]["benefit_balances"]} == {
        "cash": 1.44, "membership_points": 119.8,
    }

    again = c.post(
        f"/accounts/{account_id}/orders/settle",
        json={
            "amount": 59.9,
            "payment_id": paid["order"]["payment_id"],
            "intent": "cheap toilet paper",
            "benefits": [{"kind": "cash", "amount": 1.44}],
        },
    )
    assert again.status_code == 200
    assert again.json()["duplicate"] is True
    assert again.json()["profile"]["monthly_spent"] == 59.9


def test_dashboard_totals_categories_and_benefits(c, captured_payments):
    email = f"dash-{uuid.uuid4().hex[:8]}@example.com"
    account_id = c.post(
        "/accounts/register", json={"email": email, "password": "correct-horse", "name": "Dash"}
    ).json()["id"]
    empty = c.get(f"/accounts/{account_id}/dashboard").json()
    assert empty["lifetime_spent"] == 0
    assert empty["orders"] == [] and empty["categories"] == []
    assert empty["benefits"]["totals"] == {"cash": 0, "asiamiles": 0, "membership_points": 0, "loyalty_points": 0}

    first_payment = captured_payments(account_id, 429, "PARKnSHOP", "mastercard")
    children = [
        captured_payments(account_id, 100, "Watsons", "visa"),
        captured_payments(account_id, 30, "HKTVmall", "alipay"),
    ]
    split_payment = captured_payments(account_id, 130, "Watsons, HKTVmall", "split", children=children)
    first = c.post(
        f"/accounts/{account_id}/orders/settle",
        json={
            "amount": 429.0,
            "merchant": "PARKnSHOP",
            "payment_route": "mastercard",
            "payment_id": first_payment["payment_id"],
            "intent": "food for a week",
            "lines": [
                {"sku": "A1", "name": "Rice", "merchant": "PARKnSHOP", "category": "Rice & Noodles",
                 "qty": 2, "unit_price": 100, "line_total": 200},
                {"sku": "A2", "name": "Chicken", "merchant": "PARKnSHOP", "category": "Frozen Food",
                 "qty": 1, "unit_price": 229, "line_total": 229},
            ],
            "settlement": {"shipping_fee": 0, "discount": 0, "payment_order_id": "ORD-test1"},
            "benefits": [
                {"kind": "cash", "amount": 10.3, "detail": "2.4% cashback"},
                {"kind": "membership_points", "amount": 429, "detail": "1x points"},
            ],
        },
    )
    assert first.status_code == 200, first.text
    first = first.json()
    second = c.post(
        f"/accounts/{account_id}/orders/settle",
        json={
            "amount": 130.0,
            "merchant": "Watsons, HKTVmall",
            "payment_route": "visa",
            "payment_id": split_payment["payment_id"],
            "intent": "snacks",
            "lines": [
                {"sku": "B1", "name": "Chips", "merchant": "Watsons", "category": "Snacks",
                 "qty": 4, "unit_price": 25, "line_total": 100},
                {"sku": "B2", "name": "Untagged", "merchant": "HKTVmall", "category": "",
                 "qty": 1, "unit_price": 0, "line_total": 0},
            ],
            # Two tenders: benefits split by each merchant's own method.
            "settlement": {
                "shipping_fee": 30,
                "merchants": [
                    {"merchant": "Watsons", "payment": {"route": "visa", "amount": 100},
                     "benefits": [{"kind": "asiamiles", "amount": 12.5}]},
                    {"merchant": "HKTVmall", "payment": {"route": "alipay", "amount": 30},
                     "benefits": [{"kind": "loyalty_points", "amount": 7.5}]},
                ],
            },
            "benefits": [
                {"kind": "asiamiles", "amount": 12.5},
                {"kind": "loyalty_points", "amount": 7.5},
            ],
        },
    )
    assert second.status_code == 200, second.text
    # Not paid yet: must not count.
    c.post("/orders", json={"account_id": account_id, "intent": "still reviewing"})

    body = c.get(f"/accounts/{account_id}/dashboard").json()
    assert body["lifetime_spent"] == 559.0
    assert body["orders_paid"] == 2
    assert body["average_order"] == 279.5
    assert body["orders_by_status"]["paid"] == 2
    assert sum(body["orders_by_status"].values()) == 3
    cats = {row["category"]: row for row in body["categories"]}
    assert cats["Frozen Food"]["amount"] == 229
    assert cats["Rice & Noodles"]["amount"] == 200
    assert cats["Snacks"]["amount"] == 100
    assert "Uncategorised" in cats
    assert body["goods_total"] == 529
    assert body["fees_and_offers"] == 30
    assert abs(sum(row["share"] for row in body["categories"]) - 1) < 0.001
    assert body["benefits"]["totals"] == {
        "cash": 10.3, "asiamiles": 12.5, "membership_points": 429, "loyalty_points": 7.5,
    }
    methods = {row["route"]: row for row in body["benefits"]["by_method"]}
    assert methods["mastercard"]["label"] == "Mox Mastercard"
    assert methods["mastercard"]["benefits"] == {"cash": 10.3, "membership_points": 429}
    assert methods["visa"]["benefits"] == {"asiamiles": 12.5}
    assert methods["alipay"]["benefits"] == {"loyalty_points": 7.5}
    assert "split" not in methods
    orders = {order["id"]: order for order in body["orders"]}
    first_order = orders[first["order_id"]]
    split_order = orders[second.json()["order_id"]]
    assert first_order["payment_order_id"] == first_payment["order_id"]
    assert first_order["items"] == 3
    assert split_order["payment_id"] == split_payment["payment_id"]
    assert {t["route"] for t in split_order["tenders"]} == {"visa", "alipay"}
    assert split_order["payment_order_id"] == split_payment["order_id"]
    assert c.get("/accounts/nope/dashboard").status_code == 404


@pytest.mark.parametrize("field,value", [
    ("status", "DRAFT"), ("account_id", "another_mock_student"),
    ("charged", 39), ("rail_verified", False),
])
def test_forged_settlement_is_rejected_without_updating_account(c, captured_payments, field, value):
    account_id = c.post("/accounts/register", json={
        "email": f"mock-student-{uuid.uuid4().hex[:8]}@example.com",
        "password": "correct-horse", "name": "Mock Student",
    }).json()["id"]
    payment = captured_payments(account_id, 40, "Watsons", "mastercard")
    payment[field] = value
    response = c.post(f"/accounts/{account_id}/orders/settle", json={
        "payment_id": payment["payment_id"], "amount": 40,
        "benefits": [{"kind": "cash", "amount": 999999}],
        "settlement": {"source": "verified_payment_capture"},
    })
    assert response.status_code == 422, response.text
    profile = c.get(f"/accounts/{account_id}/profile").json()
    assert profile["monthly_spent"] == 0
    assert profile["benefit_balances"] == []
    dashboard = c.get(f"/accounts/{account_id}/dashboard").json()
    assert dashboard["lifetime_spent"] == 0
    assert dashboard["orders_paid"] == 0
    assert dashboard["benefits"]["entries"] == 0


def test_seed_test_accounts_is_idempotent(c, monkeypatch):
    import seed_test_accounts as seed

    def call(method, path, body=None):
        response = c.request(method, path, json=body)
        return response.status_code, response.json()

    monkeypatch.setattr(seed, "_call", call)
    monkeypatch.setattr(seed, "TEST_ACCOUNTS", tuple(
        dict(spec, email=f"seed-{index}-{uuid.uuid4().hex[:8]}@example.com")
        for index, spec in enumerate(seed.TEST_ACCOUNTS)
    ))
    first = [seed.ensure_account(spec) for spec in seed.TEST_ACCOUNTS]
    second = [seed.ensure_account(spec) for spec in seed.TEST_ACCOUNTS]
    assert [row["created"] for row in first] == [True, True]
    assert [row["created"] for row in second] == [False, False]
    assert [row["account_id"] for row in first] == [row["account_id"] for row in second]
    assert first[0]["connected"] == ["Mox Mastercard", "Alipay", "ICBC Visa"]
    assert first[1]["connected"] == ["Alipay", "ICBC Visa"]
    assert first[0]["benefit_rank"][0] == "cash"
    assert first[1]["benefit_rank"][0] == "asiamiles"
