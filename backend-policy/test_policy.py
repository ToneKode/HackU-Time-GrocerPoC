import json
import os

from conftest import policy


def test_happy_path_matches_contract_example(c):
    r = policy(c, 119.9)
    assert r == {"status": "PASS", "reason": "Under HK$500 cap", "amount": 119.9, "currency": "HKD",
                 "monthly_spent": 0, "monthly_remaining": 1880.1, "per_transaction_cap": 500,
                 "monthly_cap": 2000, "bulk_ceiling": 800, "rule": "pass"}


def test_halt_monthly_matches_contract_example(c):
    r = policy(c, 119.9, spent=1900)
    assert (r["status"], r["reason"], r["monthly_remaining"]) == ("HALT", "Over HK$2000 monthly cap", 100)


def test_escalate_bulk_matches_contract_example(c):
    r = policy(c, 799.0, merchant="PARKnSHOP")
    assert (r["status"], r["reason"], r["monthly_remaining"]) == ("ESCALATE", "Over HK$500 per-transaction cap", 1201)


def test_boundaries(c):
    assert policy(c, 500)["status"] == "PASS"
    assert policy(c, 500.01)["status"] == "ESCALATE"
    assert policy(c, 800)["status"] == "ESCALATE"
    r = policy(c, 800.01)
    assert r["status"] == "HALT" and r["reason"] == "Over HK$800 bulk ceiling"
    assert policy(c, 100, spent=1900)["status"] == "PASS"       # exactly 2000 is allowed
    assert policy(c, 100.01, spent=1900)["status"] == "HALT"


def test_merchant_rules(c):
    assert policy(c, 50, merchant="DarkWebMart")["reason"] == "Merchant blacklisted"
    r = policy(c, 50, merchant="Sketchy Shop")
    assert r["status"] == "HALT" and r["reason"] == "Merchant not whitelisted"
    assert policy(c, 50, merchant="watsons")["status"] == "PASS"


def test_category_rules(c):
    for cat in ("Food", "Health", "Electronics", "Alcohol"):
        r = policy(c, 50, category=cat)
        assert r["status"] == "PASS" and r["reason"] == "Under HK$500 cap"


def test_check_order_merchant_before_category_before_monthly(c):
    assert policy(c, 900, merchant="DarkWebMart", category="Food", spent=1990)["rule"] == "merchant_blacklisted"
    assert policy(c, 900, category="Food", spent=1990)["rule"] == "monthly_cap"
    assert policy(c, 900, spent=1990)["rule"] == "monthly_cap"      # monthly beats bulk ceiling


def test_bad_input_rejected(c):
    assert c.post("/check_policy", json={"merchant": "Watsons", "category": "Household", "amount": -1}).status_code == 422
    assert c.post("/check_policy", json={"merchant": "Watsons", "category": "Household", "amount": 5,
                                         "currency": "USD"}).status_code == 422


def test_blank_category_rejected(c):
    for bad in ("", "   "):
        r = c.post("/check_policy", json={"merchant": "Watsons", "category": bad, "amount": 5})
        assert r.status_code == 422
    assert c.post("/check_policy", json={"merchant": "Watsons", "amount": 5}).status_code == 422


def test_profile_caps_override_the_defaults(c):
    widened = c.post("/check_policy", json={
        "merchant": "Watsons", "category": "Household", "amount": 600,
        "monthly_spent": 0, "monthly_cap": 5000, "per_transaction_cap": 1000, "bulk_ceiling": 2000,
    }).json()
    assert widened["status"] == "PASS"
    assert widened["monthly_cap"] == 5000
    assert widened["per_transaction_cap"] == 1000
    assert widened["bulk_ceiling"] == 2000
    tight = c.post("/check_policy", json={
        "merchant": "Watsons", "category": "Household", "amount": 80,
        "monthly_spent": 100, "monthly_cap": 150,
    }).json()
    assert tight["status"] == "HALT"
    assert tight["reason"] == "Over HK$150 monthly cap"
    assert tight["monthly_remaining"] == 50


def test_rules_match_cross_team_config():
    path = os.path.join(os.path.dirname(__file__), "..", "agent-brain", "cross_team_config.json")
    if not os.path.exists(path):
        return
    cfg = json.load(open(path))
    import config
    lim = cfg["limits"]
    assert (config.PER_TRANSACTION_CAP, config.BULK_CEILING, config.MONTHLY_CAP) == \
           (lim["per_transaction_cap"], lim["bulk_ceiling"], lim["monthly_cap"])
    assert config.MERCHANT_WHITELIST == cfg["dictionaries"]["merchants"]["whitelist"]
    assert config.MERCHANT_BLACKLIST == cfg["dictionaries"]["merchants"]["blacklist"]
    for k, v in cfg["dictionaries"]["reason"].items():
        assert config.REASONS[k] == v
