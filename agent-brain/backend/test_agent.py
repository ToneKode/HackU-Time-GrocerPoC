"""Shelf picks against fake_mall JSON. Policy uses person 2's rules offline."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from agent_graph import ShoppingAgent, parse_goal
from basket import choose_best_merchant, choose_payment, fit_basket, needs_from
from clients import PolicyClient
from fake_mall import FileMall
from openrouter import OpenRouterPlanner, PlannerError, parse_decision
from pick import planner_shelf, resolve_pick
from policy_rules import decide
from server import create_app

GENESIS = "0" * 64


def scripted(intent: str, catalog: list[dict]) -> dict:
    text = intent.casefold()
    qty = 1
    if "2 " in text or text.startswith("2"):
        qty = 2
    if "toilet" in text:
        sell = "best_rating" if "best" in text else "highest_usage" if "everyday" in text else "cheap"
        sku = {"cheap": "SKU001", "highest_usage": "SKU002", "best_rating": "SKU003"}[sell]
        return {
            "query": "toilet paper",
            "qty": qty,
            "sell_point": sell,
            "sku": sku,
            "thought": f"Toilet paper, {sell}.",
            "model": "scripted",
        }
    if "earbud" in text:
        return {
            "query": "earbuds",
            "qty": 1,
            "sell_point": "best_rating",
            "sku": "SKU025",
            "thought": "They asked for the best rated earbuds.",
            "model": "scripted",
        }
    if "rice" in text:
        return {
            "query": "rice",
            "qty": 1,
            "sell_point": "highest usage",
            "sku": "SKU005",
            "thought": "Everyday rice is the highest-usage bag.",
            "model": "scripted",
        }
    if "shampoo" in text:
        return {
            "query": "shampoo",
            "qty": qty,
            "sell_point": "best_rating",
            "sku": "SKU018",
            "thought": "Two bottles of the best rated shampoo.",
            "model": "scripted",
        }
    return {
        "query": "spaceship",
        "qty": 1,
        "sell_point": "cheap",
        "sku": "",
        "thought": "Nothing on the shelf matches.",
        "model": "scripted",
    }


def client() -> tuple[TestClient, PolicyClient]:
    policy = PolicyClient(offline=True)
    app = create_app(ShoppingAgent(FileMall(), policy, scripted))
    return TestClient(app), policy


def basket_lines(body: dict) -> list[dict]:
    if body.get("lines"):
        return [{"sku": line["sku"], "qty": line["qty"]} for line in body["lines"]]
    return [{"sku": body["product"]["id"], "qty": body["goal"]["qty"]}]


def approve_reviewed(api: TestClient, body: dict) -> tuple[dict, dict]:
    confirmed = api.post(
        "/agent/basket/confirm",
        json={"intent": body["intent"], "monthly_spent": 0, "lines": basket_lines(body)},
    ).json()
    assert confirmed["status"] == "READY", confirmed.get("reply")
    assert confirmed["payment"] is None
    merchant = confirmed["settlement"]["merchants"][0]
    paid = api.post(
        "/agent/basket/approve",
        json={
            "amount": confirmed["settlement"]["total"],
            "payment_route": merchant["payment"]["route"] or "mastercard",
            "merchant": merchant["merchant"],
        },
    ).json()
    return confirmed, paid


def assert_chain(entries: list[dict]) -> None:
    previous = GENESIS
    for entry in entries:
        material = "|".join(
            [
                str(entry["index"]),
                entry["ts"],
                entry["event"],
                entry["status"],
                entry["reason"],
                entry["prev_hash"],
            ]
        )
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
        assert entry["prev_hash"] == previous
        assert entry["hash"] == digest
        previous = entry["hash"]


def events(body: dict) -> list[str]:
    return [entry["event"] for entry in body["audit_log"]]


def test_policy_rules() -> None:
    passed = decide("Watsons", "Household", 119.9, 0)
    assert passed["status"] == "PASS"
    assert passed["rule"] == "pass"
    assert passed["monthly_remaining"] == 1880.1
    halted = decide("Watsons", "Household", 119.9, 1900)
    assert halted["status"] == "HALT"
    assert halted["reason"] == "Over HK$2000 monthly cap"
    assert halted["rule"] == "monthly_cap"
    assert decide("DarkWebMart", "Household", 10, 0)["reason"] == "Merchant blacklisted"
    food = decide("PARKnSHOP", "Food", 42, 0)
    assert food["status"] == "PASS"
    assert food["rule"] == "pass"
    assert decide("Japan Home Centre", "Electronics", 698, 0)["status"] == "ESCALATE"
    assert decide("watsons", "Health", 29, 0)["status"] == "PASS"
    escalate = decide("Japan Home Centre", "Personal Care", 560, 0)
    assert escalate["status"] == "ESCALATE"
    assert escalate["rule"] == "over_per_transaction_cap"
    assert escalate["reason"] == "Over HK$500 per-transaction cap"


def test_goal_parser() -> None:
    assert parse_goal("Buy toilet paper") == {
        "intent": "Buy toilet paper",
        "query": "toilet",
        "qty": 1,
    }


def test_catalog_shape() -> None:
    products = FileMall().products
    categories = {item["category"] for item in products}
    assert len(products) == 30
    assert len(categories) == 10
    for category in categories:
        points = [item["sell_point"] for item in products if item["category"] == category]
        assert sorted(points) == ["best_rating", "cheap", "highest_usage"]


def test_sell_point_overrides_a_wrong_sku() -> None:
    catalog = FileMall().products
    cheap = resolve_pick(
        catalog,
        {"query": "toilet paper", "sell_point": "cheap", "sku": "SKU003"},
    )
    assert cheap["id"] == "SKU001"
    rated = resolve_pick(
        catalog,
        {"query": "earbuds", "sell_point": "best_rating", "sku": "SKU025"},
    )
    assert rated["id"] == "SKU027"
    assert resolve_pick(catalog, {"query": "spaceship", "sell_point": "cheap", "sku": ""}) is None


def test_cheap_toilet_paper_passes_and_pays() -> None:
    api, _policy = client()
    response = api.post("/agent/intent", json={"intent": "cheap toilet paper", "monthly_spent": 0})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "READY"
    assert body["goal"]["sell_point"] == "cheap"
    assert body["goal"]["model"] == "scripted"
    assert body["product"]["id"] == "SKU001"
    assert body["product"]["sell_point"] == "cheap"
    assert body["quote"]["shipping_fee"] == 30
    assert body["quote"]["total_landed_cost"] == 59.9
    assert body["policy"]["status"] == "PASS"
    assert body["policy"]["reason"] == "Under HK$500 cap"
    assert body["policy"]["rule"] == "pass"
    assert body["policy"]["monthly_remaining"] == 1940.1
    assert body["escalation"] is None
    assert body["payment"] is None
    assert body["settlement"]["total"] == 59.9
    assert events(body) == [
        "INTENT_RECEIVED",
        "PLAN",
        "SEARCH",
        "CART_PRICED",
        "POLICY_CHECK",
        "BASKET_REVIEW",
    ]
    assert body["audit_log"][4]["status"] == "PASS"
    policy_step = next(step for step in body["react"] if step["action"] == "POLICY_CHECK")
    assert policy_step["source"] == "agent"
    assert "checked pass passed" in policy_step["thought"]
    assert "PASS" in policy_step["observation"]
    assert "pass" in policy_step["observation"]
    assert body["audit_log"][4]["result"]["status"] == "PASS"
    assert body["audit_log"][4]["result"]["rule"] == "pass"
    assert body["audit_log"][4]["result"]["amount"] == 59.9
    assert body["audit_log"][4]["result"]["monthly_remaining"] == 1940.1
    assert body["audit_log"][4]["result"]["per_transaction_cap"] == 500
    assert "checked pass passed" in body["audit_log"][4]["thought"]
    assert body["audit_log"][-1]["status"] == "READY"
    assert_chain(body["audit_log"])
    _confirmed, paid = approve_reviewed(api, body)
    assert paid["success"] is True
    assert paid["charged"] == 59.9
    assert "reward_points_earned" not in paid


def test_monthly_cap_halts_before_pay() -> None:
    api, _policy = client()
    body = api.post("/agent/intent", json={"intent": "cheap toilet paper", "monthly_spent": 1950}).json()
    assert body["status"] == "HALTED"
    assert body["product"]["id"] == "SKU001"
    assert body["policy"]["status"] == "HALT"
    assert body["policy"]["reason"] == "Over HK$2000 monthly cap"
    assert body["policy"]["rule"] == "monthly_cap"
    assert body["policy"]["monthly_remaining"] == 50
    assert body["payment"] is None
    assert events(body)[-1] == "HALTED"
    assert_chain(body["audit_log"])


def test_best_rated_earbuds_escalate_and_everyday_rice_pays() -> None:
    api, _policy = client()
    earbuds = api.post("/agent/intent", json={"intent": "best rated earbuds"}).json()
    assert earbuds["status"] == "ESCALATED"
    assert earbuds["product"]["id"] == "SKU027"
    assert earbuds["product"]["sell_point"] == "best_rating"
    assert earbuds["quote"]["shipping_fee"] == 0
    assert earbuds["quote"]["total_landed_cost"] == 698.0
    assert earbuds["policy"]["status"] == "ESCALATE"
    assert earbuds["policy"]["rule"] == "over_per_transaction_cap"
    assert earbuds["payment"] is None
    assert earbuds["escalation"]["amount"] == 698.0
    assert events(earbuds)[-1] == "ESCALATION_CREATED"
    assert_chain(earbuds["audit_log"])
    rice = api.post("/agent/intent", json={"intent": "everyday rice"}).json()
    assert rice["status"] == "READY"
    assert rice["product"]["id"] == "SKU005"
    assert rice["goal"]["sell_point"] == "highest_usage"
    assert rice["quote"]["total_landed_cost"] == 98.0
    assert rice["policy"]["status"] == "PASS"
    assert rice["payment"] is None
    _confirmed, paid = approve_reviewed(api, rice)
    assert paid["charged"] == 98.0


def test_shampoo_escalates_then_pays_when_approved() -> None:
    api, policy = client()
    body = api.post("/agent/intent", json={"intent": "2 best rated shampoo"}).json()
    assert body["status"] == "ESCALATED"
    assert body["product"]["id"] == "SKU018"
    assert body["product"]["merchant"] == "Japan Home Centre"
    assert body["quote"]["shipping_fee"] == 0
    assert body["quote"]["total_landed_cost"] == 560.0
    assert body["policy"]["status"] == "ESCALATE"
    assert body["policy"]["rule"] == "over_per_transaction_cap"
    assert body["payment"] is None
    assert body["escalation"]["status"] == "PENDING"
    assert body["escalation"]["amount"] == 560.0
    assert events(body)[-1] == "ESCALATION_CREATED"
    assert_chain(body["audit_log"])
    escalation_id = body["escalation"]["escalation_id"]
    policy.memory[escalation_id]["status"] = "APPROVED"
    resumed = api.post(
        "/agent/intent",
        json={"intent": "2 best rated shampoo", "escalation_id": escalation_id},
    ).json()
    assert resumed["status"] == "COMPLETED"
    assert resumed["payment"]["success"] is True
    assert resumed["payment"]["charged"] == 560.0
    assert events(resumed) == ["PAYMENT"]
    assert_chain(resumed["audit_log"])


def test_unknown_request_is_logged_and_does_not_pay() -> None:
    api, _policy = client()
    body = api.post("/agent/intent", json={"intent": "a spaceship"}).json()
    assert body["status"] == "FAILED"
    assert body["payment"] is None
    assert events(body) == ["INTENT_RECEIVED"]
    assert body["audit_log"][-1]["reason"] == "No product matched"
    assert_chain(body["audit_log"])


def test_missing_openrouter_key_is_logged() -> None:
    policy = PolicyClient(offline=True)
    agent = ShoppingAgent(FileMall(), policy, OpenRouterPlanner(api_key=""))
    body = agent.run("cheap toilet paper", 0, None)
    assert body["status"] == "FAILED"
    assert body["audit_log"][-1]["reason"] == "OPENROUTER_API_KEY is not set"
    assert_chain(body["audit_log"])


def test_openrouter_json_parse() -> None:
    decision = parse_decision('```json\n{"query":"rice","qty":1,"sell_point":"cheap","sku":"SKU004","thought":"Cheap rice."}\n```')
    assert decision["sku"] == "SKU004"
    try:
        OpenRouterPlanner(api_key="").__call__("rice", [])
    except PlannerError as exc:
        assert "OPENROUTER_API_KEY" in str(exc)
    else:
        raise AssertionError("missing key should fail")
    try:
        OpenRouterPlanner(api_key="test", model="deepseek/deepseek-v4.1-flash:batch").__call__("rice", [])
    except PlannerError as exc:
        assert "batch-only" in str(exc)
        assert "deepseek/deepseek-v4.1-flash" in str(exc)
    else:
        raise AssertionError("batch model should fail before the request")


def _shelf_item(sku: str, name: str, price: float, merchant: str, sell: str) -> dict:
    return {
        "id": sku,
        "name": name,
        "price": price,
        "currency": "HKD",
        "merchant": merchant,
        "category": "Household",
        "stock": 20,
        "image_url": "",
        "sell_point": sell,
    }


def _quote_shelf(catalog: list[dict], items: list[dict]) -> dict:
    by_id = {item["id"]: item for item in catalog}
    lines = []
    for item in items:
        product = by_id[item["sku"]]
        qty = int(item["qty"])
        unit = round(float(product["price"]), 2)
        lines.append(
            {
                "sku": product["id"],
                "name": product["name"],
                "merchant": product["merchant"],
                "category": product["category"],
                "unit_price": unit,
                "qty": qty,
                "line_total": round(unit * qty, 2),
            }
        )
    subtotal = round(sum(line["line_total"] for line in lines), 2)
    shipping = 0.0 if subtotal >= 400 else 30.0
    return {
        "line_items": lines,
        "subtotal": subtotal,
        "shipping_fee": shipping,
        "tax": 0.0,
        "total_landed_cost": round(subtotal + shipping, 2),
        "currency": "HKD",
        "free_shipping_threshold": 400,
    }


def test_cheap_pick_keeps_quantity_per_dollar_and_a_close_promo() -> None:
    catalog = [
        _shelf_item("BOWL", "rice bowl", 11.9, "Japan Home Centre", "cheap"),
        _shelf_item("COOKER", "rice cooker", 219.0, "Japan Home Centre", "cheap"),
    ]
    needs = needs_from({"needs": [{"query": "rice", "qty": 1, "sell_point": "cheap", "priority": 1}]})
    fitted = fit_basket(
        catalog,
        needs,
        0,
        lambda items: _quote_shelf(catalog, items),
        PolicyClient(offline=True).check_lines,
    )
    assert fitted["lines"][0]["sku"] == "BOWL"
    thought = next(event["thought"] for event in fitted["events"] if event["event"] == "BASKET_PICKED")
    assert "asked for cheap" in thought
    assert "quantity per dollar" in thought
    assert "connected tender" in thought
    assert "rice cooker" in thought

    near = [
        _shelf_item("PLAIN", "rice bowl plain", 11.9, "Japan Home Centre", "cheap"),
        _shelf_item("WAT", "rice bowl watsons", 12.5, "Watsons", "cheap"),
    ]
    fitted = fit_basket(
        near,
        needs_from({"needs": [{"query": "rice bowl", "qty": 1, "sell_point": "cheap", "priority": 1}]}),
        0,
        lambda items: _quote_shelf(near, items),
        PolicyClient(offline=True).check_lines,
    )
    assert fitted["lines"][0]["sku"] == "WAT"
    assert "Watsons" in next(event["thought"] for event in fitted["events"] if event["event"] == "BASKET_PICKED")


def test_repick_keeps_the_sell_point_and_logs_both_policy_checks() -> None:
    catalog = [_shelf_item(f"S{i}", f"staple {i}", 50, "Watsons", "cheap") for i in range(1, 9)]
    catalog.append(_shelf_item("PAPER-BEST", "paper premium", 90, "Watsons", "best_rating"))
    catalog.append(_shelf_item("PAPER-VALUE", "paper value", 64, "HKTVmall", "cheap"))
    catalog.append(_shelf_item("SOAP", "soap bar", 30, "PARKnSHOP", "cheap"))
    needs = [{"query": f"staple {i}", "qty": 1, "sell_point": "cheap", "priority": i} for i in range(1, 9)]
    needs.append({"query": "paper", "qty": 1, "sell_point": "", "priority": 9})
    needs.append({"query": "soap", "qty": 1, "sell_point": "cheap", "priority": 10})
    policy = PolicyClient(offline=True)
    fitted = fit_basket(
        catalog,
        needs_from({"needs": needs}),
        0,
        lambda items: _quote_shelf(catalog, items),
        policy.check_lines,
    )
    reasons = [event["reason"] for event in fitted["events"]]
    assert fitted["status"] == "PASS"
    assert fitted["quote"]["total_landed_cost"] == 494.0
    assert fitted["repairs"][0]["from_sku"] == "PAPER-BEST"
    assert fitted["repairs"][0]["to_sku"] == "PAPER-VALUE"
    assert fitted["repairs"][0]["saved"] == 26.0
    assert any("basket landed 520.00" in reason for reason in reasons)
    assert any("basket landed 494.00" in reason for reason in reasons)
    assert any(event["event"] == "BASKET_REVISED" for event in fitted["events"])
    assert fitted["question"] == ""


def test_explicit_sell_point_asks_instead_of_downgrading() -> None:
    catalog = [
        _shelf_item("ROLL", "toilet roll", 29.9, "Watsons", "cheap"),
        _shelf_item("SHINE", "shampoo shine", 280, "Japan Home Centre", "best_rating"),
        _shelf_item("PLAIN", "shampoo plain", 24.9, "Watsons", "cheap"),
    ]
    needs = [
        {"query": "toilet", "qty": 1, "sell_point": "cheap", "priority": 1},
        {"query": "shampoo", "qty": 2, "sell_point": "best_rating", "priority": 2},
    ]
    fitted = fit_basket(
        catalog,
        needs_from({"needs": needs}),
        0,
        lambda items: _quote_shelf(catalog, items),
        PolicyClient(offline=True).check_lines,
    )
    assert fitted["status"] == "NEEDS_INPUT"
    assert fitted["policy"]["status"] == "ESCALATE"
    assert fitted["quote"]["total_landed_cost"] == 589.9
    assert fitted["repairs"] == []
    assert "HK$589.90" in fitted["question"]
    assert "SHINE" in fitted["question"]
    assert "approval" in fitted["question"]


def test_payment_offer_waits_for_its_minimum() -> None:
    offers = [
        {
            "category": "payment",
            "retailer": "Watsons",
            "payment_method": "HSBC",
            "title": "HSBC day",
            "description": "92折 on single $400+ spend",
            "conditions": "",
        }
    ]
    small = choose_payment([{"merchant": "Watsons", "line_total": 29.9}], offers)
    large = choose_payment([{"merchant": "Watsons", "line_total": 450}], offers)
    assert small[0] == "mastercard"
    assert large[0] == "HSBC"
    assert "HK$36.00" in large[1]


def test_two_merchants_pass_policy_and_pay() -> None:
    def planner(intent: str, catalog: list[dict]) -> dict:
        return {
            "needs": [
                {"query": "toilet paper", "qty": 1, "sell_point": "cheap", "priority": 1, "sku": "SKU001"},
                {"query": "food container", "qty": 1, "sell_point": "cheap", "priority": 2, "sku": "SKU028"},
            ],
            "thought": "One roll and one box, two shops.",
            "model": "scripted",
        }

    policy = PolicyClient(offline=True)
    api = TestClient(create_app(ShoppingAgent(FileMall(), policy, planner)))
    body = api.post("/agent/intent", json={"intent": "toilet paper and a food container"}).json()
    assert body["status"] == "READY"
    assert [line["sku"] for line in body["lines"]] == ["SKU001", "SKU028"]
    assert {line["merchant"] for line in body["lines"]} == {"Watsons", "Japan Home Centre"}
    assert body["lines"][0]["product_reason"]
    assert body["lines"][0]["merchant_reason"]
    assert body["quote"]["total_landed_cost"] == 79.8
    assert body["policy"]["status"] == "PASS"
    assert body["payment"] is None
    assert {row["merchant"] for row in body["settlement"]["merchants"]} == {"Watsons", "Japan Home Centre"}
    assert body["question"] == ""
    assert [entry["event"] for entry in body["audit_log"]].count("POLICY_CHECK") >= 3
    assert_chain(body["audit_log"])
    _confirmed, paid = approve_reviewed(api, body)
    assert paid["charged"] == 79.8


def test_basket_asks_before_it_drops_a_requested_sell_point() -> None:
    def planner(intent: str, catalog: list[dict]) -> dict:
        return {
            "needs": [
                {"query": "toilet paper", "qty": 1, "sell_point": "cheap", "priority": 1, "sku": "SKU001"},
                {"query": "shampoo", "qty": 2, "sell_point": "best_rating", "priority": 2, "sku": "SKU018"},
            ],
            "thought": "Keep the toilet paper. The shampoo is the one they care about less.",
            "model": "scripted",
        }

    api = TestClient(create_app(ShoppingAgent(FileMall(), PolicyClient(offline=True), planner)))
    body = api.post("/agent/intent", json={"intent": "cheap toilet paper and 2 best rated shampoo"}).json()
    assert body["status"] == "NEEDS_INPUT"
    assert body["payment"] is None
    assert body["escalation"] is None
    assert body["policy"]["rule"] == "over_per_transaction_cap"
    assert body["quote"]["total_landed_cost"] == 589.9
    assert "approval" in body["question"]
    assert "FOLLOW_UP" in events(body)
    assert_chain(body["audit_log"])


def test_food_in_a_basket_halts_and_is_logged() -> None:
    def planner(intent: str, catalog: list[dict]) -> dict:
        return {
            "needs": [
                {"query": "toilet paper", "qty": 1, "sell_point": "cheap", "priority": 1, "sku": "SKU001"},
                {"query": "rice", "qty": 1, "sell_point": "highest_usage", "priority": 2, "sku": "SKU005"},
            ],
            "thought": "Rice is blocked.",
            "model": "scripted",
        }

    api = TestClient(create_app(ShoppingAgent(FileMall(), PolicyClient(offline=True), planner)))
    body = api.post("/agent/intent", json={"intent": "toilet paper and rice"}).json()
    assert body["status"] == "READY"
    assert [line["sku"] for line in body["lines"]] == ["SKU001", "SKU005"]
    assert body["quote"]["total_landed_cost"] == 127.9
    assert body["policy"]["status"] == "PASS"
    assert body["policy"]["amount"] == 127.9
    assert body["payment"] is None
    logged = [entry["reason"] for entry in body["audit_log"] if entry["event"] == "POLICY_CHECK"]
    assert any("SKU005" in reason and "Under HK$500 cap" in reason for reason in logged)
    assert any("SKU001" in reason for reason in logged)
    assert_chain(body["audit_log"])
    _confirmed, paid = approve_reviewed(api, body)
    assert paid["charged"] == 127.9


def test_one_cheap_item_from_every_category_shows_each_decision() -> None:
    api = TestClient(create_app(ShoppingAgent(FileMall(), PolicyClient(offline=True), scripted)))
    body = api.post("/agent/intent", json={"intent": "one cheap item from every category"}).json()
    assert body["status"] == "READY"
    assert body["goal"]["model"] == "catalog"
    assert [line["sku"] for line in body["lines"]] == [
        "SKU001",
        "SKU004",
        "SKU007",
        "SKU010",
        "SKU013",
        "SKU016",
        "SKU019",
        "SKU022",
        "SKU025",
        "SKU028",
    ]
    assert body["quote"]["total_landed_cost"] == 326.6
    assert body["policy"]["status"] == "PASS"
    assert body["policy"]["amount"] == 326.6
    assert body["payment"] is None
    assert body["settlement"]["total"] == 326.6
    checks = [entry for entry in body["audit_log"] if entry["event"] == "POLICY_CHECK"]
    assert len(checks) == 11
    for entry in checks:
        result = entry["result"]
        assert result["status"] == entry["status"]
        assert result["reason"] == entry["reason"].split(": ", 1)[-1]
        assert result["monthly_spent"] == 0
        assert "monthly_remaining" in result
        assert result["per_transaction_cap"] == 500
        assert result["bulk_ceiling"] == 800
        assert result["monthly_cap"] == 2000
        assert f"checked {result['rule']}" in entry["thought"]
        assert entry["thought"].endswith("passed") or entry["thought"].endswith("failed")
    by_sku = {}
    for entry in checks:
        for sku in ("SKU001", "SKU004", "SKU013", "SKU025", "SKU028"):
            if sku in entry["reason"]:
                by_sku[sku] = entry
    assert by_sku["SKU001"]["result"]["status"] == "PASS"
    assert by_sku["SKU001"]["result"]["rule"] == "pass"
    assert by_sku["SKU004"]["result"]["rule"] == "pass"
    assert by_sku["SKU013"]["result"]["rule"] == "pass"
    assert by_sku["SKU025"]["result"]["rule"] == "pass"
    assert by_sku["SKU028"]["result"]["status"] == "PASS"
    picked = next(entry for entry in body["audit_log"] if entry["event"] == "BASKET_PICKED")
    assert "Household SKU001" in picked["reason"]
    assert "Food SKU004" in picked["reason"]
    assert "Electronics SKU025" in picked["reason"]
    assert "asked for cheap" in picked["thought"]
    assert "quantity per dollar" in picked["thought"]
    assert "connected tender" in picked["thought"]
    assert "HALTED" not in events(body)
    assert any("basket landed 326.60" in entry["reason"] for entry in body["audit_log"])
    assert "one cheap item from each category" in body["audit_log"][0]["thought"].casefold()
    assert_chain(body["audit_log"])


def test_same_merchant_picks_the_shop_that_covers_the_most() -> None:
    catalog = FileMall().products
    needs = needs_from(
        {
            "needs": [
                {"query": "toilet paper", "qty": 1, "sell_point": "cheap", "priority": 1},
                {"query": "shampoo", "qty": 1, "sell_point": "cheap", "priority": 2},
                {"query": "water", "qty": 1, "sell_point": "cheap", "priority": 3},
            ]
        }
    )
    choice = choose_best_merchant(catalog, needs, "same shop")
    assert choice["merchant"] == "Watsons"
    assert choice["rows"][0]["covered"] == 3
    assert choice["rows"][0]["landed"] == 102.8

    api = TestClient(create_app(ShoppingAgent(FileMall(), PolicyClient(offline=True), scripted)))
    body = api.post(
        "/agent/intent",
        json={"intent": "one cheap item from every category, same merchant"},
    ).json()
    assert body["status"] == "NEEDS_INPUT"
    assert body["goal"]["model"] == "catalog"
    assert {line["merchant"] for line in body["lines"]} == {"HKTVmall"}
    assert [line["sku"] for line in body["lines"]] == [
        "SKU002",
        "SKU005",
        "SKU008",
        "SKU010",
        "SKU014",
        "SKU017",
        "SKU020",
        "SKU023",
        "SKU025",
        "SKU029",
    ]
    assert body["quote"]["total_landed_cost"] == 568.7
    assert body["payment"] is None
    assert "approval" in body["question"]
    assert "HKTVmall is the best single merchant" in body["reply"]
    assert "PARKnSHOP covers 8" in body["reply"]
    assert "Watsons covers 5" in body["reply"]
    assert "locked to HKTVmall" in body["lines"][0]["merchant_reason"]
    assert any(step["source"] == "catalog" for step in body["react"])
    assert any("best single merchant" in step["thought"] for step in body["react"])
    assert "has no cheap match" in body["lines"][0]["product_reason"]
    assert "HALTED" not in events(body)
    assert_chain(body["audit_log"])


def test_named_shop_is_kept_when_it_covers_less() -> None:
    api = TestClient(create_app(ShoppingAgent(FileMall(), PolicyClient(offline=True), scripted)))
    body = api.post(
        "/agent/intent",
        json={"intent": "one cheap item from every category from Watsons"},
    ).json()
    assert body["status"] == "READY"
    assert {line["merchant"] for line in body["lines"]} == {"Watsons"}
    assert [line["sku"] for line in body["lines"]] == ["SKU001", "SKU007", "SKU013", "SKU016", "SKU021"]
    assert body["quote"]["total_landed_cost"] == 259.8
    assert body["payment"] is None
    assert body["settlement"]["total"] == 259.8
    assert "You asked for Watsons" in body["reply"]
    assert "does not stock" in body["reply"]
    assert_chain(body["audit_log"])


def test_week_of_food_guesses_several_ingredients() -> None:
    api = TestClient(create_app(ShoppingAgent(FileMall(), PolicyClient(offline=True), scripted)))
    body = api.post(
        "/agent/intent",
        json={"intent": "buy food for 7 days with budget 700hkd"},
    ).json()
    assert body["status"] == "READY"
    assert body["goal"]["model"] == "meal"
    assert len({line["sku"] for line in body["lines"]}) >= 3
    assert body["quote"]["total_landed_cost"] <= 500
    assert body["payment"] is None
    assert body["settlement"]["total"] == body["quote"]["total_landed_cost"]
    assert "7 days" in body["reply"]
    assert "700" in body["reply"]
    assert "Guessed rice, water, and potato chips" not in body["reply"]
    assert_chain(body["audit_log"])


def test_sparse_food_shelf_explains_infeasible_minimum() -> None:
    api = TestClient(create_app(ShoppingAgent(FileMall(), PolicyClient(offline=True), scripted)))
    body = api.post(
        "/agent/intent",
        json={
            "intent": (
                "maximum is 500hkd for this order, and you must at least spent 400hkd. "
                "buy me 5 days food with different products as possible, "
                "i want more cash back dollar"
            )
        },
    ).json()
    total = body["settlement"]["total"]
    skus = [line["sku"] for line in body["lines"]]
    assert body["status"] == "READY"
    assert body["payment"] is None
    assert 0 < total < 400
    assert body["quote"]["total_landed_cost"] <= 500
    assert len(set(skus)) >= 3
    assert body["meal"]["minimum_shortfall"] == round(400 - total, 2)
    assert body["meal"]["meets_band"] is False
    assert any("below your HK$400.00 minimum" in warning for warning in body["meal"]["warnings"])
    assert all(line["qty"] == 1 for line in body["lines"] if line["category"] == "Food")
    assert "Guessed rice, water, and potato chips" not in body["reply"]
    assert body["reply"].count("Food for 5 days") == 1
    assert "cashback" in body["reply"].casefold()
    joined = "\n".join(line["product_reason"] for line in body["lines"])
    assert "Category" in joined
    assert_chain(body["audit_log"])


def test_vague_request_asks_a_follow_up() -> None:
    api = TestClient(create_app(ShoppingAgent(FileMall(), PolicyClient(offline=True), scripted)))
    body = api.post("/agent/intent", json={"intent": "buy me something"}).json()
    assert body["status"] == "NEEDS_INPUT"
    assert body["payment"] is None
    assert "What should I buy" in body["question"]
    assert "FOLLOW_UP" in events(body)
    assert_chain(body["audit_log"])


def test_llm_react_is_shown_before_the_tool_steps() -> None:
    def planner(intent: str, catalog: list[dict]) -> dict:
        return {
            "query": "toilet paper",
            "qty": 1,
            "sell_point": "cheap",
            "sku": "SKU001",
            "thought": "Cheap toilet paper.",
            "model": "qwen/qwen3.6-flash",
            "react": [
                {
                    "thought": "The shopper asked for the cheap roll.",
                    "action": "match_sell_point",
                    "observation": "cheap is the lowest price on the toilet-paper shelf.",
                }
            ],
        }

    api = TestClient(create_app(ShoppingAgent(FileMall(), PolicyClient(offline=True), planner)))
    body = api.post("/agent/intent", json={"intent": "cheap toilet paper"}).json()
    assert body["react"][0]["source"] == "llm"
    assert body["react"][0]["action"] == "match_sell_point"
    assert body["react"][0]["thought"] == "The shopper asked for the cheap roll."
    assert body["react"][1]["action"] == "INTENT_RECEIVED"
    assert body["react"][1]["source"] == "llm"
    assert any(step["action"] == "POLICY_CHECK" and step["source"] == "agent" for step in body["react"])
    assert_chain(body["audit_log"])


def test_team_contract_covers_both_readers() -> None:
    path = Path(__file__).resolve().parents[2] / "frontend" / "team_contract.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["for"] == ["person_3", "person_4"]
    assert "NEEDS_INPUT" in body["person_3"]["labels"]["plan_status"]
    assert body["person_4"]["pay"]["does_not_choose_payment_route"] is True
    assert body["person_4"]["receives_from_person_2"] is None
    assert {case["id"] for case in body["cases"]} >= {
        "mixed_merchants_pass",
        "repick_same_sell_point",
        "ask_before_sell_point_change",
        "category_halt",
        "one_item_every_category",
        "same_merchant",
    }


def test_profile_cap_and_checkpoint_are_used() -> None:
    class Memory:
        def __init__(self):
            self.checkpoints = []
            self.chat = []

        def get_profile(self, account_id):
            return {
                "id": account_id,
                "monthly_cap": 50,
                "per_order_cap": 500,
                "bulk_ceiling": 800,
                "monthly_spent": 0,
                "default_payment_route": "visa",
                "last_purchase": {"merchant": "Watsons", "amount": 12.0},
                "recent_orders": [],
            }

        def open_order(self, account_id, intent):
            return "ord_test"

        def checkpoint(self, order_id, **fields):
            self.checkpoints.append((order_id, fields.get("step"), fields.get("status")))

        def append_chat(self, account_id, role, content, order_id=None):
            self.chat.append((role, content))

    memory = Memory()
    policy = PolicyClient(offline=True)
    agent = ShoppingAgent(FileMall(), policy, scripted, profile=memory)
    body = agent.run("cheap toilet paper", 0, None, account_id="acct-1")
    assert body["status"] == "HALTED"
    assert body["policy"]["monthly_cap"] == 50
    assert body["policy"]["reason"] == "Over HK$50 monthly cap"
    assert body["payment"] is None
    assert any(step == "audit_halt" and status == "halted" for _order, step, status in memory.checkpoints)
    assert memory.chat[0][0] == "user"
    assert "toilet" in memory.chat[0][1]


def test_planner_shelf_caps_a_large_catalog() -> None:
    catalog = [
        {
            "id": f"SKU{i:05d}",
            "name": "soap" if i < 3 else f"item {i}",
            "category": "Bath" if i < 50 else "Baby",
            "merchant": "Watsons",
            "price": 10 + i,
            "currency": "HKD",
            "sell_point": "rated",
        }
        for i in range(80)
    ]
    shelf = planner_shelf("soap", catalog)
    assert len(shelf) <= 40
    assert shelf
    assert all("soap" in item["name"] for item in shelf)
    small = catalog[:10]
    assert planner_shelf("soap", small) is small
    broad = planner_shelf("zzzz-not-a-product", catalog)
    assert len(broad) == 2
    assert {item["category"] for item in broad} == {"Bath", "Baby"}


def test_payment_service_holds_a_draft_until_authorize() -> None:
    class FakePayments:
        def __init__(self) -> None:
            self.authorized = []

        def draft(self, **kwargs):
            return {
                "payment_id": "pay_hold",
                "status": "DRAFT",
                "amount": kwargs["amount"],
                "currency": "HKD",
                "rail": kwargs.get("rail") or "mastercard",
                "merchant": kwargs["merchant"],
                "risk_score": 5,
                "step_up_required": False,
                "step_up_reason": "",
                "recommendation": {"rail": "mastercard", "rank": 1},
            }

        def authorize(self, payment_id, idempotency_key=None, step_up_confirmed=False):
            self.authorized.append((payment_id, step_up_confirmed))
            return {
                "status": "CAPTURED",
                "payment_id": payment_id,
                "order_id": "ORD-held",
                "charged": 59.3,
                "currency": "HKD",
                "rail": "mastercard",
                "rail_ts": "2026-10-03T00:00:00Z",
                "error": None,
            }

    payments = FakePayments()
    api = TestClient(
        create_app(ShoppingAgent(FileMall(), PolicyClient(offline=True), scripted, payments=payments))
    )
    review = api.post("/agent/intent", json={"intent": "cheap toilet paper"}).json()
    assert review["status"] == "READY"
    assert review["payment"] is None
    assert review["payment_draft"] is None
    assert events(review)[-1] == "BASKET_REVIEW"
    assert payments.authorized == []
    draft = api.post(
        "/agent/basket/confirm",
        json={"intent": "cheap toilet paper", "lines": [{"sku": "SKU001", "qty": 1}]},
    ).json()
    assert draft["status"] == "READY"
    assert draft["payment"] is None
    assert draft["payment_draft"]["payment_id"] == "pay_hold"
    assert draft["payment_draft"]["rail"] == "mastercard"
    assert draft["payment_draft"]["step_up_required"] is False

    paid = api.post(
        "/agent/payment/authorize",
        json={"payment_id": "pay_hold", "step_up_confirmed": False},
    ).json()
    assert paid["success"] is True
    assert paid["order_id"] == "ORD-held"
    assert paid["charged"] == 59.3
    assert payments.authorized == [("pay_hold", False)]


def test_confirm_does_not_suggest_a_removed_item() -> None:
    api, _policy = client()
    body = api.post(
        "/agent/basket/confirm",
        json={
            "intent": "cheap toilet paper",
            "monthly_spent": 1990,
            "lines": [{"sku": "SKU001", "qty": 1}],
            "removed_skus": ["SKU002"],
        },
    ).json()
    assert body["status"] == "NEEDS_INPUT"
    assert body["question"].startswith("checked ")
    assert "failed" in body["question"]
    assert body["suggestion"]["sku"] not in {"SKU001", "SKU002"}
    assert body["payment"] is None


def test_home_page_does_not_dump_the_plan() -> None:
    api, _policy = client()
    page = api.get("/")
    assert page.status_code == 200
    text = page.text
    assert "localhost:5173/agent" in text
    assert "/agent/intent" in text
    assert 'id="ticket"' not in text
    assert "<pre" not in text


if __name__ == "__main__":
    test_policy_rules()
    test_goal_parser()
    test_catalog_shape()
    test_sell_point_overrides_a_wrong_sku()
    test_cheap_toilet_paper_passes_and_pays()
    test_monthly_cap_halts_before_pay()
    test_best_rated_earbuds_escalate_and_everyday_rice_pays()
    test_shampoo_escalates_then_pays_when_approved()
    test_unknown_request_is_logged_and_does_not_pay()
    test_missing_openrouter_key_is_logged()
    test_openrouter_json_parse()
    test_repick_keeps_the_sell_point_and_logs_both_policy_checks()
    test_explicit_sell_point_asks_instead_of_downgrading()
    test_payment_offer_waits_for_its_minimum()
    test_two_merchants_pass_policy_and_pay()
    test_basket_asks_before_it_drops_a_requested_sell_point()
    test_food_in_a_basket_halts_and_is_logged()
    test_one_cheap_item_from_every_category_shows_each_decision()
    test_same_merchant_picks_the_shop_that_covers_the_most()
    test_named_shop_is_kept_when_it_covers_less()
    test_week_of_food_guesses_several_ingredients()
    test_vague_request_asks_a_follow_up()
    test_llm_react_is_shown_before_the_tool_steps()
    test_team_contract_covers_both_readers()
    test_payment_service_holds_a_draft_until_authorize()
    test_home_page_does_not_dump_the_plan()
    print("ok")
