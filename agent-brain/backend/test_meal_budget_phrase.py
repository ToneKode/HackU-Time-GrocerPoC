"""Spend bands from natural requests apply to the final amount after offers."""
import json
from pathlib import Path

from meal_plan import parse_request, plan_meal


INTENT = "buy food for 5 days for one person, at least HK$400 and at most HK$500, varied meals with cashback"


def test_currency_prefixed_minimum_and_maximum_are_retained():
    request = parse_request(INTENT)
    assert request.min_total == 400
    assert request.max_total == 500


def test_discounted_charge_meets_the_minimum_or_explains_the_shortfall():
    catalog = json.loads((Path(__file__).parents[1] / "hk_products_full.json").read_text(encoding="utf-8"))
    result = plan_meal(INTENT, catalog, caps={"per_transaction_cap": 450, "monthly_cap": 1800, "bulk_ceiling": 800})
    meal = result["meal"]
    assert meal["request"]["min_total"] == 400
    total = meal["planned_total"]
    assert total <= 450
    assert total >= 400 or meal["warnings"]
