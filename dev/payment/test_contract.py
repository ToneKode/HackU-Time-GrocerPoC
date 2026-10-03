"""Run the payment module on person 1 contract JSON and check PayResult."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from dev.payment.settle import clear_settlements, settle_payment

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = (
    ROOT / "frontend" / "contract.json",
    ROOT / "agent-brain" / "cross_team_config.json",
)
ARTIFACTS = Path("/opt/cursor/artifacts")
TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
CART_LINE_KEYS = ("sku", "name", "merchant", "category", "unit_price", "qty", "line_total")
CART_QUOTE_KEYS = (
    "line_items",
    "subtotal",
    "shipping_fee",
    "tax",
    "total_landed_cost",
    "currency",
    "free_shipping_threshold",
)
# Shared by both person 1 PayResult objects. The agent-brain copy still
# lists reward_points_earned; frontend/contract.json removed it.
PAY_RESULT_KEYS = (
    "success",
    "order_id",
    "charged",
    "currency",
    "payment_route",
    "ts",
    "error",
)
RAILS = {"yuu", "hase_hsbc", "alipay_ant", "payme"}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _nested_quote(contract: dict, name: str) -> dict | None:
    example = contract.get("examples", {}).get(name)
    if not isinstance(example, dict):
        return None
    response = example.get("response")
    if isinstance(response, dict) and isinstance(response.get("quote"), dict):
        return response["quote"]
    return None


def _scenario_quote(contract: dict, name: str, merchant: str, title: str, category: str) -> dict | None:
    scenario = contract.get("scenarios", {}).get(name)
    if not isinstance(scenario, dict) or "subtotal" not in scenario:
        return None
    return {
        "line_items": [
            {
                "sku": scenario["sku"],
                "name": title,
                "merchant": merchant,
                "category": category,
                "unit_price": scenario["subtotal"],
                "qty": scenario["qty"],
                "line_total": scenario["subtotal"],
            }
        ],
        "subtotal": scenario["subtotal"],
        "shipping_fee": scenario.get("shipping_fee", 0),
        "tax": scenario.get("tax", 0),
        "total_landed_cost": scenario["total_landed_cost"],
        "currency": "HKD",
        "free_shipping_threshold": 400,
    }


def _quotes(contract: dict, name: str) -> list[dict]:
    nested = _nested_quote(contract, name)
    if nested is not None:
        return [nested]
    if name == "happy_path":
        product = contract.get("examples", {}).get("product", {})
        built = _scenario_quote(
            contract,
            name,
            str(product.get("merchant") or "Watsons"),
            str(product.get("name") or ""),
            str(product.get("category") or ""),
        )
    else:
        built = _scenario_quote(
            contract,
            name,
            "PARKnSHOP",
            "Kleenex Toilet Paper 30 Rolls Bulk",
            "Household",
        )
    return [] if built is None else [built]


def _assert_pay_result(body: dict, spec: dict) -> None:
    for key in PAY_RESULT_KEYS:
        assert key in spec, key
        assert key in body, key
    assert isinstance(body["success"], bool)
    assert body["success"] is True
    assert isinstance(body["order_id"], str) and body["order_id"].startswith("ORD-")
    assert isinstance(body["charged"], (int, float)) and not isinstance(body["charged"], bool)
    assert body["currency"] == "HKD"
    assert body["payment_route"] in RAILS
    assert isinstance(body["ts"], str) and TS.match(body["ts"])
    assert body["error"] is None
    # frontend/contract.json ignores reward points. Do not revive the stale field.
    assert "reward_points_earned" not in body
    for row in body["settlements"]:
        logistics = row["logistics"]
        assert logistics["status"] == "confirmed"
        assert logistics["tracking_id"].startswith("TRK-")
        assert logistics["carrier"]
        assert logistics["eta"]


def _dump(name: str, payload: dict) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_person1_contracts_define_cart_and_pay_result() -> None:
    frontend = _load(CONTRACTS[0])
    brain = _load(CONTRACTS[1])
    for contract in (frontend, brain):
        assert set(PAY_RESULT_KEYS) <= set(contract["types"]["PayResult"])
    # Cart line and quote types live on the agent-brain contract.
    # frontend/contract.json carries the same fields on example quotes.
    assert set(CART_LINE_KEYS) <= set(brain["types"]["CartLine"])
    assert set(CART_QUOTE_KEYS) <= set(brain["types"]["CartQuote"])
    assert "reward_points_earned" not in frontend["types"]["PayResult"]
    assert "reward_points" in frontend["ignored"]
    assert "mastercard" in frontend["types"]["PayResult"]["payment_route"]


def test_person1_happy_path_quote_returns_pay_result() -> None:
    clear_settlements()
    samples = []
    for path in CONTRACTS:
        contract = _load(path)
        quotes = _quotes(contract, "happy_path")
        assert quotes, path.name
        for quote in quotes:
            assert set(CART_QUOTE_KEYS) <= set(quote)
            for line in quote["line_items"]:
                assert set(CART_LINE_KEYS) <= set(line)
            result = asyncio.run(settle_payment(quote, delay_s=0))
            _assert_pay_result(result, contract["types"]["PayResult"])
            # Cashback does not reduce cash, so the charge is the landed total.
            assert result["charged"] == quote["total_landed_cost"]
            assert result["payment_route"] == "hase_hsbc"
            assert result["settlements"][0]["merchant"] == quote["line_items"][0]["merchant"]
            assert result["settlements"][0]["shipping_and_tax"] == quote["shipping_fee"]
            samples.append({"contract": str(path.relative_to(ROOT)), "pay_result": result})
    _dump("pay-result-happy-path.json", samples[0]["pay_result"])


def test_person1_bulk_quote_uses_payme_and_matches_pay_result() -> None:
    clear_settlements()
    samples = []
    for path in CONTRACTS:
        contract = _load(path)
        quotes = _quotes(contract, "escalation_bulk")
        assert quotes, path.name
        for quote in quotes:
            result = asyncio.run(settle_payment(quote, delay_s=0))
            _assert_pay_result(result, contract["types"]["PayResult"])
            assert result["payment_route"] == "payme"
            assert result["charged"] == 769.0
            assert result["settlements"][0]["logistics"]["carrier"] == "PARKnSHOP Home Delivery"
            samples.append(result)
    _dump("pay-result-bulk.json", samples[0])
