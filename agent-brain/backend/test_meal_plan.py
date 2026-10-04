"""Meal-plan optimiser: parsing, spend band, connected methods, benefit rank,
basket edits, swaps, and validation of optional LLM notes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_graph import ShoppingAgent
from benefits import choose_tender
from clients import PolicyClient
from fake_mall import FileMall
from meal_plan import parse_request, plan_meal
from openrouter import validate_enrichment
from server import create_app

EXAMPLE = (
    "Maximum for this order is 500 Hkd, you at least need to spent 80% of the cap for this order, "
    "buy me foods for 5 days for a family with size of 3 and I wanna more food category, like protein, "
    "fruits, main dashes ingredients etc."
)
FULL = Path(__file__).resolve().parent.parent / "hk_products_full.json"
METHODS = [
    {"id": "m1", "route": "mastercard", "label": "Mox Mastercard", "last4": "4242", "connected": True},
    {"id": "m2", "route": "alipay", "label": "Alipay", "last4": "", "connected": True},
    {"id": "m3", "route": "visa", "label": "ICBC Visa", "last4": "1888", "connected": True},
]
RANK = ["cash", "asiamiles", "membership_points", "loyalty_points"]


@pytest.fixture(scope="module")
def catalog() -> list[dict]:
    rows = json.loads(FULL.read_text(encoding="utf-8"))
    return [{**row, "stock": row.get("stock") or 0} for row in rows]


class Profiles:
    """In-memory stand-in for persistance /accounts/{id}/profile."""

    def __init__(self, methods, rank):
        self.data = {"payment_methods": methods, "benefit_rank": rank, "per_order_cap": 500, "monthly_cap": 2000}

    def get_profile(self, account_id):
        return dict(self.data)

    def open_order(self, *a, **k):
        return None

    def checkpoint(self, *a, **k):
        return None

    def append_chat(self, *a, **k):
        return None


def _agent(catalog, methods=METHODS, rank=RANK, enricher=False):
    return ShoppingAgent(
        FileMall(products=catalog),
        PolicyClient(offline=True),
        planner=lambda intent, shelf: {"query": intent, "qty": 1, "model": "scripted"},
        profile=Profiles(methods, rank),
        enricher=enricher,
    )


def test_example_sentence_is_parsed() -> None:
    req = parse_request(EXAMPLE)
    assert req.max_total == 500
    assert req.min_pct == 0.8
    assert req.days == 5
    assert req.family == 3
    assert {"protein", "fruit", "staple"} <= set(req.asked_groups)
    assert req.variety


def test_example_basket_lands_in_band_and_uses_best_tender(catalog) -> None:
    plan = plan_meal(EXAMPLE, catalog, methods=METHODS, benefit_rank=RANK, caps={"per_order_cap": 500})
    assert plan["needs"], plan.get("question")
    meal = plan["meal"]
    assert 400 <= meal["planned_total"] <= 500
    assert meal["planned_landed"] <= 500
    by_sku = {row["id"]: row for row in catalog}
    for need in plan["needs"]:
        assert need["sku"] in by_sku  # never invented
        assert need["group"] in {"staple", "protein", "fruit", "vegetable", "dairy", "drinks", "snacks"}
        assert by_sku[need["sku"]]["name"] in need["reason"]
        assert "family of 3 for 5 days" in need["reason"]
    groups = {need["group"] for need in plan["needs"]}
    assert {"protein", "fruit", "staple"} <= groups
    for row in meal["payment"]:
        goods = sum(
            by_sku[n["sku"]]["price"] * n["qty"] for n in plan["needs"] if by_sku[n["sku"]]["merchant"] == row["merchant"]
        )
        assert row["route"] == choose_tender(row["merchant"], goods, METHODS, RANK)["route"]


def test_only_connected_methods_are_used(catalog) -> None:
    methods = [dict(m, connected=(m["route"] == "visa")) for m in METHODS]
    plan = plan_meal(EXAMPLE, catalog, methods=methods, benefit_rank=RANK, caps={"per_order_cap": 500})
    assert plan["needs"]
    assert {row["route"] for row in plan["meal"]["payment"]} == {"visa"}
    for row in plan["meal"]["payment"]:
        assert {option["route"] for option in row["options"]} == {"visa"}


def test_rank_changes_the_tender(catalog) -> None:
    plan = plan_meal(
        EXAMPLE, catalog, methods=METHODS, benefit_rank=["loyalty_points", "cash"], caps={"per_order_cap": 500}
    )
    assert plan["needs"]
    assert {row["route"] for row in plan["meal"]["payment"]} == {"alipay"}


def test_no_connected_method_asks(catalog) -> None:
    methods = [dict(m, connected=False) for m in METHODS]
    plan = plan_meal(EXAMPLE, catalog, methods=methods, benefit_rank=RANK)
    assert plan.get("question") and not plan.get("needs")


def test_minimum_above_cap_asks(catalog) -> None:
    plan = plan_meal("buy food for 3 days, maximum 100 hkd, spend at least 200 hkd", catalog, methods=METHODS)
    assert "at least" in plan["question"]


def test_intent_endpoint_runs_policy_and_explains(catalog) -> None:
    api = TestClient(create_app(_agent(catalog)))
    body = api.post("/agent/intent", json={"intent": EXAMPLE, "account_id": "t1"}).json()
    assert body["status"] == "READY", body.get("reply")
    assert body["policy"]["status"] == "PASS"
    assert 400 <= body["settlement"]["total"] <= 500
    assert body["meal"]["request"]["family_size"] == 3
    assert body["payment_route"] == body["meal"]["payment"][0]["route"]
    assert any(e["event"] == "POLICY_CHECK" for e in body["audit_log"])
    assert all(line["product_reason"] for line in body["lines"])
    assert "llm" not in {step["source"] for step in body["react"]}


def test_confirm_over_user_max_goes_back_for_edits(catalog) -> None:
    api = TestClient(create_app(_agent(catalog)))
    body = api.post("/agent/intent", json={"intent": EXAMPLE, "account_id": "t1"}).json()
    lines = [{"sku": line["sku"], "qty": line["qty"]} for line in body["lines"]]
    top = max(range(len(lines)), key=lambda i: body["lines"][i]["unit_price"])
    # Exceed the paid cap even after the largest configured merchant discount (15%).
    lines[top]["qty"] += int((500 / 0.85 - body["quote"]["subtotal"]) // body["lines"][top]["unit_price"]) + 1
    again = api.post("/agent/basket/confirm", json={"intent": EXAMPLE, "account_id": "t1", "lines": lines}).json()
    assert again["status"] == "NEEDS_INPUT"
    assert "over your HK$500.00 maximum" in again["question"]
    assert again["lines"] and again["meal"]["warnings"]
    fixed = api.post(
        "/agent/basket/confirm",
        json={"intent": EXAMPLE, "account_id": "t1", "lines": [{"sku": l["sku"], "qty": l["qty"]} for l in body["lines"]]},
    ).json()
    assert fixed["status"] == "READY"
    assert fixed["policy"]["status"] == "PASS"
    assert all(line["product_reason"] for line in fixed["lines"])


def test_alternatives_are_real_catalog_rows(catalog) -> None:
    api = TestClient(create_app(_agent(catalog)))
    body = api.post("/agent/intent", json={"intent": EXAMPLE, "account_id": "t1"}).json()
    sku = body["lines"][0]["sku"]
    out = api.post("/agent/basket/alternatives", json={"intent": EXAMPLE, "sku": sku}).json()
    by_sku = {row["id"]: row for row in catalog}
    assert out["alternatives"]
    for option in out["alternatives"]:
        assert option["sku"] != sku
        assert by_sku[option["sku"]]["price"] == pytest.approx(option["price"])


def test_llm_notes_are_validated() -> None:
    brief = {"lines": [{"sku": "A1", "name": "Eggs 15PCS", "qty": 2}], "planned_charge_hkd": 499.0}
    raw = {
        "notes": [
            {"sku": "A1", "note": "Boil the eggs for breakfast across the 5 days."},
            {"sku": "A1X", "note": "Invented product."},
            {"sku": "A1", "note": "Only HK$3.20 each!"},
        ],
        "summary": "Covers protein for 3 people.",
        "react": [
            {"thought": "Family of 3 for 5 days.", "action": "read", "observation": "ok"},
            {"thought": "Total is 612 dollars.", "action": "check", "observation": "made up"},
        ],
        "parse_check": {"days": 5, "family_size": 3, "max_hkd": 500, "min_hkd": 400},
    }
    out = validate_enrichment(raw, EXAMPLE, brief, "test-model")
    assert out["notes"] == {"A1": "Boil the eggs for breakfast across the 5 days."}
    assert out["summary"] == "Covers protein for 3 people."
    assert [step["thought"] for step in out["react"]] == ["Family of 3 for 5 days."]
    assert out["dropped"] == 3
    assert out["parse_check"]["min_hkd"]["grounded"]  # 80% of 500


def test_enricher_failure_keeps_optimizer_result(catalog) -> None:
    def broken(intent, brief):
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    api = TestClient(create_app(_agent(catalog, enricher=broken)))
    body = api.post("/agent/intent", json={"intent": EXAMPLE, "account_id": "t1"}).json()
    assert body["status"] == "READY"
    assert body["meal"]["llm"]["used"] is False


def test_enricher_notes_reach_lines(catalog) -> None:
    def fake(intent, brief):
        sku = brief["lines"][0]["sku"]
        return validate_enrichment(
            {"notes": [{"sku": sku, "note": "Use it in the main dish."}], "summary": "", "react": [
                {"thought": "Check groups.", "action": "check", "observation": "ok"}]},
            intent, brief, "fake-llm",
        )

    api = TestClient(create_app(_agent(catalog, enricher=fake)))
    body = api.post("/agent/intent", json={"intent": EXAMPLE, "account_id": "t1"}).json()
    assert body["meal"]["llm"]["used"] is True
    assert "Meal idea (model): Use it in the main dish." in body["lines"][0]["product_reason"]
    sources = [step["source"] for step in body["react"]]
    assert sources[0] == "llm" and "optimizer" in sources


def test_confirm_under_minimum_warns_but_passes(catalog) -> None:
    api = TestClient(create_app(_agent(catalog)))
    body = api.post("/agent/intent", json={"intent": EXAMPLE, "account_id": "t1"}).json()
    lines = [{"sku": l["sku"], "qty": l["qty"]} for l in body["lines"]]
    small = lines[: max(1, len(lines) // 3)]
    out = api.post("/agent/basket/confirm", json={"intent": EXAMPLE, "account_id": "t1", "lines": small}).json()
    assert out["status"] == "READY"  # not blocked
    under = out["meal"]["under_min"]
    assert under["minimum"] == 400 and under["charge"] == out["settlement"]["total"]
    assert under["short_by"] == round(400 - out["settlement"]["total"], 2)
    assert "80% of your HK$500.00 cap" in under["basis"]
    assert f"HK${under['short_by']:.2f} below the HK$400.00 minimum" in out["reply"]
    step = next(s for s in out["react"] if s["action"] == "check_spend_band")
    assert step["source"] == "optimizer" and "under the minimum" in step["thought"]
    assert any(e["event"] == "BASKET_REVISED" and e["status"] == "UNDER_MINIMUM" for e in out["audit_log"])


THREE_METHODS = METHODS
TWO_METHODS = [dict(m, connected=(m["route"] != "mastercard")) for m in METHODS]
CASH_FIRST = ["cash", "membership_points", "asiamiles", "loyalty_points"]
MILES_FIRST = ["asiamiles", "loyalty_points", "membership_points", "cash"]


def _run_to_draft(catalog, methods, rank) -> tuple[dict, dict]:
    api = TestClient(create_app(_agent(catalog, methods=methods, rank=rank)))
    plan = api.post("/agent/intent", json={"intent": EXAMPLE, "account_id": "seeded"}).json()
    lines = [{"sku": l["sku"], "qty": l["qty"]} for l in plan["lines"]]
    out = api.post("/agent/basket/confirm", json={"intent": EXAMPLE, "account_id": "seeded", "lines": lines}).json()
    return plan, out


def test_two_shoppers_same_prompt_get_different_suggestions(catalog) -> None:
    """Mirrors persistance/backend/seed_test_accounts.py: 3 methods + cashback first
    vs 2 methods (no Mastercard) + Asia Miles first."""
    plan_a, a = _run_to_draft(catalog, THREE_METHODS, CASH_FIRST)
    plan_b, b = _run_to_draft(catalog, TWO_METHODS, MILES_FIRST)
    for plan, out in ((plan_a, a), (plan_b, b)):
        assert out["status"] == "READY"
        assert out["payment"] is None  # stops before any authorisation
        assert 400 <= out["settlement"]["total"] <= 500
    tender_a = {m["payment"]["label"] for m in a["settlement"]["merchants"]}
    tender_b = {m["payment"]["label"] for m in b["settlement"]["merchants"]}
    assert tender_a == {"Mox Mastercard"}
    assert tender_b == {"ICBC Visa"}
    kinds_a = {x["kind"] for x in a["settlement"]["benefits"]}
    kinds_b = {x["kind"] for x in b["settlement"]["benefits"]}
    assert "cash" in kinds_a and "asiamiles" not in kinds_a
    assert kinds_b == {"asiamiles"}
    # The cashback shopper's basket unlocks a shop offer (cash value), the miles shopper's does not need to.
    cash_a = float(a["settlement"].get("discount") or 0) + sum(
        x["amount"] for x in a["settlement"]["benefits"] if x["kind"] == "cash"
    )
    cash_b = float(b["settlement"].get("discount") or 0)
    assert cash_a > cash_b
    # Accurate pack weights can make the same food basket best for both shoppers;
    # their connected methods and reward ranking must still select different tenders.
    assert plan_a["meal"]["payment"][0]["route"] != plan_b["meal"]["payment"][0]["route"]
    # Both baskets still feed the family about equally well.
    nut = {alt["strategy"]: alt["nutrition"] for alt in plan_a["meal"]["alternatives"]}
    assert abs(nut[plan_a["meal"]["strategy"]] - nut[plan_b["meal"]["strategy"]]) <= 0.06
