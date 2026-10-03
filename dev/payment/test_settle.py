"""Chooser and mocked settlement for the payment step."""

from __future__ import annotations

import asyncio

import pytest

from dev.payment.money import money
from dev.payment.rails import RailQuote, choose_rail, explain
from dev.payment.settle import clear_settlements, settle_payment


def _method(subtotal: str) -> str:
    best, _quotes = choose_rail(money(subtotal))
    return best.method


def test_under_300_prefers_five_percent_cashback_over_smaller_rewards() -> None:
    best, quotes = choose_rail(money("100"))
    by_method = {quote.method: quote for quote in quotes}
    assert best.method == "hase_hsbc"
    assert best.cash_paid == money("100")
    assert best.reward_hkd == money("5.00")
    assert by_method["yuu"].reward_hkd == money("0.50")
    assert by_method["alipay_ant"].reward_hkd == money("0.10")
    assert by_method["payme"].eligible is False


def test_payme_wins_when_it_reduces_cash() -> None:
    best, _quotes = choose_rail(money("300"))
    assert best.method == "payme"
    assert best.cash_paid == money("270")
    assert best.reward_hkd == money("0")


def test_payme_just_under_threshold_does_not_apply() -> None:
    assert _method("299.99") == "hase_hsbc"


def test_equal_cash_prefers_higher_reward_value() -> None:
    """HK$5 of yuu value beats HK$2 of cashback when cash paid is the same."""
    yuu = RailQuote("yuu", True, money("100"), money("5"), "yuu")
    card = RailQuote("hase_hsbc", True, money("100"), money("2"), "card")
    best = min(
        (yuu, card),
        key=lambda quote: (quote.cash_paid, -quote.reward_hkd, 0),
    )
    assert best.method == "yuu"
    assert "ahead of" in explain(yuu, [yuu, card])


def test_each_merchant_is_charged_with_its_own_rail() -> None:
    clear_settlements()
    result = asyncio.run(
        settle_payment(
        [
            {
                "sku": "SKU001",
                "name": "Tempo Ultra Soft Toilet Paper 27 Rolls",
                "merchant": "Watsons",
                "unit_price": 89.9,
                "qty": 1,
                "line_total": 89.9,
            },
            {
                "sku": "SKU003",
                "name": "Kleenex Toilet Paper 30 Rolls Bulk",
                "merchant": "PARKnSHOP",
                "price": 799,
                "qty": 1,
            },
            {
                "name": "Taste grapes",
                "merchant": "Taste",
                "price": 40,
                "qty": 2,
            },
        ],
            delay_s=0,
        )
    )
    assert result["success"] is True
    by_merchant = {row["merchant"]: row for row in result["settlements"]}
    assert by_merchant["Watsons"]["method"] == "hase_hsbc"
    assert by_merchant["Watsons"]["cash_paid"] == 89.9
    assert by_merchant["PARKnSHOP"]["method"] == "payme"
    assert by_merchant["PARKnSHOP"]["cash_paid"] == 769.0
    assert by_merchant["Taste"]["method"] == "hase_hsbc"
    assert by_merchant["Taste"]["subtotal"] == 80.0
    for row in result["settlements"]:
        assert row["logistics"]["status"] == "confirmed"
        assert row["logistics"]["tracking_id"].startswith("TRK-")
        assert row["order_id"].startswith("ORD-")
    assert result["charged"] == pytest.approx(89.9 + 769.0 + 80.0)
    assert result["payment_route"] == "payme"
    assert result["currency"] == "HKD"
    assert result["error"] is None


def test_idempotency_returns_the_same_orders() -> None:
    clear_settlements()
    items = [{"merchant": "Taste", "price": 50, "qty": 1, "name": "Snacks"}]
    first = asyncio.run(settle_payment(items, idempotency_key="list-1", delay_s=0))
    second = asyncio.run(settle_payment(items, idempotency_key="list-1", delay_s=0))
    assert first == second
    assert first["settlements"][0]["logistics"]["carrier"] == "Taste Home Delivery"


def test_same_merchant_lines_share_one_charge() -> None:
    clear_settlements()
    result = asyncio.run(settle_payment(
        [
            {"merchant": "PARKnSHOP", "line_total": 200, "qty": 1, "sku": "A"},
            {"merchant": "parknshop", "line_total": 150, "qty": 1, "sku": "B"},
        ],
            delay_s=0,
        )
    )
    assert len(result["settlements"]) == 1
    row = result["settlements"][0]
    assert row["merchant"] == "PARKnSHOP"
    assert row["subtotal"] == 350
    assert row["method"] == "payme"
    assert row["cash_paid"] == 320
