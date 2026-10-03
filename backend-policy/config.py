"""Person 2 — hardcoded policy rules and runtime settings.

Numbers, merchants and the check order mirror agent-brain/cross_team_config.json.
test_policy.py::test_rules_match_cross_team_config fails if they drift apart.
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Load backend-policy/.env if python-dotenv is installed. Real environment variables win.
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

CURRENCY = "HKD"

PER_TRANSACTION_CAP = 500.0
BULK_CEILING = 800.0
MONTHLY_CAP = 2000.0

MERCHANT_WHITELIST = ["Watsons", "HKTVmall", "PARKnSHOP", "Japan Home Centre"]
MERCHANT_BLACKLIST = ["DarkWebMart"]
# Empty on purpose. A category is allowed unless this list names it.
CATEGORY_BLACKLIST = []

REASONS = {
    "PASS": "Under HK$500 cap",
    "ESCALATE": "Over HK$500 per-transaction cap",
    "HALT_MONTHLY": "Over HK$2000 monthly cap",
    "HALT_BULK": "Over HK$800 bulk ceiling",
    "HALT_MERCHANT": "Merchant not whitelisted",
    "HALT_MERCHANT_BLACKLIST": "Merchant blacklisted",
    "HALT_CATEGORY": "Category blacklisted",
}


def env(name: str, default: str) -> str:
    return os.getenv(name, default)


def _ledger_path() -> str:
    path = env("LEDGER_PATH", "data/ledger.jsonl")
    return path if os.path.isabs(path) else str(BASE_DIR / path)    # same file whatever the cwd is


def _redis_url() -> str:
    # Default stays in-process fakeredis for a zero-dep demo.
    # Point REDIS_URL at the persistance Redis (see persistance/compose.yaml) for real TTLs.
    return env("REDIS_URL", "fakeredis://")


def _database_url() -> str | None:
    # When set, the hash-chained ledger lives in Postgres (persistance subtree).
    # Empty / unset keeps the JSONL file at LEDGER_PATH.
    url = env("DATABASE_URL", "").strip()
    return url or None


def settings() -> dict:
    return {
        "port": int(env("POLICY_API_PORT", "8001")),
        "frontend_origin": env("FRONTEND_ORIGIN", "http://localhost:5173"),
        "redis_url": _redis_url(),
        "database_url": _database_url(),
        "ledger_path": _ledger_path(),
        "ttl": int(env("ESCALATION_TTL_SECONDS", "600")),
        "signing_secret": env("APPROVAL_SIGNING_SECRET", "dev-secret-change-me"),
        "require_signature": env("REQUIRE_SIGNATURE", "false").lower() == "true",
        "demo_mode": env("DEMO_MODE", "true").lower() == "true",
    }
