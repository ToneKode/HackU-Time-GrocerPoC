"""Per-account record of every policy verdict this service gives.

Why: the hash-chained audit ledger has no account id, so it cannot answer
"how often did the agent fail the policy check for this shopper, and on which
rule?". Each /check_policy call that carries an account_id (and optionally a
run_id and stage from the agent) is stored here with the rule that fired.
/create_escalation calls with an account_id are stored too, so their outcome
(APPROVED / REFUSED / EXPIRED) can be shown later.

Backend: JSONL file by default (DECISIONS_PATH, next to the ledger), MySQL
table policy_decisions when DATABASE_URL is set (schema in
persistance/backend/schema.sql, migration 006).
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from audit_log import now_ts

# Same order as policy_engine.evaluate (first hit wins).
RULE_ORDER = (
    "merchant_blacklisted",
    "merchant_not_whitelisted",
    "category_blacklisted",
    "monthly_cap",
    "over_bulk_ceiling",
    "over_per_transaction_cap",
)
FIELDS = (
    "id", "ts", "account_id", "run_id", "stage", "kind", "status", "rule", "reason",
    "amount", "merchant", "category", "sku", "qty", "escalation_id",
)


def _row(**values) -> dict:
    row = {key: values.get(key) for key in FIELDS}
    row["id"] = row["id"] or "pd_" + uuid.uuid4().hex[:12]
    row["ts"] = row["ts"] or now_ts()
    row["kind"] = row["kind"] or "check"
    row["stage"] = (row["stage"] or "")[:32]
    row["run_id"] = (row["run_id"] or "")[:64]
    row["amount"] = round(float(row["amount"] or 0), 2)
    row["qty"] = int(row["qty"] or 1)
    for key in ("account_id", "status", "rule", "reason", "merchant", "category", "sku", "escalation_id"):
        row[key] = str(row[key] or "")
    return row


def make_decision_log(database_url: str | None, path: str):
    if database_url:
        return MySQLDecisionLog(database_url)
    return FileDecisionLog(path)


class FileDecisionLog:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        if not os.path.exists(path):
            open(path, "w").close()

    def record(self, **values) -> dict:
        row = _row(**values)
        with self._lock, open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def for_account(self, account_id: str) -> list[dict]:
        with self._lock, open(self.path, "r", encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        return [row for row in rows if row.get("account_id") == account_id]

    def reset(self) -> None:
        with self._lock:
            open(self.path, "w").close()


class MySQLDecisionLog:
    def __init__(self, url: str):
        import sys

        root = Path(__file__).resolve().parents[1] / "persistance" / "backend"
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from db import connect  # persistance/backend/db.py

        self.url = url
        self._connect = connect

    def record(self, **values) -> dict:
        row = _row(**values)
        with self._connect(self.url) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO policy_decisions (" + ", ".join(FIELDS) + ") VALUES ("
                + ", ".join(["%s"] * len(FIELDS)) + ")",
                tuple(row[key] for key in FIELDS),
            )
        return row

    def for_account(self, account_id: str) -> list[dict]:
        with self._connect(self.url) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT " + ", ".join(FIELDS) + " FROM policy_decisions WHERE account_id = %s ORDER BY ts, id",
                (account_id,),
            )
            rows = cur.fetchall()
        out = []
        for row in rows:
            row = dict(row)
            row["amount"] = round(float(row["amount"] or 0), 2)
            out.append(row)
        return out

    def reset(self) -> None:
        with self._connect(self.url) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM policy_decisions")


def _run_key(row: dict) -> str:
    # A run is one agent decision (intent run or basket confirm). Calls without a
    # run id count on their own.
    return f"{row.get('run_id')}|{row.get('stage')}" if row.get("run_id") else f"single|{row['id']}"


def stats(rows: list[dict], escalation_status=None, recent: int = 10) -> dict:
    """Aggregate one account's verdicts.

    A run fails when any verdict in it is HALT or ESCALATE. Each failed run
    counts once per rule it hit, so a basket with three blocked lines on the
    same rule counts as one failure for that rule.
    """
    checks = [row for row in rows if row.get("kind") == "check"]
    runs: dict[str, list[dict]] = {}
    for row in checks:
        runs.setdefault(_run_key(row), []).append(row)
    failed_runs = 0
    halted_runs = 0
    escalated_runs = 0
    by_rule: dict[str, dict] = {}
    examples = []
    for key, group in runs.items():
        bad = [row for row in group if row.get("status") in {"HALT", "ESCALATE"}]
        if not bad:
            continue
        failed_runs += 1
        if any(row["status"] == "HALT" for row in bad):
            halted_runs += 1
        else:
            escalated_runs += 1
        seen = set()
        for row in bad:
            rule = row.get("rule") or "unknown"
            if rule in seen:
                continue
            seen.add(rule)
            entry = by_rule.setdefault(
                rule,
                {"rule": rule, "status": row["status"], "count": 0, "last_ts": "", "examples": []},
            )
            entry["count"] += 1
            entry["last_ts"] = max(entry["last_ts"], row["ts"])
            example = {
                "ts": row["ts"],
                "run_id": row.get("run_id") or "",
                "stage": row.get("stage") or "",
                "status": row["status"],
                "rule": rule,
                "reason": row.get("reason") or "",
                "amount": row.get("amount"),
                "merchant": row.get("merchant") or "",
                "category": row.get("category") or "",
                "sku": row.get("sku") or "",
            }
            entry["examples"].append(example)
            examples.append(example)
    order = {rule: index for index, rule in enumerate(RULE_ORDER)}
    rules = sorted(by_rule.values(), key=lambda item: (-item["count"], order.get(item["rule"], 99)))
    for entry in rules:
        entry["examples"] = sorted(entry["examples"], key=lambda item: item["ts"], reverse=True)[:3]
    escalations = []
    outcome: dict[str, int] = {}
    for row in rows:
        if row.get("kind") != "escalation":
            continue
        status = "UNKNOWN"
        if escalation_status is not None:
            status = escalation_status(row.get("escalation_id")) or "UNKNOWN"
        outcome[status] = outcome.get(status, 0) + 1
        escalations.append(
            {
                "escalation_id": row.get("escalation_id"),
                "ts": row["ts"],
                "amount": row.get("amount"),
                "merchant": row.get("merchant"),
                "reason": row.get("reason"),
                "status": status,
            }
        )
    return {
        "checks": len(checks),
        "runs_checked": len(runs),
        "runs_failed": failed_runs,
        "runs_halted": halted_runs,
        "runs_escalated": escalated_runs,
        "runs_passed": len(runs) - failed_runs,
        "by_rule": rules,
        "recent_failures": sorted(examples, key=lambda item: item["ts"], reverse=True)[:recent],
        "escalations": {"count": len(escalations), "by_status": outcome, "recent": escalations[-recent:][::-1]},
        "first_ts": rows[0]["ts"] if rows else None,
        "last_ts": rows[-1]["ts"] if rows else None,
    }


def ledger_summary(entries: list[dict]) -> dict:
    """Shared audit ledger (no account id): POLICY_CHECK rows by status, all accounts."""
    out: dict[str, int] = {}
    for entry in entries:
        if entry.get("event") == "POLICY_CHECK":
            out[entry.get("status") or ""] = out.get(entry.get("status") or "", 0) + 1
    return {"policy_checks_by_status": out, "scope": "all accounts (the audit ledger has no account id)"}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
