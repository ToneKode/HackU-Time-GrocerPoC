"""Persistance runtime settings.

Postgres = durable audit ledger + monthly spend.
Redis    = escalation TTL clock (same key scheme as backend-policy/escalations.py).
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
        "port": int(env("PERSISTANCE_PORT", "8003")),
        "frontend_origin": env("FRONTEND_ORIGIN", "http://localhost:5173"),
        "database_url": env(
            "DATABASE_URL",
            "postgresql://tg:tg@127.0.0.1:5432/time_grocer",
        ),
        "redis_url": env("REDIS_URL", "redis://127.0.0.1:6379/0"),
        "ttl": int(env("ESCALATION_TTL_SECONDS", "600")),
        "signing_secret": env("APPROVAL_SIGNING_SECRET", "dev-secret-change-me"),
        "require_signature": env("REQUIRE_SIGNATURE", "false").lower() == "true",
        "demo_mode": env("DEMO_MODE", "true").lower() == "true",
        "schema_path": str(BASE_DIR / "schema.sql"),
    }
