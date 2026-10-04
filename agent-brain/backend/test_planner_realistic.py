"""Offline regressions for household quantities and payment-aware planning."""

import pytest

from benefits import choose_tender
from meal_plan import classify, plan_meal, servings
from openrouter import SYSTEM


def item(sku, name, price=10, merchant="HKTVmall", category="Food"):
    return dict(id=sku, name=name, price=price, merchant=merchant, category=category, in_stock=True)


@pytest.mark.parametrize("name,count", [
    ("Instant noodles 93g x 5", 5),
    ("Instant noodles 5-pack", 5),
    ("Instant noodles 5P x 2", 10),
    ("Instant noodles 93g x 2packs", 2),
    ("Instant noodles 5S", 5),
])
def test_noodle_edible_units(name, count):
    assert servings(item("n", name), "staple")[0] == count


def test_three_selling_units_feed_fifteen_individual_meals():
    plan = plan_meal("noodles for a family of 3 for 5 days, budget 500 hkd",
                     [item("n", "Instant noodles 93g x 5")], shipping=(0, 0),
                     overrides={"groups": ["staple"]})
    assert plan["needs"][0]["qty"] == 6  # Two staple meals per person per day.
    assert plan["meal"]["serving_targets"]["staple"] == 30
    from meal_plan import describe_lines
    described = describe_lines("noodles for a family of 3 for 5 days", [{"sku": "n", "qty": 3}],
                               {"n": item("n", "Instant noodles 93g x 5")}, methods=None,
                               benefit_rank=None, caps=None, quote={}, settlement={})
    assert "3 selling units x 5 noodle packs = 15 packs" in described["reasons"]["n"]
    assert "family of 3 for 5 days" in described["reasons"]["n"]


def test_unmet_servings_prefer_new_products_over_repeating_the_first_two():
    shelf = [item(f'n{i}', f'Instant noodles flavour {i} 5P', price=10 + i) for i in range(6)]
    plan = plan_meal('noodles for a family of 3 for 5 days under HK$500', shelf,
                     shipping=(0, 0), overrides={'groups': ['staple']})
    assert len(plan['needs']) == 6
    assert all(need['qty'] == 1 for need in plan['needs'])
    assert plan['meal']['servings_supplied']['staple'] == 30


def test_soup_base_is_supporting_ingredient_with_household_cap():
    soup = item("s", "Chicken noodle soup base 500g", category="Rice & Noodles")
    assert classify(soup) == "condiment"
    plan = plan_meal("soup base for a family of 3 for 5 days, budget 500 hkd, spend at least 400 hkd",
                     [soup], shipping=(0, 0), overrides={"groups": ["condiment"]})
    assert plan["needs"][0]["qty"] == 1
    assert plan["meal"]["warnings"]
    assert plan["meal"]["planned_total"] < 400


def test_large_budget_does_not_create_excess_and_unspecified_food_is_diverse():
    shelf = [item("n", "Noodles 5P"), item("r", "Rice 750g"),
             item("p", "Chicken 240g"), item("e", "Eggs 4PCS"),
             item("v", "Carrots 160g"), item("b", "Broccoli 160g"),
             item("f", "Apples 300g"), item("o", "Oranges 300g"),
             item("d", "Water 330ml", category="Beverages")]
    plan = plan_meal("food for a family of 3 for 5 days, budget 5000 hkd", shelf,
                     shipping=(0, 0), caps={"per_order_cap": 5000})
    for group in ("protein", "vegetable", "fruit"):
        assert len([n for n in plan["needs"] if n["group"] == group]) >= 2
    assert plan["meal"]["planned_total"] < 1000
    for group, amount in plan["meal"]["servings_supplied"].items():
        assert amount <= plan["meal"]["serving_targets"][group] + 10


def test_impossible_budget_warns_about_meal_shortfalls():
    plan = plan_meal("food for 5 days for a family of 3, budget 10 hkd",
                     [item("n", "Noodles 5P")], shipping=(0, 0))
    assert plan["needs"]
    assert any("cannot cover" in warning for warning in plan["meal"]["warnings"])


def test_cross_shop_coverage_and_explicit_one_shop():
    shelf = [item("n", "Noodles 5P", merchant="HKTVmall"),
             item("p", "Chicken 240g", merchant="Watsons")]
    mixed = plan_meal("noodles and protein for 1 day, budget 100 hkd", shelf, shipping=(0, 0))
    assert {n["sku"] for n in mixed["needs"]} == {"n", "p"}
    single = plan_meal("food only from HKTVmall for 1 day, budget 100 hkd", shelf, shipping=(0, 0))
    assert {n["sku"] for n in single["needs"]} == {"n"}


def test_merchant_specific_connected_methods_and_benefit_ranking():
    methods = [dict(route="mastercard", merchants=["Watsons"], connected=True),
               dict(route="visa", connected=True), dict(route="alipay", connected=False)]
    assert choose_tender("HKTVmall", 100, methods, ["cash"])["route"] == "visa"
    assert choose_tender("Watsons", 100, methods, ["cash"])["route"] == "mastercard"
    assert choose_tender("Watsons", 100, methods, ["asiamiles"])["route"] == "visa"


def test_benefits_choose_between_equal_food_coverage():
    shelf = [item("h", "Noodles 5P", merchant="HKTVmall"),
             item("w", "Noodles 5P", merchant="Watsons")]
    methods = [dict(route="mastercard", connected=True), dict(route="visa", connected=True)]
    plan = plan_meal("noodles for 1 day, budget 100 hkd", shelf, methods=methods,
                     benefit_rank=["membership_points", "cash"], shipping=(0, 0))
    assert plan["needs"][0]["sku"] == "w"
    assert plan["meal"]["payment"][0]["route"] == "mastercard"


def test_household_counts_and_word_days():
    from meal_plan import parse_request
    request = parse_request("food for five days for 2 adults and 1 child, maximum 500 hkd, at least 400 hkd")
    assert request.days == 5
    assert request.family == 3
    assert request.max_total == 500
    assert request.min_total == 400


def test_pack_weight_is_not_capped_or_lost_in_compact_multipacks():
    assert servings(item("r", "Rice 10kg"), "staple")[0] == 133.3
    assert servings(item("n", "Noodles 93gx5"), "staple")[0] == 5
    assert servings(item("m", "Milk 250mlx6", category="Beverages"), "dairy")[0] == 6


def test_minimum_uses_substitutes_without_adding_servings():
    shelf = [item("cheap", "Chicken 960g", price=20),
             item("premium", "Chicken breast 960g", price=400),
             item("s", "Chicken soup base 500g", price=300)]
    plan = plan_meal("protein for 2 days, maximum 500 hkd, at least 400 hkd", shelf,
                     shipping=(0, 0))
    assert plan["meal"]["meets_band"]
    assert plan["meal"]["planned_total"] == 400
    assert plan["needs"][0]["sku"] == "premium"
    assert plan["needs"][0]["qty"] == 1
    assert plan["meal"]["servings_supplied"]["protein"] == 8
    assert all(need["group"] != "condiment" for need in plan["needs"])


def test_merchant_thresholds_and_unavailable_cards_do_not_invent_benefits():
    from benefits import quote_tender, settlement_for
    card = dict(route="mastercard", connected=True)
    assert quote_tender("Watsons", 299.99, card)["discount"] == 0
    assert quote_tender("Watsons", 300, card)["discount"] == 45
    assert quote_tender("Watsons", 300, dict(card, connected=False))["benefits"] == []
    assert quote_tender("Watsons", 300, dict(card, merchants=["HKTVmall"]))["route"] == ""
    assert quote_tender("Watsons", 300, dict(route="amex", label="Visa travel card"))["benefits"] == []
    lines = [dict(merchant="Watsons", line_total=200), dict(merchant="PARKnSHOP", line_total=200)]
    settlement = settlement_for(lines, {"shipping_fee": 30}, [card], ["cash"])
    assert settlement["discount"] == 0
    assert settlement["total"] == 430
    assert sum(group["payment"]["amount"] for group in settlement["merchants"]) == 430


def test_line_reward_uses_the_selected_merchant_payment():
    from benefits import settlement_for
    from meal_plan import describe_lines
    products = {"p": item("p", "Chicken 240g", merchant="Watsons")}
    lines = [dict(sku="p", merchant="Watsons", qty=1, line_total=10)]
    methods = [dict(route="mastercard"), dict(route="visa")]
    settlement = settlement_for(lines, {}, methods, ["asiamiles"])
    described = describe_lines("food for 1 day", lines, products, methods=methods,
                               benefit_rank=["asiamiles"], caps=None, quote={}, settlement=settlement)
    assert "ICBC Visa" in described["reasons"]["p"]
    assert "Asia Miles" in described["reasons"]["p"]
    assert "cashback" not in described["reasons"]["p"]


def test_prompt_explains_realistic_multi_merchant_plans():
    assert "15 packs" in SYSTEM
    assert "multiple merchants" in SYSTEM
    assert "never add excess quantities" in SYSTEM
