import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
os.environ["REDIS_URL"] = "fakeredis://"
os.environ["DATABASE_URL"] = ""  # disable auto-detect; unit tests stay on JSONL
os.environ["LEDGER_PATH"] = os.path.join(tempfile.mkdtemp(), "ledger.jsonl")
os.environ["ESCALATION_TTL_SECONDS"] = "2"
os.environ["DEMO_MODE"] = "true"

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture()
def c():
    with TestClient(app) as client:
        client.post("/demo/reset")
        yield client


def policy(c, amount, merchant="Watsons", category="Household", spent=0, **kw):
    return c.post("/check_policy", json={"merchant": merchant, "category": category, "amount": amount,
                                         "currency": "HKD", "sku": "SKU001", "qty": 1,
                                         "monthly_spent": spent, **kw}).json()


def escalate(c, amount=799.0, merchant="PARKnSHOP", sku="SKU003", category="Household", **kw):
    return c.post("/create_escalation", json={"amount": amount, "currency": "HKD", "merchant": merchant,
                                              "category": category, "sku": sku, "qty": 1,
                                              "reason": "Over HK$500 per-transaction cap", **kw}).json()
