"""Persistance runtime settings.

MySQL  = audit ledger, monthly spend, profiles, orders, and the product shelf.
Redis  = escalation TTL clock (same key scheme as backend-policy/escalations.py).
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT_DIR / ".env")
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def settings() -> dict:
    return {
        "demo_admin_emails": [email.strip().lower() for email in env("DEMO_ADMIN_EMAILS", "demo-admin@example.com").split(",") if email.strip()],
        "payment_url": env("PAYMENT_URL", "http://127.0.0.1:8004"),
        "port": int(env("PERSISTANCE_PORT", "8003")),
        "frontend_origin": env("FRONTEND_ORIGIN", "http://localhost:5173"),
        # Host MySQL listens on 3306. Tests use time_grocer_test, not this
        # database, because /demo/reset truncates audit and spend.
        "database_url": env(
            "DATABASE_URL",
            "mysql://tg:tg@127.0.0.1:3306/time_grocer",
        ),
        "redis_url": env("REDIS_URL", "redis://127.0.0.1:6379/0"),
        "ttl": int(env("ESCALATION_TTL_SECONDS", "600")),
        "signing_secret": env("APPROVAL_SIGNING_SECRET", "dev-secret-change-me"),
        "require_signature": env("REQUIRE_SIGNATURE", "false").lower() == "true",
        "demo_mode": env("DEMO_MODE", "true").lower() == "true",
        "schema_path": str(BASE_DIR / "schema.sql"),
    }
