"""Person 2 — hardcoded policy rules and runtime settings.

Numbers, merchants and the check order mirror agent-brain/cross_team_config.json.
test_policy.py::test_rules_match_cross_team_config fails if they drift apart.

When DATABASE_URL / REDIS_URL are unset, we probe the persistance compose defaults
and use them if reachable; otherwise we keep the zero-dep JSONL + fakeredis demo.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
log = logging.getLogger("policy.config")

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

# Defaults match persistance/compose.yaml
PERSISTANCE_DATABASE_URL = "postgresql://tg:tg@127.0.0.1:5432/time_grocer"
PERSISTANCE_REDIS_URL = "redis://127.0.0.1:6379/0"


def env(name: str, default: str) -> str:
    return os.getenv(name, default)


def _pg_reachable(url: str) -> bool:
    try:
        import psycopg
        with psycopg.connect(url, connect_timeout=1) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                return cur.fetchone() is not None
    except Exception:
        return False


def _redis_reachable(url: str) -> bool:
    try:
        import redis
        return bool(redis.Redis.from_url(url, socket_connect_timeout=1).ping())
    except Exception:
        return False


def _ledger_path() -> str:
    path = env("LEDGER_PATH", "data/ledger.jsonl")
    return path if os.path.isabs(path) else str(BASE_DIR / path)


def _redis_url() -> str:
    # Explicit REDIS_URL always wins (tests set fakeredis://).
    if "REDIS_URL" in os.environ:
        return os.environ["REDIS_URL"] or "fakeredis://"
    if _redis_reachable(PERSISTANCE_REDIS_URL):
        log.info("Auto-detected persistance Redis at %s", PERSISTANCE_REDIS_URL)
        return PERSISTANCE_REDIS_URL
    return "fakeredis://"


def _database_url() -> str | None:
    if "DATABASE_URL" in os.environ:
        url = os.environ["DATABASE_URL"].strip()
        return url or None
    if _pg_reachable(PERSISTANCE_DATABASE_URL):
        log.info("Auto-detected persistance Postgres at %s", PERSISTANCE_DATABASE_URL.split("@")[-1])
        return PERSISTANCE_DATABASE_URL
    return None


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
