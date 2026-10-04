"""Payment service settings.

When DATABASE_URL is unset, probe host MySQL and use it if it answers.
An explicit empty DATABASE_URL keeps the in-memory store (unit tests).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

log = logging.getLogger("payment.config")

# Host MySQL that already holds the shop catalog. Do not probe Postgres.
PERSISTANCE_DATABASE_URL = "mysql://tg:tg@127.0.0.1:3306/time_grocer"

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


def _mysql_reachable(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"mysql", "mysql+pymysql"}:
        return False
    try:
        import pymysql

        conn = pymysql.connect(
            host=parsed.hostname or "127.0.0.1",
            port=parsed.port or 3306,
            user=unquote(parsed.username or ""),
            password=unquote(parsed.password or ""),
            database=(parsed.path or "").lstrip("/") or None,
            connect_timeout=1,
        )
        conn.close()
        return True
    except Exception:
        return False


def _database_url() -> str:
    # Explicit DATABASE_URL always wins, including "" (tests stay in memory).
    if "DATABASE_URL" in os.environ:
        return os.environ["DATABASE_URL"].strip()
    if _mysql_reachable(PERSISTANCE_DATABASE_URL):
        log.info("Auto-detected shop MySQL at %s", PERSISTANCE_DATABASE_URL.split("@")[-1])
        return PERSISTANCE_DATABASE_URL
    return ""


def settings() -> dict:
    return {
        "persistance_url": env("PERSISTANCE_API_BASE_URL", "http://127.0.0.1:8003").rstrip("/"),
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
