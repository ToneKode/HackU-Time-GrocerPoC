"""Per-account policy verdicts and GET /policy_stats/{account_id}."""
from conftest import escalate, policy


def test_untagged_checks_are_not_recorded(c):
    policy(c, 100)
    body = c.get("/policy_stats/acct-1").json()
    assert body["checks"] == 0
    assert body["runs_failed"] == 0
    assert body["by_rule"] == []


def test_failures_are_counted_per_run_and_rule(c):
    tag = {"account_id": "acct-1"}
    # Run 1: two blocked lines on the same rule, then the total. One failure for the rule.
    policy(c, 900, run_id="r1", stage="intent", **tag)
    policy(c, 950, run_id="r1", stage="intent", **tag)
    # Run 2: passes.
    policy(c, 120, run_id="r2", stage="intent", **tag)
    # Run 3: over the per-order cap -> ESCALATE.
    policy(c, 600, run_id="r3", stage="confirm", **tag)
    # Run 4: merchant not on the whitelist.
    policy(c, 50, merchant="Nowhere Mart", run_id="r4", stage="confirm", **tag)
    # Another shopper's failure is not mixed in.
    policy(c, 900, run_id="x1", account_id="acct-2")

    body = c.get("/policy_stats/acct-1").json()
    assert body["checks"] == 5
    assert body["runs_checked"] == 4
    assert body["runs_failed"] == 3
    assert body["runs_passed"] == 1
    assert body["runs_halted"] == 2
    assert body["runs_escalated"] == 1
    rules = {item["rule"]: item for item in body["by_rule"]}
    assert rules["over_bulk_ceiling"]["count"] == 1
    assert rules["over_bulk_ceiling"]["status"] == "HALT"
    assert rules["over_per_transaction_cap"]["count"] == 1
    assert rules["merchant_not_whitelisted"]["count"] == 1
    example = rules["over_per_transaction_cap"]["examples"][0]
    assert example["run_id"] == "r3" and example["stage"] == "confirm" and example["amount"] == 600
    assert len(body["recent_failures"]) == 3
    assert body["recent_failures"][0]["ts"] >= body["recent_failures"][-1]["ts"]
    other = c.get("/policy_stats/acct-2").json()
    assert other["runs_failed"] == 1


def test_escalations_are_tracked_with_their_outcome(c):
    esc = escalate(c, account_id="acct-9", run_id="r9")
    c.post(f"/escalations/{esc['escalation_id']}/decision", json={"decision": "REFUSE"})
    body = c.get("/policy_stats/acct-9").json()
    assert body["escalations"]["count"] == 1
    assert body["escalations"]["by_status"] == {"REFUSED": 1}
    assert body["escalations"]["recent"][0]["escalation_id"] == esc["escalation_id"]


def test_ledger_summary_is_labelled_global(c):
    c.post("/log_event", json={"event": "POLICY_CHECK", "status": "HALT", "reason": "x"})
    body = c.get("/policy_stats/acct-1").json()
    assert body["ledger"]["policy_checks_by_status"] == {"HALT": 1}
    assert "all accounts" in body["ledger"]["scope"]


def test_verdict_is_unchanged_by_tags(c):
    plain = policy(c, 600)
    tagged = policy(c, 600, account_id="acct-1", run_id="r", stage="intent")
    assert plain == tagged
