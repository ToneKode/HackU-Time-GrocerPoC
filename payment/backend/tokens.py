"""Scoped one-time payment tokens (workshop Topic 4 — least privilege).

JWT claims: iss, sub, aud (merchant), amt, cur, pur, exp, jti, one_time_use, rail.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

import jwt

ALG = "HS256"


def mint(
    *,
    secret: str,
    subject: str,
    merchant: str,
    amount: float,
    currency: str,
    purpose: str,
    rail: str,
    ttl: int,
    issuer: str,
) -> dict[str, Any]:
    now = int(time.time())
    jti = "tok_" + uuid.uuid4().hex[:16]
    payload = {
        "iss": issuer,
        "sub": subject,
        "aud": merchant,
        "amt": round(float(amount), 2),
        "cur": currency,
        "pur": purpose,
        "rail": rail,
        "exp": now + int(ttl),
        "iat": now,
        "jti": jti,
        "one_time_use": True,
    }
    token = jwt.encode(payload, secret, algorithm=ALG)
    return {"token": token, "jti": jti, "expires_at": payload["exp"], "claims": payload}


def verify(token: str, secret: str, issuer: str) -> dict[str, Any]:
    # aud is our merchant id, not an OAuth audience list — check it ourselves.
    return jwt.decode(
        token,
        secret,
        algorithms=[ALG],
        issuer=issuer,
        options={
            "require": ["exp", "jti", "amt", "aud", "sub"],
            "verify_aud": False,
        },
    )
