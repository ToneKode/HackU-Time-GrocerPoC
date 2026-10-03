"""MySQL payment store. Skips when host MySQL is not up."""
from __future__ import annotations

import pytest

URL = "mysql://tg:tg@127.0.0.1:3306/time_grocer"


def _reachable() -> bool:
    try:
        from config import _mysql_reachable

        return _mysql_reachable(URL)
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _reachable(), reason="shop MySQL is not running")


def test_roundtrip_keeps_step_up_and_burns_jti_once():
    from mysql_store import MysqlPaymentStore

    store = MysqlPaymentStore(URL)
    store.reset()
    record = {
        "payment_id": "pay_mysql_probe",
        "status": "DRAFT",
        "account_id": "demo",
        "amount": 420.0,
        "currency": "HKD",
        "merchant": "Watsons",
        "rail": "mastercard",
        "purpose": "SKU1:1",
        "intent": "probe",
        "cart_hash": "abc",
        "token_jti": "jti-probe",
        "token": "header.payload.sig",
        "token_expires_at": 1_800_000_000,
        "recommendation": {"rail": "mastercard"},
        "auth_id": None,
        "order_id": None,
        "receipt_id": None,
        "error": None,
        "evidence": ["intent"],
        "created_at": "2026-10-03T00:00:00Z",
        "updated_at": "2026-10-03T00:00:00Z",
        "risk_score": 55,
        "step_up_required": True,
        "step_up_reason": "Confirm this payment before the rail is charged.",
    }
    store.put(record)
    loaded = store.get("pay_mysql_probe")
    assert loaded is not None
    assert loaded["amount"] == 420.0
    assert loaded["status"] == "DRAFT"
    assert loaded["step_up_required"] is True
    assert loaded["risk_score"] == 55
    assert loaded["recommendation"]["rail"] == "mastercard"
    assert "token" in loaded
    assert store.mark_jti_used("jti-probe") is True
    assert store.mark_jti_used("jti-probe") is False
    store.reset()
    assert store.get("pay_mysql_probe") is None
