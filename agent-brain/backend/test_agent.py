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
from pick import resolve_pick
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
    assert body["status"] == "COMPLETED"
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
    assert body["payment"]["success"] is True
    assert body["payment"]["charged"] == 59.9
    assert "reward_points_earned" not in body["payment"]
    assert events(body) == [
        "INTENT_RECEIVED",
        "PLAN",
        "SEARCH",
        "CART_PRICED",
        "POLICY_CHECK",
        "PAYMENT",
    ]
    assert body["audit_log"][4]["status"] == "PASS"
    policy_step = next(step for step in body["react"] if step["action"] == "POLICY_CHECK")
    assert policy_step["source"] == "agent"
    assert "Policy engine result" in policy_step["thought"]
    assert "PASS" in policy_step["observation"]
    assert "pass" in policy_step["observation"]
    assert body["audit_log"][4]["result"]["status"] == "PASS"
    assert body["audit_log"][4]["result"]["rule"] == "pass"
    assert body["audit_log"][4]["result"]["amount"] == 59.9
    assert body["audit_log"][4]["result"]["monthly_remaining"] == 1940.1
    assert body["audit_log"][4]["result"]["per_transaction_cap"] == 500
    assert "Policy engine result" in body["audit_log"][4]["thought"]
    assert body["audit_log"][-1]["status"] == "COMPLETED"
    assert_chain(body["audit_log"])


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
    assert rice["status"] == "COMPLETED"
    assert rice["product"]["id"] == "SKU005"
    assert rice["goal"]["sell_point"] == "highest_usage"
    assert rice["quote"]["total_landed_cost"] == 98.0
    assert rice["policy"]["status"] == "PASS"
    assert rice["payment"]["charged"] == 98.0


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
    assert body["status"] == "COMPLETED"
    assert [line["sku"] for line in body["lines"]] == ["SKU001", "SKU028"]
    assert {line["merchant"] for line in body["lines"]} == {"Watsons", "Japan Home Centre"}
    assert body["lines"][0]["product_reason"]
    assert body["lines"][0]["merchant_reason"]
    assert body["quote"]["total_landed_cost"] == 79.8
    assert body["policy"]["status"] == "PASS"
    assert body["payment"]["charged"] == 79.8
    assert body["payment_route"]
    assert body["question"] == ""
    assert [entry["event"] for entry in body["audit_log"]].count("POLICY_CHECK") >= 3
    assert_chain(body["audit_log"])


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
    assert body["status"] == "COMPLETED"
    assert [line["sku"] for line in body["lines"]] == ["SKU001", "SKU005"]
    assert body["quote"]["total_landed_cost"] == 127.9
    assert body["policy"]["status"] == "PASS"
    assert body["policy"]["amount"] == 127.9
    assert body["payment"]["charged"] == 127.9
    logged = [entry["reason"] for entry in body["audit_log"] if entry["event"] == "POLICY_CHECK"]
    assert any("SKU005" in reason and "Under HK$500 cap" in reason for reason in logged)
    assert any("SKU001" in reason for reason in logged)
    assert_chain(body["audit_log"])


def test_one_cheap_item_from_every_category_shows_each_decision() -> None:
    api = TestClient(create_app(ShoppingAgent(FileMall(), PolicyClient(offline=True), scripted)))
    body = api.post("/agent/intent", json={"intent": "one cheap item from every category"}).json()
    assert body["status"] == "COMPLETED"
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
    assert body["payment"]["charged"] == 326.6
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
        assert f"rule {result['rule']}" in entry["thought"]
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
    assert body["status"] == "COMPLETED"
    assert {line["merchant"] for line in body["lines"]} == {"Watsons"}
    assert [line["sku"] for line in body["lines"]] == ["SKU001", "SKU007", "SKU013", "SKU016", "SKU021"]
    assert body["quote"]["total_landed_cost"] == 259.8
    assert body["payment"]["charged"] == 259.8
    assert "You asked for Watsons" in body["reply"]
    assert "does not stock" in body["reply"]
    assert_chain(body["audit_log"])


def test_week_of_food_guesses_several_ingredients() -> None:
    api = TestClient(create_app(ShoppingAgent(FileMall(), PolicyClient(offline=True), scripted)))
    body = api.post(
        "/agent/intent",
        json={"intent": "buy food for 7 days with budget 700hkd"},
    ).json()
    assert body["status"] == "COMPLETED"
    assert body["goal"]["model"] == "catalog"
    assert [(line["sku"], line["qty"]) for line in body["lines"]] == [
        ("SKU004", 1),
        ("SKU007", 3),
        ("SKU010", 4),
    ]
    assert body["quote"]["total_landed_cost"] == 161.6
    assert body["quote"]["total_landed_cost"] <= 700
    assert body["payment"]["charged"] == 161.6
    assert "7 days" in body["reply"]
    assert "700" in body["reply"]
    assert "rice, water, and potato chips" in body["reply"]
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
    test_home_page_does_not_dump_the_plan()
    print("ok")
