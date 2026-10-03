"""Replay saved intents against the agent API and report overspend telemetry.

Input is a JSON array with scenario_id, intent, monthly_spent, and
authorized_total fields per scenario. See ``measure_replays`` in
adversarial.py for the overspend definition.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx

from adversarial import measure_replays


def replay_scenarios(scenarios: list[dict], client: httpx.Client) -> dict:
    records = []
    for scenario in scenarios:
        required = {"scenario_id", "intent", "authorized_total"}
        missing = required - scenario.keys()
        if missing:
            raise ValueError(
                f"Scenario {scenario.get('scenario_id', '<unknown>')} is missing: "
                + ", ".join(sorted(missing))
            )
        monthly_spent = scenario.get("monthly_spent", 0)
        response = client.post(
            "/agent/intent",
            json={
                "intent": scenario["intent"],
                "monthly_spent": monthly_spent,
                "escalation_id": scenario.get("escalation_id"),
            },
        )
        response.raise_for_status()
        body = response.json()
        payment = body.get("payment") or {}
        escalation = body.get("escalation") or {}
        policy = body.get("policy") or {}
        charged = payment.get("charged")
        final_monthly_spent = float(monthly_spent) + (float(charged) if charged is not None else 0)
        records.append(
            {
                "scenario_id": scenario["scenario_id"],
                "authorized_total": scenario["authorized_total"],
                "payment_attempted": any(
                    entry.get("event") == "PAYMENT" for entry in body.get("audit_log", [])
                ),
                "payment_success": payment.get("success"),
                "charged": charged,
                "policy_status": policy.get("status"),
                "escalation_status": escalation.get("status"),
                "final_monthly_spent": final_monthly_spent,
                "plan_status": body.get("status"),
                "payment_error": payment.get("error"),
            }
        )
    return measure_replays(records)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenarios", help="JSON file containing replay scenarios")
    parser.add_argument(
        "--endpoint",
        default="http://localhost:8002",
        help="base URL of the running agent API (default: http://localhost:8002)",
    )
    args = parser.parse_args()
    scenarios = json.loads(Path(args.scenarios).read_text(encoding="utf-8"))
    with httpx.Client(base_url=args.endpoint.rstrip("/"), timeout=65.0) as client:
        report = replay_scenarios(scenarios, client)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
