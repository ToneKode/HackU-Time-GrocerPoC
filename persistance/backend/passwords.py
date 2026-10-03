"""Password hashes for shopper accounts. The database never stores the password."""
from __future__ import annotations

import hashlib
import secrets

ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), ITERATIONS
    ).hex()
    return f"pbkdf2_sha256${ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt, digest = stored.split("$", 3)
        count = int(rounds)
    except (ValueError, AttributeError):
        return False
    if algorithm != "pbkdf2_sha256" or count < 1:
        return False
    check = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), count
    ).hex()
    return secrets.compare_digest(check, digest)
