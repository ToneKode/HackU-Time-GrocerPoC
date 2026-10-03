"""Postgres payment store. Skips when the persistance database is not up."""
from __future__ import annotations

import os

import pytest

URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://tg:tg@127.0.0.1:5432/time_grocer"
)


def _reachable(url: str) -> bool:
    try:
        import psycopg

        with psycopg.connect(url, connect_timeout=1) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                return cur.fetchone() is not None
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _reachable(URL), reason="persistance Postgres is not running"
)


def test_open_store_selects_postgres(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", URL)
    from config import settings
    from store import open_store

    store = open_store(settings()["database_url"], "")
    assert store.backend == "postgres"
    store.reset()


def test_roundtrip_survives_a_new_store():
    from pg_store import PostgresPaymentStore
    from store import draft_record

    store = PostgresPaymentStore(URL)
    store.reset()
    record = draft_record(
        account_id="demo",
        amount=59.9,
        currency="HKD",
        merchant="Watsons",
        rail="mastercard",
        purpose="SKU001:1",
        intent="cheap toilet paper",
        cart_hash="abc",
        token={"token": "jwt-demo", "jti": "tok_pgtest", "expires_at": 1893456000},
        recommendation={"rail": "mastercard", "rank": 1, "net_benefit": 0.6},
    )
    store.put(record)
    loaded = store.get(record["payment_id"])
    assert loaded is not None
    assert loaded["amount"] == 59.9
    assert loaded["currency"] == "HKD"
    assert loaded["token"] == "jwt-demo"
    assert loaded["recommendation"]["rail"] == "mastercard"
    assert loaded["status"] == "DRAFT"

    loaded["status"] = "CAPTURED"
    loaded["charged"] = 59.9
    loaded["reward_points_earned"] = 5
    loaded["order_id"] = "ORD-pg"
    loaded["evidence"] = list(loaded["evidence"]) + ["captured"]
    store.put(loaded)

    again = PostgresPaymentStore(URL).get(record["payment_id"])
    assert again["status"] == "CAPTURED"
    assert again["charged"] == 59.9
    assert again["reward_points_earned"] == 5
    assert again["order_id"] == "ORD-pg"
    assert "captured" in again["evidence"]
    assert again["token"] == "jwt-demo"

    assert store.mark_jti_used("tok_pgtest") is True
    assert store.mark_jti_used("tok_pgtest") is False
    store.reset()
    assert store.get(record["payment_id"]) is None
    assert store.mark_jti_used("tok_pgtest") is True
