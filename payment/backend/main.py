"""Payment API — scoped tokens + rail authorize/capture. Port 8004."""
from __future__ import annotations

import hashlib
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config import settings
from rails import charge
from recommender import pick_rail, recommend
from store import draft_record, open_store
from tokens import mint, verify

log = logging.getLogger("payment")
S = settings()
store = open_store(S["database_url"], S["redis_url"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(
        "Payment API ready (store=%s acquirer=%s)",
        store.backend,
        S["mock_acquirer_url"] or "local-mock",
    )
    yield


app = FastAPI(title="HacKU Time-Grocer Payment API", version="0.1.0", lifespan=lifespan)
_origins = list(
    dict.fromkeys(
        [S["frontend_origin"], "http://localhost:5173", "http://127.0.0.1:5173"]
    )
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RecommendIn(BaseModel):
    amount: float = Field(gt=0)
    merchants: list[str] = Field(default_factory=list)
    preferred: str | None = None


class DraftIn(BaseModel):
    account_id: str = "demo"
    amount: float = Field(gt=0)
    currency: Literal["HKD"] = "HKD"
    merchant: str = Field(min_length=1)
    purpose: str = "cart"
    intent: str = ""
    cart_hash: str = ""
    rail: str | None = None
    preferred_rail: str | None = None
    sku: str = ""
    qty: int = 1


class AuthorizeIn(BaseModel):
    payment_id: str
    token: str | None = None
    idempotency_key: str | None = None


class RefundIn(BaseModel):
    reason: str = "customer_request"


def _public(record: dict) -> dict:
    out = {k: v for k, v in record.items() if k != "token"}
    return out


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "payment",
        "store": store.backend,
        "acquirer": S["mock_acquirer_url"] or "local-mock",
        "rails": ["mastercard", "unionpay"],
    }


@app.post("/payment/recommend")
def payment_recommend(body: RecommendIn) -> dict:
    rows = recommend(body.amount, merchants=body.merchants, preferred=body.preferred)
    return {"amount": round(body.amount, 2), "currency": "HKD", "options": rows}


@app.post("/payment/draft")
def payment_draft(body: DraftIn) -> dict:
    choice = pick_rail(
        body.amount,
        merchants=[body.merchant],
        preferred=body.rail or body.preferred_rail,
    )
    rail = body.rail or choice.get("rail") or "mastercard"
    cart_hash = body.cart_hash or hashlib.sha256(
        f"{body.merchant}|{body.amount:.2f}|{body.sku}|{body.qty}".encode()
    ).hexdigest()[:24]
    purpose = body.purpose or f"{body.sku}:{body.qty}"
    token = mint(
        secret=S["token_secret"],
        subject=body.account_id,
        merchant=body.merchant,
        amount=body.amount,
        currency=body.currency,
        purpose=purpose,
        rail=rail,
        ttl=S["token_ttl"],
        issuer=S["issuer"],
    )
    record = draft_record(
        account_id=body.account_id,
        amount=body.amount,
        currency=body.currency,
        merchant=body.merchant,
        rail=rail,
        purpose=purpose,
        intent=body.intent,
        cart_hash=cart_hash,
        token=token,
        recommendation=choice,
    )
    store.put(record)
    return _public(record)


@app.post("/payment/authorize")
def payment_authorize(body: AuthorizeIn) -> dict:
    record = store.get(body.payment_id)
    if record is None:
        raise HTTPException(404, f"Unknown payment: {body.payment_id}")
    if record["status"] in {"AUTHORIZED", "CAPTURED"}:
        return _public(record)
    if record["status"] not in {"DRAFT", "FAILED"}:
        raise HTTPException(409, f"Cannot authorize from status {record['status']}")

    raw_token = body.token or record.get("token")
    if not raw_token:
        raise HTTPException(422, "Missing payment token")
    try:
        claims = verify(raw_token, S["token_secret"], S["issuer"])
    except Exception as exc:
        record["status"] = "FAILED"
        record["error"] = f"token_invalid:{type(exc).__name__}"
        record["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        store.put(record)
        raise HTTPException(403, "Invalid or expired payment token") from exc

    if claims.get("jti") != record["token_jti"]:
        raise HTTPException(403, "Token does not match payment draft")
    if float(claims["amt"]) != float(record["amount"]):
        raise HTTPException(403, "Token amount mismatch")
    if claims.get("aud") != record["merchant"]:
        raise HTTPException(403, "Token merchant mismatch")

    if not store.mark_jti_used(claims["jti"]):
        # Idempotent replay of same token after success is handled above;
        # a second charge attempt with a burned jti is rejected.
        raise HTTPException(409, "Token already used")

    key = body.idempotency_key or f"{record['payment_id']}:{claims['jti']}"
    result = charge(
        amount=record["amount"],
        rail=record["rail"],
        idempotency_key=key,
        acquirer_url=S["mock_acquirer_url"],
    )
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    record["updated_at"] = now
    evidence = list(record.get("evidence") or [])
    if "authorized" not in evidence:
        evidence.append("authorized")
    if not result.get("success"):
        record["status"] = "FAILED"
        record["error"] = result.get("error") or "authorization_failed"
        record["evidence"] = evidence
        store.put(record)
        return _public(record)

    record["status"] = "AUTHORIZED"
    record["auth_id"] = result.get("auth_id")
    record["order_id"] = result.get("order_id")
    record["charged"] = result.get("charged")
    record["reward_points_earned"] = result.get("reward_points_earned")
    record["rail_ts"] = result.get("ts")
    record["error"] = None
    evidence.append("rail_approved")
    # PoC: auto-capture on success (open-loop auth+capture in one step for the mall).
    record["status"] = "CAPTURED"
    record["receipt_id"] = "RCPT-" + (result.get("order_id") or record["payment_id"])[-10:]
    evidence.append("captured")
    record["evidence"] = evidence
    store.put(record)
    return _public(record)


@app.post("/payment/{payment_id}/capture")
def payment_capture(payment_id: str) -> dict:
    record = store.get(payment_id)
    if record is None:
        raise HTTPException(404, f"Unknown payment: {payment_id}")
    if record["status"] == "CAPTURED":
        return _public(record)
    if record["status"] != "AUTHORIZED":
        raise HTTPException(409, f"Cannot capture from status {record['status']}")
    record["status"] = "CAPTURED"
    record["receipt_id"] = record.get("receipt_id") or ("RCPT-" + payment_id[-10:])
    record["evidence"] = list(dict.fromkeys((record.get("evidence") or []) + ["captured"]))
    record["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    store.put(record)
    return _public(record)


@app.post("/payment/{payment_id}/refund")
def payment_refund(payment_id: str, body: RefundIn) -> dict:
    record = store.get(payment_id)
    if record is None:
        raise HTTPException(404, f"Unknown payment: {payment_id}")
    if record["status"] not in {"CAPTURED", "AUTHORIZED"}:
        raise HTTPException(409, f"Cannot refund from status {record['status']}")
    record["status"] = "REFUNDED"
    record["refund_reason"] = body.reason
    record["evidence"] = list(dict.fromkeys((record.get("evidence") or []) + ["refunded"]))
    record["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    store.put(record)
    return _public(record)


@app.get("/payment/{payment_id}")
def payment_get(payment_id: str) -> dict:
    record = store.get(payment_id)
    if record is None:
        raise HTTPException(404, f"Unknown payment: {payment_id}")
    return _public(record)


@app.post("/demo/reset")
def demo_reset() -> dict:
    if not S["demo_mode"]:
        raise HTTPException(404)
    store.reset()
    return {"reset": True}
