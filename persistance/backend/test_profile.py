import uuid


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


def test_preferences_and_paid_order_update_the_account(c):
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

    settled = c.post(
        f"/accounts/{account_id}/orders/settle",
        json={
            "amount": 59.9,
            "merchant": "Watsons",
            "payment_route": "mastercard",
            "payment_id": f"pay_{uuid.uuid4().hex[:8]}",
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
            "benefits": [{"kind": "cash", "amount": 1.44, "detail": "2.4% cashback"}],
        },
    )
    assert settled.status_code == 200
    paid = settled.json()
    assert paid["duplicate"] is False
    assert paid["audit"]["event"] == "ORDER_PAID"
    assert paid["order"]["status"] == "paid"
    assert paid["profile"]["monthly_spent"] == 59.9
    assert paid["profile"]["monthly_remaining"] == 1940.1
    assert paid["profile"]["benefit_balances"] == [{"kind": "cash", "amount": 1.44}]

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
