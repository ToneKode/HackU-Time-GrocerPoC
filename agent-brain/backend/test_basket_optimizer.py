"""Fixed-needs allocation, offer thresholds, delivery and equivalence contracts."""
from copy import deepcopy

import pytest

from basket_optimizer import TOOL_NAME, TOOL_SCHEMA, optimize_basket
from benefits import settlement_for


def product(sku, name, merchant, price, **extra):
    return {"id": sku, "name": name, "merchant": merchant, "price": price, **extra}


def line(row, qty=1):
    return {**row, "sku": row["id"], "qty": qty, "unit_price": row["price"], "line_total": row["price"] * qty}


def offers(thresholds, rate=0.05):
    def evaluate(lines, quote, methods, rank):
        merchants = {}
        for row in lines:
            merchants[row["merchant"]] = merchants.get(row["merchant"], 0) + row["line_total"]
        discount = sum(subtotal * rate for merchant, subtotal in merchants.items() if subtotal >= thresholds[merchant])
        return {"total": round(sum(merchants.values()) - discount + quote["shipping_fee"], 2),
                "discount": round(discount, 2), "benefits": [], "merchants": list(merchants)}
    return evaluate


def fixture_basket():
    a1 = product("a1", "Rice 1kg", "A", 300)
    b1 = product("b1", "Rice 1kg", "B", 330)
    a2 = product("a2", "Beans 1kg", "A", 170)
    b2 = product("b2", "Beans 1kg", "B", 150)
    return [line(a1), line(a2)], [a1, b1, a2, b2]


def test_out_of_stock_alternatives_and_initial_baskets_are_not_selected():
    rows = [product('a', 'Rice 1kg', 'A', 100, in_stock=True, stock=None),
            product('b', 'Rice 1kg', 'B', 1, in_stock=False, stock=None)]
    result = optimize_basket([line(rows[0])], rows, shipping=(0, 0))
    assert result['lines'][0]['sku'] == 'a'
    assert result['optimization']['alternatives_counts'] == [0]
    unavailable = optimize_basket([line(rows[1])], [rows[1]], shipping=(0, 0))
    assert unavailable['optimization']['feasible'] is False


def test_split_unlocks_both_thresholds_and_beats_either_single_shop():
    lines, catalog = fixture_basket()
    result = optimize_basket(lines, catalog, shipping=(0, 0), candidate_sets=[["a1", "b1"], ["a2", "b2"]],
                             settlement_evaluator=offers({"A": 300, "B": 150}), offer_thresholds={"A": 300, "B": 150})
    assert [row["sku"] for row in result["lines"]] == ["a1", "b2"]
    assert result["settlement"]["total"] == 427.5
    assert result["settlement"]["total"] < min(470 * .95, 480 * .95)
    assert result["optimization"]["initial_effective_cost"] == 446.5
    assert result["optimization"]["alternatives_counts"] == [1, 1]


def test_delivery_negates_split_with_injected_per_merchant_delivery():
    lines, catalog = fixture_basket()
    def delivery(rows, shipping):
        groups = {}
        for row in rows:
            groups[row["merchant"]] = groups.get(row["merchant"], 0) + row["line_total"]
        fee = sum(30 for subtotal in groups.values() if subtotal < 400)
        return {"shipping_fee": fee}
    result = optimize_basket(lines, catalog, quote_evaluator=delivery,
                             settlement_evaluator=offers({"A": 300, "B": 150}))
    assert {row["merchant"] for row in result["lines"]} == {"A"}
    assert result["settlement"]["total"] == 446.5


def test_identical_discount_does_not_force_split():
    catalog = [product(f"{m}{i}", f"Food{i} 1kg", m, 150) for i in range(2) for m in ("A", "B")]
    result = optimize_basket([line(catalog[0]), line(catalog[2])], catalog, shipping=(0, 0),
                             settlement_evaluator=offers({"A": 150, "B": 150}))
    assert result["settlement"]["total"] == 285
    assert len({row["merchant"] for row in result["lines"]}) == 1


def test_real_offers_and_basket_wide_delivery_are_authoritative():
    rows = [product("p", "Rice 1kg", "PARKnSHOP", 320), product("w", "Rice 1kg", "Watsons", 320)]
    result = optimize_basket([line(rows[0])], rows)
    assert result["lines"][0]["merchant"] == "Watsons"
    assert result["quote"]["shipping_fee"] == 30
    assert result["settlement"]["discount"] == 48
    assert result["settlement"]["total"] == 302
    assert result["optimization"]["selected_effective_cost"] == 295.47
    assert result["settlement"] == settlement_for(result["lines"], result["quote"])
    assert sum(m["payment"]["amount"] for m in result["settlement"]["merchants"]) == 302


def test_default_delivery_is_one_basket_fee_and_waived_on_goods():
    rows = [product("a", "Rice 1kg", "A", 200), product("b", "Beans 1kg", "B", 200)]
    result = optimize_basket([line(row) for row in rows], rows)
    assert result["quote"]["shipping_fee"] == 0
    rows[1]["price"] = 199
    result = optimize_basket([line(row) for row in rows], rows)
    assert result["quote"]["shipping_fee"] == 30
    assert sum(m["payment"]["amount"] for m in result["settlement"]["merchants"]) == result["settlement"]["total"]


def test_cap_uses_charge_before_cashback_and_never_pads_quantities():
    row = product("a", "Rice 1kg", "A", 100)
    capped = optimize_basket([line(row)], [row], shipping=(0, 0), max_total=99)
    assert capped["optimization"]["selected_effective_cost"] == 97.6
    assert capped["optimization"]["feasible"] is False
    minimum = optimize_basket([line(row, 2)], [row], shipping=(0, 0), min_total=250)
    assert minimum["optimization"]["feasible"] is False
    assert minimum["lines"][0]["qty"] == 2
    assert minimum["settlement"]["total"] == 200


def test_substitution_can_meet_band_without_padding():
    rows = [product("a", "Rice 1kg", "A", 100), product("b", "Rice 1kg", "B", 120)]
    result = optimize_basket([line(rows[0], 2)], rows, shipping=(0, 0), min_total=230, max_total=240)
    assert result["optimization"]["feasible"]
    assert result["settlement"]["total"] == 240
    assert result["lines"][0]["qty"] == 2


def test_disconnected_and_merchant_restricted_methods_are_not_used():
    rows = [product("w", "Rice 1kg", "Watsons", 300), product("p", "Rice 1kg", "PARKnSHOP", 290)]
    methods = [{"route": "mastercard", "connected": False}, {"route": "visa", "connected": True, "merchants": ["Elsewhere"]}]
    result = optimize_basket([line(rows[0])], rows, methods=methods, shipping=(0, 0))
    assert result["settlement"]["discount"] == 0
    assert result["settlement"]["benefits"] == []
    assert result["optimization"]["feasible"] is False
    assert result["lines"][0]["sku"] == "w"
    assert result["settlement"]["merchants"][0]["payment"]["route"] == ""


def test_equivalence_rejects_category_only_and_mismatched_servings_or_package(monkeypatch):
    base = product("a", " Rice 1kg ", "A", 100, category="staple", servings=10, package="bag")
    rows = [base, product("b", "rice 1kg", "B", 90, servings=10, package="bag"),
            product("c", "rice 1kg", "C", 1, servings=20, package="bag"),
            product("d", "Pasta 1kg", "D", 1, category="staple", servings=10, package="bag"),
            product("e", "rice 1kg", "E", 1, servings=10, package="box")]
    result = optimize_basket([line(base, 3)], rows, shipping=(0, 0))
    assert result["lines"][0]["sku"] == "b"
    assert result["lines"][0]["servings"] * result["lines"][0]["qty"] == 30
    assert result["optimization"]["alternatives_counts"] == [1]
    explicit = optimize_basket([line(base, 3)], rows, candidate_sets=[["c", "d", "e"]], shipping=(0, 0))
    assert explicit["lines"][0]["sku"] == "d"
    assert explicit["lines"][0]["qty"] == 3
    assert explicit["optimization"]["alternatives_counts"] == [1]

    import basket_optimizer
    compatible = basket_optimizer._compatible
    checked = []
    def track(base, option, explicit):
        checked.append(option["id"])
        return compatible(base, option, explicit)
    monkeypatch.setattr(basket_optimizer, "_compatible", track)
    unrelated = [product(f"other{i}", f"Other food {i} 1kg", "A", 1) for i in range(5000)]
    indexed = optimize_basket([line(base, 3), line(base, 2)], rows + unrelated, shipping=(0, 0))
    assert checked == ["b", "c", "e", "b", "c", "e"]
    assert [row["sku"] for row in indexed["lines"]] == ["b", "b"]
    assert indexed["optimization"]["alternatives_counts"] == [1, 1]
    assert indexed["optimization"]["quantity_split_supported"] is False
    assert indexed["optimization"]["multi_quantity_line_indices"] == [0, 1]
    assert "splitting units within a line is not searched" in indexed["optimization"]["explanation"]


def test_unknown_pack_requires_explicit_alternatives():
    rows = [product("a", "Rice", "A", 100), product("b", "rice", "B", 50)]
    assert optimize_basket([line(rows[0])], rows)["lines"][0]["sku"] == "a"
    assert optimize_basket([line(rows[0])], rows, candidate_sets=[["b"]])["lines"][0]["sku"] == "b"


def test_points_only_break_effective_cost_ties():
    rows = [product("a", "Rice 1kg", "A", 100), product("b", "Rice 1kg", "B", 101)]
    def evaluator(lines, quote, methods, rank):
        charge = sum(row["line_total"] for row in lines)
        return {"total": charge, "benefits": [{"kind": "asiamiles", "amount": 1000000 if lines[0]["merchant"] == "B" else 0}]}
    result = optimize_basket([line(rows[0])], rows, settlement_evaluator=evaluator, rank=["asiamiles"])
    assert result["lines"][0]["sku"] == "a"
    rows[1]["price"] = 100
    assert optimize_basket([line(rows[0])], rows, settlement_evaluator=evaluator, rank=["asiamiles"])["lines"][0]["sku"] == "b"


def test_bound_metadata_initial_retention_stock_and_no_input_mutation():
    rows = [product("a", "Rice 1kg", "A", 100), product("b", "Rice 1kg", "B", 50, stock=1)]
    lines = [line(rows[0], 2)]
    before = deepcopy((lines, rows))
    result = optimize_basket(lines, rows, max_evaluations=1, beam_width=1)
    assert result["optimization"]["evaluations"] == 1
    assert result["lines"][0]["sku"] == "a"
    assert result["optimization"]["alternatives_counts"] == [0]
    assert result["optimization"]["global_optimum_guaranteed"] is False
    assert (lines, rows) == before


def test_threshold_seed_survives_narrow_beam():
    rows = [product("a", "Rice 1kg", "A", 310), product("b", "Rice 1kg", "Watsons", 300)]
    result = optimize_basket([line(rows[0])], rows, shipping=(0, 0), beam_width=1, rounds=0)
    assert result["lines"][0]["sku"] == "b"


def test_evaluation_limit_on_multiple_needs_retains_initial_and_merchant_diversity():
    rows = [product(f"{m}{i}", f"Food{i} 1kg", m, price)
            for i in range(3) for m, price in (("A", 100), ("B", 90), ("C", 95))]
    lines = [line(rows[i * 3]) for i in range(3)]
    result = optimize_basket(lines, rows, shipping=(0, 0), max_evaluations=4,
                             beam_width=2, max_candidates=3)
    metadata = result["optimization"]
    assert metadata["evaluations"] == 4
    assert metadata["evaluation_limit_reached"]
    assert metadata["retained_alternatives_counts"] == [2, 2, 2]
    assert metadata["initial_effective_cost"] == 292.8
    assert metadata["selected_effective_cost"] <= metadata["initial_effective_cost"]
    assert [row["qty"] for row in result["lines"]] == [1, 1, 1]


def test_schema_and_invalid_inputs():
    assert TOOL_SCHEMA["function"]["name"] == TOOL_NAME == "optimize_basket"
    row = product("a", "Rice 1kg", "A", 100)
    with pytest.raises(ValueError, match="align"):
        optimize_basket([line(row)], [row], candidate_sets=[])
    with pytest.raises(ValueError, match="Unknown alternative"):
        optimize_basket([line(row)], [row], candidate_sets=[["missing"]])
    with pytest.raises(ValueError, match="positive integer"):
        optimize_basket([line(row, 1.5)], [row])
    with pytest.raises(ValueError, match="exceeds"):
        optimize_basket([line(row)], [row], min_total=101, max_total=100)
    assert optimize_basket([], [])["settlement"]["total"] == 0
