"""Create (or refresh) two clearly labelled TEST shoppers through the persistance API.

    python seed_test_accounts.py                      # uses http://127.0.0.1:8003
    PERSISTANCE_API_BASE_URL=http://host:8003 python seed_test_accounts.py

Safe to run repeatedly: an existing account is logged into, not re-created, and its
connected methods and benefit ranking are set back to the values below.

Mock admin (not real credentials): demo-admin@example.com / DemoAdminOnly!
Run `python seed_test_accounts.py --admin-only` to provision it without changing
shopper preferences. Default DEMO_ADMIN_EMAILS grants this account the mock admin
role. Admin APIs require its account_id and X-Admin-Password on each request.

Both shopper accounts are for testing how payment preferences change the agent's suggestion
for the same prompt (see agent-brain/backend/test_meal_plan.py::test_two_shoppers_*):

  test-3methods@example.com  Mox Mastercard + Alipay + ICBC Visa, ranks cashback first
  test-2methods@example.com  Alipay + ICBC Visa (Mastercard disconnected), ranks Asia Miles first

Only the standard library is used, so no new dependency is needed.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE_URL = os.environ.get("PERSISTANCE_API_BASE_URL", "http://127.0.0.1:8003").rstrip("/")

DEMO_ADMIN = {
    "email": "demo-admin@example.com", "password": "DemoAdminOnly!",
    "name": "DEMO ADMIN (mock market editor)", "connected": {},
    "benefit_rank": ["cash", "membership_points", "asiamiles", "loyalty_points"],
}

TEST_ACCOUNTS = (
    {
        "email": "test-3methods@example.com",
        "password": "TestShopper3!",
        "name": "TEST 3 methods (cashback first)",
        "connected": {"mastercard": True, "alipay": True, "visa": True},
        "benefit_rank": ["cash", "membership_points", "asiamiles", "loyalty_points"],
    },
    {
        "email": "test-2methods@example.com",
        "password": "TestShopper2!",
        "name": "TEST 2 methods (Asia Miles first)",
        "connected": {"mastercard": False, "alipay": True, "visa": True},
        "benefit_rank": ["asiamiles", "loyalty_points", "membership_points", "cash"],
    },
)


def _call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        BASE_URL + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read() or b"{}")
        except ValueError:
            detail = {}
        return exc.code, detail


def ensure_account(spec: dict) -> dict:
    """Log in, or register when the email is new, then apply methods and ranking."""
    status, found = _call("POST", "/accounts/login", {"email": spec["email"], "password": spec["password"]})
    created = False
    if status == 401:
        status, found = _call(
            "POST",
            "/accounts/register",
            {"email": spec["email"], "password": spec["password"], "name": spec["name"]},
        )
        created = status == 200
        if status == 409:
            raise SystemExit(f"{spec['email']} exists with a different password; not touching it.")
    if status != 200:
        raise SystemExit(f"{spec['email']}: persistance answered {status} {found}")
    account_id = found["id"]
    have = {method["route"] for method in found.get("payment_methods") or []}
    for route, label, last4 in (("mastercard", "Mox Mastercard", "4242"), ("alipay", "Alipay", ""), ("visa", "ICBC Visa", "1888")):
        if route not in have and spec["connected"].get(route):
            _call("POST", f"/accounts/{account_id}/payment-methods", {"route": route, "label": label, "last4": last4})
    status, profile = _call(
        "PATCH",
        f"/accounts/{account_id}/preferences",
        {
            "benefit_rank": spec["benefit_rank"],
            "methods": [{"route": route, "connected": on} for route, on in spec["connected"].items()],
        },
    )
    if status != 200:
        raise SystemExit(f"{spec['email']}: preferences answered {status} {profile}")
    return {
        "email": spec["email"],
        "password": spec["password"],
        "account_id": account_id,
        "created": created,
        "connected": [m["label"] for m in profile.get("payment_methods") or [] if m.get("connected")],
        "benefit_rank": profile.get("benefit_rank"),
    }


def main() -> int:
    for spec in ((DEMO_ADMIN,) if "--admin-only" in sys.argv else TEST_ACCOUNTS + (DEMO_ADMIN,)):
        print(json.dumps(ensure_account(spec)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
