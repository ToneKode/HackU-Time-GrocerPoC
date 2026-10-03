"""Payment service settings."""
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
        "port": int(env("PAYMENT_API_PORT", "8004")),
        "frontend_origin": env("FRONTEND_ORIGIN", "http://localhost:5173"),
        "token_secret": env("PAYMENT_TOKEN_SECRET", "dev-payment-secret-change-me"),
        "token_ttl": int(env("PAYMENT_TOKEN_TTL_SECONDS", "600")),
        "mock_acquirer_url": env("MOCK_ACQUIRER_URL", "").rstrip("/"),
        "redis_url": env("REDIS_URL", ""),
        "demo_mode": env("DEMO_MODE", "true").lower() == "true",
        "issuer": env("PAYMENT_ISSUER", "payment.time-grocer.local"),
    }
