"""Agent hooks the dashboard relies on: policy verdicts carry account/run tags,
and a captured payment is saved as a paid order."""
from __future__ import annotations

import json

import httpx
from fastapi.testclient import TestClient

from agent_graph import ShoppingAgent
from clients import PolicyClient
from fake_mall import FileMall
from server import create_app
from test_meal_plan import EXAMPLE, FULL, METHODS, RANK, Profiles


def _policy_recorder():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        seen.append((request.url.path, body))
        if request.url.path == "/check_policy":
            return httpx.Response(404)  # fall back to local rules, keep the payload
        return httpx.Response(200, json={})

    client = httpx.Client(base_url="http://policy", transport=httpx.MockTransport(handler))
    return PolicyClient(http=client), seen


class Payments:
    def __init__(self):
        self.drafts = {}

    def draft(self, **kw):
        pid = f"pay_{len(self.drafts) + 1}"
        self.drafts[pid] = kw
        return {"payment_id": pid, "status": "DRAFT", "rail": kw.get("rail"), "step_up_required": True}

    def authorize(self, payment_id, step_up_confirmed=False):
        kw = self.drafts[payment_id]
        return {"status": "CAPTURED", "order_id": "ORD-x1", "charged": kw["amount"], "rail": kw["rail"],
                "payment_id": payment_id}


class SavingProfiles(Profiles):
    def __init__(self, *a):
        super().__init__(*a)
        self.settled = []

    def settle(self, account_id, body):
        self.settled.append((account_id, body))
        return {"order_id": "ord_1", "duplicate": False}


def _rows():
    rows = json.loads(FULL.read_text(encoding="utf-8"))
    return [{**row, "stock": row.get("stock") or 0} for row in rows]


def test_policy_calls_carry_account_and_run_tags() -> None:
    policy, seen = _policy_recorder()
    agent = ShoppingAgent(FileMall(products=_rows()), policy, planner=lambda i, s: {"model": "scripted"},
                          profile=Profiles(METHODS, RANK), enricher=False)
    api = TestClient(create_app(agent))
    body = api.post("/agent/intent", json={"intent": EXAMPLE, "account_id": "acct-7"}).json()
    checks = [payload for path, payload in seen if path == "/check_policy"]
    assert checks and all(p["account_id"] == "acct-7" and p["stage"] == "intent" for p in checks)
    assert len({p["run_id"] for p in checks}) == 1
    lines = [{"sku": l["sku"], "qty": l["qty"]} for l in body["lines"]]
    api.post("/agent/basket/confirm", json={"intent": EXAMPLE, "account_id": "acct-7", "lines": lines})
    confirm = [p for path, p in seen if path == "/check_policy" and p.get("stage") == "confirm"]
    assert confirm and confirm[0]["run_id"].startswith("cfm_")


def test_captured_payment_is_saved_as_a_paid_order() -> None:
    profiles = SavingProfiles(METHODS, RANK)
    agent = ShoppingAgent(FileMall(products=_rows()), PolicyClient(offline=True),
                          planner=lambda i, s: {"model": "scripted"}, profile=profiles,
                          payments=Payments(), enricher=False)
    api = TestClient(create_app(agent))
    plan = api.post("/agent/intent", json={"intent": EXAMPLE, "account_id": "acct-8"}).json()
    lines = [{"sku": l["sku"], "qty": l["qty"]} for l in plan["lines"]]
    ready = api.post("/agent/basket/confirm", json={"intent": EXAMPLE, "account_id": "acct-8", "lines": lines}).json()
    pid = ready["payment_draft"]["payment_id"]
    assert profiles.settled == []  # nothing saved before approval
    paid = api.post("/agent/payment/authorize",
                    json={"payment_id": pid, "step_up_confirmed": True, "account_id": "acct-8"}).json()
    assert paid["success"] is True
    account, body = profiles.settled[0]
    assert account == "acct-8"
    assert body["payment_id"] == pid
    assert body["amount"] == ready["settlement"]["total"]
    assert body["settlement"]["payment_order_id"] == "ORD-x1"
    assert len(body["lines"]) == len(lines) and all(l["category"] for l in body["lines"])
    assert body["benefits"] == ready["settlement"]["benefits"]
