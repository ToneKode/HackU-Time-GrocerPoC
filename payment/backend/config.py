"""Payment service settings.

When DATABASE_URL is unset, probe the persistance compose default and use it
if Postgres is up. An explicit empty DATABASE_URL keeps the in-memory store
(unit tests).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger("payment.config")

# Matches persistance/compose.yaml
PERSISTANCE_DATABASE_URL = "postgresql://tg:tg@127.0.0.1:5432/time_grocer"

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


def _pg_reachable(url: str) -> bool:
    try:
        import psycopg

        with psycopg.connect(url, connect_timeout=1) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                return cur.fetchone() is not None
    except Exception:
        return False


def _database_url() -> str:
    # Explicit DATABASE_URL always wins, including "" (tests stay in memory).
    if "DATABASE_URL" in os.environ:
        return os.environ["DATABASE_URL"].strip()
    if _pg_reachable(PERSISTANCE_DATABASE_URL):
        log.info(
            "Auto-detected persistance Postgres at %s",
            PERSISTANCE_DATABASE_URL.split("@")[-1],
        )
        return PERSISTANCE_DATABASE_URL
    return ""


def settings() -> dict:
    return {
        "port": int(env("PAYMENT_API_PORT", "8004")),
        "frontend_origin": env("FRONTEND_ORIGIN", "http://localhost:5173"),
        "token_secret": env("PAYMENT_TOKEN_SECRET", "dev-payment-secret-change-me"),
        "token_ttl": int(env("PAYMENT_TOKEN_TTL_SECONDS", "600")),
        "mock_acquirer_url": env("MOCK_ACQUIRER_URL", "").rstrip("/"),
        "redis_url": env("REDIS_URL", ""),
        "database_url": _database_url(),
        "demo_mode": env("DEMO_MODE", "true").lower() == "true",
        "issuer": env("PAYMENT_ISSUER", "payment.time-grocer.local"),
    }
