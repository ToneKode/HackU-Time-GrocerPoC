import uuid
import pytest
from fastapi import HTTPException
from market_store import DEFAULT_RULES, MarketRules, MarketStore, price_quote
from settlement_verifier import verified_settlement


def product(sku="a", price=300):
    return {"id": sku, "name": sku, "merchant": "Watsons", "category": "Care", "price": price,
            "currency": "HKD", "stock": 20, "in_stock": True}


def test_default_discount_and_gifts_do_not_recurse():
    rules = dict(DEFAULT_RULES, sku_gifts=[{"sku": "a", "gift_sku": "a"}])
    quote = price_quote([{"sku": "a", "qty": 1}], {"a": product()}, rules)
    assert quote["total"] == 285
    assert len(quote["lines"]) == 2
    assert quote["lines"][1]["is_gift"] and quote["lines"][1]["line_total"] == 0
    assert quote['shipping_fee'] == 30
    assert sum(m['total'] for m in quote['merchants']) == quote['total']


def test_snapshot_verified_without_reading_live_rules():
    quote = price_quote([{"sku": "a", "qty": 1}], {"a": product()}, DEFAULT_RULES)
    payment = {"payment_id": "pay_test", "account_id": "alice", "status": "CAPTURED",
               "rail_verified": True, "order_id": "ORD", "receipt_id": "RCPT", "amount": 285,
               "charged": 285, "currency": "HKD", "charged_currency": "HKD",
               "rail": "mastercard", "merchant": "Watsons", "market_quote": quote}
    result = verified_settlement(payment, "alice", "pay_test", 285, "HKD")
    assert result["rules_version"] == 0 and result["discount"] == 45
    quote["total"] = 250
    with pytest.raises(ValueError, match="does not match"):
        verified_settlement(payment, "alice", "pay_test", 285, "HKD")


def test_settlement_saves_server_gifts_ignoring_caller_lines(monkeypatch):
    import main
    rules = dict(DEFAULT_RULES, sku_gifts=[{"sku": "a", "gift_sku": "a"}])
    quote = price_quote([{"sku": "a", "qty": 1}], {"a": product()}, rules)
    payment = {"payment_id": "pay_test", "account_id": "alice", "status": "CAPTURED",
               "rail_verified": True, "order_id": "ORD", "receipt_id": "RCPT", "amount": 285,
               "charged": 285, "currency": "HKD", "charged_currency": "HKD",
               "rail": "mastercard", "merchant": "Watsons", "market_quote": quote}
    writes = []
    monkeypatch.setattr(main, "fetch_payment", lambda *args: payment)
    monkeypatch.setattr(main.profile, "record_paid", lambda *args, **kwargs: writes.append(kwargs) or {"order_id": "ord", "duplicate": True})
    main.settle_order("alice", main.SettleIn(amount=285, payment_id="pay_test", lines=[{"sku": "fake", "qty": 99}]))
    assert writes[0]["lines"] == quote["lines"]
    assert writes[0]["lines"][1]["is_gift"] is True


def test_admin_requires_role_and_password(monkeypatch):
    import main
    monkeypatch.setattr(main.profile, "profile", lambda actor: {"id": actor, "email": "shopper@example.com"})
    with pytest.raises(HTTPException) as exc:
        main.require_admin("user", "whatever")
    assert exc.value.status_code == 403
    monkeypatch.setattr(main.profile, "profile", lambda actor: {"id": actor, "email": main.S["demo_admin_emails"][0]})
    monkeypatch.setattr(main.profile, "authenticate", lambda *args: None)
    with pytest.raises(HTTPException) as exc:
        main.require_admin("admin", None)
    assert exc.value.status_code == 401


def test_mysql_admin_rules_and_live_price(c):
    import main
    email = f"admin-{uuid.uuid4().hex}@example.com"
    password = "MockAdminTest!"
    admin = c.post("/accounts/register", json={"email": email, "password": password, "name": "TEST admin"}).json()
    main.S["demo_admin_emails"].append(email)
    original = main.market.get()
    sku = "market-test-" + uuid.uuid4().hex[:10]
    main.catalog.upsert_many([dict(product(sku, 100))])
    headers = {"X-Admin-Password": password}
    try:
        assert c.put("/admin/market/rules", json={"account_id": admin["id"], "rules": {}}).status_code == 401
        response = c.put("/admin/market/rules", headers=headers, json={"account_id": admin["id"], "rules": {
            "merchant_discounts": [{"merchant": "Watsons", "percent": 20, "threshold": 100}],
            "sku_gifts": [{"sku": sku, "gift_sku": sku}]}})
        assert response.status_code == 200, response.text
        version = response.json()["version"]
        assert c.get("/market/rules").json()["version"] == version
        promotions = [{"route": "mastercard", "kind": "cash", "rate": 0.05, "enabled": True}]
        saved = c.put("/admin/market/rules", headers=headers, json={"account_id": admin["id"], "rules": {
            **response.json(), "payment_promotions": promotions}})
        assert saved.status_code == 200, saved.text
        assert saved.json()["version"] == version + 1
        assert c.get("/market/rules").json()["payment_promotions"][0]["rate"] == 0.05
        assert MarketStore(main.market.database_url).get() == saved.json()
        assert c.patch(f"/admin/catalog/{sku}", headers=headers, json={"account_id": admin["id"], "price": 120}).json()["price"] == 120
        quote = c.post("/market/quote", json={"lines": [{"sku": sku, "qty": 1}]}).json()
        assert quote["total"] == 126 and quote["lines"][1]["line_total"] == 0
    finally:
        main.market.put(original, admin["id"])
        main.S["demo_admin_emails"].remove(email)


@pytest.mark.parametrize("rate", [-0.01, float("inf"), float("nan")])
def test_payment_promotion_rejects_invalid_rate(rate):
    with pytest.raises(ValueError):
        MarketRules(payment_promotions=[{"route": "mastercard", "kind": "cash", "rate": rate}])


def test_payment_promotion_defaults_and_duplicate_validation():
    assert MarketRules().model_dump()["payment_promotions"] == DEFAULT_RULES["payment_promotions"]
    assert MarketRules(payment_promotions=[]).payment_promotions == []
    with pytest.raises(ValueError, match="Only one payment promotion"):
        MarketRules(payment_promotions=[{"route": "visa", "kind": "cash", "rate": 0.1}] * 2)


def promotion_payment(rules, merchant="Watsons", route="mastercard", price=300):
    quote = price_quote([{"sku": "a", "qty": 1}], {"a": dict(product(price=price), merchant=merchant)}, rules)
    return {"payment_id": "pay_promotions", "account_id": "alice", "status": "CAPTURED",
            "rail_verified": True, "order_id": "ORD", "receipt_id": "RCPT", "amount": quote["total"],
            "charged": quote["total"], "currency": "HKD", "charged_currency": "HKD",
            "rail": route, "merchant": merchant, "market_quote": quote}


def reward_amounts(payment):
    result = verified_settlement(payment, "alice", payment["payment_id"], payment["amount"], "HKD")
    return {b["kind"]: b["amount"] for b in result["benefits"]}


def test_custom_promotions_use_frozen_discounted_goods_not_shipping():
    rules = dict(DEFAULT_RULES, version=12, payment_promotions=[
        {"route": "mastercard", "kind": "cash", "rate": 0.05, "enabled": True},
        {"route": "mastercard", "kind": "asiamiles", "rate": 0.1, "enabled": True},
        {"route": "visa", "kind": "cash", "rate": 1, "enabled": True}])
    payment = promotion_payment(rules)
    rules["payment_promotions"][0]["rate"] = 99
    assert reward_amounts(payment) == {"cash": 12.75, "asiamiles": 25.5}
    assert payment["market_quote"]["rules_version"] == 12


def test_empty_promotions_disable_rewards_and_legacy_snapshots_keep_defaults():
    assert reward_amounts(promotion_payment(dict(DEFAULT_RULES, payment_promotions=[]))) == {}
    legacy = {k: v for k, v in DEFAULT_RULES.items() if k != "payment_promotions"}
    assert reward_amounts(promotion_payment(legacy)) == {"membership_points": 510, "cash": 6.12}


def test_merchant_specific_rewards_override_general_and_disabled_rules():
    rules = dict(DEFAULT_RULES, payment_promotions=[
        {"route": "mastercard", "kind": "cash", "rate": 0.2, "merchant": "Watsons", "enabled": False},
        {"route": "mastercard", "kind": "cash", "rate": 0.05, "enabled": True},
        {"route": "mastercard", "kind": "asiamiles", "rate": 0.1, "merchant": "Watsons", "enabled": True}])
    assert reward_amounts(promotion_payment(rules)) == {"asiamiles": 25.5}
    assert reward_amounts(promotion_payment(rules, merchant="HKTVmall")) == {"cash": 15}


def test_full_discount_can_produce_zero_rewards():
    rules = dict(DEFAULT_RULES, merchant_discounts=[{"merchant": "Watsons", "percent": 100, "threshold": 0}])
    assert reward_amounts(promotion_payment(rules)) == {"membership_points": 0, "cash": 0}


def test_split_promotions_use_each_merchants_frozen_goods_total():
    rules = dict(DEFAULT_RULES, version=15, payment_promotions=[
        {"route": "mastercard", "kind": "cash", "rate": 0.05, "enabled": True},
        {"route": "mastercard", "kind": "asiamiles", "rate": 0.1, "enabled": True}])
    products = {"a": product(price=300), "b": dict(product("b", 50), merchant="HKTVmall")}
    quote = price_quote([{"sku": "a", "qty": 1}, {"sku": "b", "qty": 1}], products, rules)
    children = []
    for index, row in enumerate(quote["merchants"]):
        child = promotion_payment(rules)
        child.update(payment_id=f"pay_child_{index}", merchant=row["merchant"], amount=row["total"],
                     charged=row["total"], market_quote=quote, market_merchant=row["merchant"])
        children.append(child)
    parent = dict(children[0], payment_id="pay_basket", rail="split", merchant="Watsons, HKTVmall",
                  amount=quote["total"], charged=quote["total"], market_merchant=None,
                  children=[child["payment_id"] for child in children], captures=children,
                  allocations=[{"merchant": child["merchant"], "rail": child["rail"], "amount": child["amount"]}
                               for child in children])
    result = verified_settlement(parent, "alice", "pay_basket", parent["amount"], "HKD")
    assert [{b["kind"]: b["amount"] for b in child["benefits"]} for child in result["allocations"]] == [
        {"cash": 12.75, "asiamiles": 25.5}, {"cash": 2.5, "asiamiles": 5}]


def test_legacy_stored_rules_return_full_schema_without_changing_version():
    import json
    class Cursor:
        def execute(self, query):
            pass

        def fetchone(self):
            return {"version": 8, "rules_json": json.dumps({"merchant_discounts": [], "sku_gifts": []})}

    result = MarketStore("unused")._read(Cursor())
    assert result == {"version": 8, **MarketRules().model_dump()}
