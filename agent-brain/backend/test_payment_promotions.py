"""Live payment reward snapshots and their tender and basket effects."""
import asyncio
from copy import deepcopy

import pytest

from basket_optimizer import optimize_basket
from benefits import (benefit_rates, choose_tender, current_rules, quote_tender,
                      rules_context, settlement_for, validate_rules)


METHODS = [{"route": "mastercard"}, {"route": "visa"}, {"route": "alipay"}]


def reward(route="mastercard", kind="cash", rate=0.1, **extra):
    return {"route": route, "kind": kind, "rate": rate, **extra}


def snapshot(rewards, promotions=None):
    return {"version": 7, "promotions": promotions or [], "payment_promotions": rewards}


def amounts(tender):
    return {row["kind"]: row["amount"] for row in tender["benefits"]}


def test_missing_property_preserves_legacy_rewards():
    rules = {"version": 1, "promotions": []}
    for method in METHODS:
        assert amounts(quote_tender("Shop", 100, method, rules=rules)) == amounts(quote_tender("Shop", 100, method))
    assert amounts(quote_tender("Watsons", 300, METHODS[0])) == {"cash": 6.12, "membership_points": 510}
    assert amounts(quote_tender("Watsons", 300, METHODS[0], rules=rules)) == {"cash": 7.2, "membership_points": 600}


def test_editable_cash_and_miles_select_tenders_and_show_exact_rewards():
    rules = snapshot([reward(rate=.03), reward("visa", rate=.08), reward(kind="Asia Miles", rate=2),
                      reward("visa", "asiamiles", .5)])
    assert choose_tender("Shop", 100, METHODS, ["cash"], rules=rules)["route"] == "visa"
    miles = choose_tender("Shop", 100, METHODS, ["asiamiles"], rules=rules)
    assert miles["route"] == "mastercard"
    assert amounts(miles) == {"cash": 3, "asiamiles": 200}
    assert "3% cashback" in miles["because"]
    assert "2 Asia Miles per HK$1" in miles["because"]
    assert "200.00 earned on HK$100.00" in miles["because"]
    changed = snapshot([reward(rate=.2), reward("visa", rate=.08)])
    assert choose_tender("Shop", 100, METHODS, ["cash"], rules=changed)["route"] == "mastercard"


def test_threshold_discount_rewards_only_discounted_goods_excluding_fees():
    discount = {"id": "sale", "merchant": "Shop", "kind": "percent", "rate": .2, "threshold": 300}
    rules = snapshot([reward(rate=.1), reward(kind="asiamiles", rate=2)], [discount])
    below = quote_tender("Shop", 299, METHODS[0], rules=rules)
    assert below["discount"] == 0
    tender = quote_tender("Shop", 300, METHODS[0], rules=rules)
    assert tender["payable"] == 240
    assert amounts(tender) == {"cash": 24, "asiamiles": 480}
    assert benefit_rates(tender)["cash"] == pytest.approx(.28)
    assert benefit_rates(tender)["asiamiles"] == pytest.approx(1.6)
    settled = settlement_for([{"merchant": "Shop", "qty": 1, "line_total": 300}],
                             {"shipping_fee": 30, "tax": 10}, rules=rules)
    assert settled["total"] == 280
    assert amounts(settled) == amounts(tender)


def test_scoped_override_is_order_independent_and_does_not_stack():
    rows = [reward(rate=.1), reward(rate=.2, merchant="Shop"),
            reward(kind="asiamiles", rate=2), reward(kind="asiamiles", rate=9, merchant="Shop", enabled=False)]
    for ordered in (rows, rows[::-1]):
        rules = snapshot(ordered)
        assert amounts(quote_tender("Shop", 100, METHODS[0], rules=rules)) == {"cash": 20}
        assert amounts(quote_tender("Elsewhere", 100, METHODS[0], rules=rules)) == {"cash": 10, "asiamiles": 200}


def test_explicit_empty_disables_all_rewards_but_keeps_merchant_discount():
    rules = snapshot([], [{"id": "sale", "merchant": "Shop", "kind": "percent", "rate": .1}])
    for method in METHODS:
        tender = quote_tender("Shop", 100, method, rules=rules)
        assert tender["benefits"] == []
        assert tender["discount"] == 10
        assert benefit_rates(tender) == {"cash": .1, "asiamiles": 0, "membership_points": 0, "loyalty_points": 0}


def test_unavailable_methods_cannot_earn_rewards():
    rules = snapshot([reward(rate=1)])
    for method in ({"route": "mastercard", "connected": False},
                   {"route": "mastercard", "merchants": ["Elsewhere"]}):
        assert quote_tender("Shop", 100, method, rules=rules)["benefits"] == []
        assert choose_tender("Shop", 100, [method], None, rules=rules)["benefits"] == []
    assert choose_tender("Shop", 100, [], None, rules=rules)["route"] == ""


def test_optimizer_uses_live_cash_and_miles():
    rows = [{"id": merchant, "name": "Rice 1kg", "merchant": merchant, "price": 100} for merchant in ("A", "B")]
    lines = [{**rows[0], "sku": "A", "qty": 1, "unit_price": 100, "line_total": 100}]
    for kind, rate in (("cash", .2), ("asiamiles", 2)):
        rules = snapshot([reward(kind=kind, rate=rate, merchant="B")])
        result = optimize_basket(lines, rows, shipping=(0, 0), rank=[kind], rules=rules)
        assert result["lines"][0]["merchant"] == "B"
        assert amounts(result["settlement"])[kind] == rate * 100
        disabled = optimize_basket(lines, rows, shipping=(0, 0), rules=snapshot([]))
        assert disabled["settlement"]["benefits"] == []
        assert disabled["optimization"]["selected_effective_cost"] == 100


def test_concurrent_contexts_are_isolated_and_restore_after_errors():
    baseline = current_rules()

    async def worker(rate):
        rules = snapshot([reward(rate=rate)])
        with rules_context(rules):
            await asyncio.sleep(0)
            assert amounts(quote_tender("Shop", 100, METHODS[0])) == {"cash": rate * 100}
            with rules_context(snapshot([])):
                await asyncio.sleep(0)
                assert quote_tender("Shop", 100, METHODS[0])["benefits"] == []
            assert current_rules()["payment_promotions"][0]["rate"] == rate
        assert current_rules() is baseline

    async def run():
        await asyncio.gather(worker(.1), worker(.2))

    asyncio.run(run())
    with pytest.raises(RuntimeError), rules_context(snapshot([])):
        raise RuntimeError("request failed")
    assert current_rules() is baseline


@pytest.mark.parametrize("kind", ["Asia Miles", "ASIA_MILES", "asia-miles", "Membership Points", "loyalty-points", "CASH"])
def test_standard_kind_spellings_normalize_without_mutation(kind):
    rules = snapshot([reward(kind=kind)])
    before = deepcopy(rules)
    checked = validate_rules(rules)
    assert checked["payment_promotions"][0]["kind"] in {"cash", "asiamiles", "membership_points", "loyalty_points"}
    assert checked["payment_promotions"][0]["merchant"] == ""
    assert checked["payment_promotions"][0]["enabled"] is True
    assert rules == before


@pytest.mark.parametrize("row", [None, {}, reward(rate=True), reward(rate=-1), reward(rate=float("nan")),
    reward(rate=float("inf")), reward(rate=1.01), reward(rate=".1"), reward(rate=10**1000),
    reward(kind="asiamiles", rate=1_000_001), reward(kind="cashback"), reward(kind="miles"),
    reward(route=" "), reward(route=7), reward(merchant=None), reward(enabled=1)])
def test_invalid_payment_rewards_rejected(row):
    with pytest.raises(ValueError):
        validate_rules(snapshot([row]))


@pytest.mark.parametrize("value", [None, {}, "", False])
def test_invalid_payment_array_rejected(value):
    with pytest.raises(ValueError):
        validate_rules(snapshot(value))


def test_duplicate_normalized_rules_rejected_and_finite_limits_accepted():
    with pytest.raises(ValueError, match="Duplicate"):
        validate_rules(snapshot([reward(kind="asiamiles"), reward(kind="Asia Miles")]))
    assert validate_rules(snapshot([reward(rate=1), reward(kind="asiamiles", rate=1_000_000)]))
