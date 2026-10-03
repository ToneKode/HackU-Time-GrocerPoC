"""Person 2 — Trust, Policy & Audit service. Port 8001.

Contract: agent-brain/cross_team_config.json (functions.check_budget / log_event /
create_escalation / get_escalation / resolve_escalation) and frontend/contract.json (audit_log).
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Annotated, Literal

import redis
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StringConstraints

import policy_engine
from audit_log import AuditLog
from config import (BULK_CEILING, CATEGORY_BLACKLIST, CURRENCY, MERCHANT_BLACKLIST, MERCHANT_WHITELIST,
                    MONTHLY_CAP, PER_TRANSACTION_CAP, settings)
from escalations import BadSignature, Escalations, NotFound, make_redis

log = logging.getLogger("policy")

S = settings()
USING_FAKEREDIS = S["redis_url"].startswith("fakeredis")
audit = AuditLog(S["ledger_path"])
escalations = Escalations(make_redis(S["redis_url"]), audit, S["ttl"], S["signing_secret"])

NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


@asynccontextmanager
async def lifespan(app: FastAPI):
    if USING_FAKEREDIS:
        log.warning("REDIS_URL not set: using in-process fakeredis. Escalations are lost on restart.")
    else:
        try:
            escalations.r.ping()
            log.info("Connected to Redis at %s", S["redis_url"])
        except redis.RedisError as exc:
            log.error("Cannot reach Redis at %s (%s). Escalation endpoints will return 503 until it is up.",
                      S["redis_url"], exc)

    async def sweeper():                       # logs expiries nobody looked at
        failing = False
        while True:
            try:
                await asyncio.to_thread(escalations.sweep)
                if failing:
                    log.info("sweeper: recovered")
                    failing = False
            except Exception as exc:           # a Redis blip must not kill the sweeper for good
                if not failing:
                    log.error("sweeper: %s: %s. Retrying every second.", type(exc).__name__, exc)
                    failing = True
            await asyncio.sleep(1)
    task = asyncio.create_task(sweeper())
    yield
    task.cancel()


app = FastAPI(title="HacKU Time-Grocer Policy API", version="0.1.0", lifespan=lifespan)
_origins = list(dict.fromkeys([S["frontend_origin"], "http://localhost:5173", "http://127.0.0.1:5173"]))
app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(redis.RedisError)
async def redis_unavailable(_request, exc: redis.RedisError) -> JSONResponse:
    return JSONResponse(status_code=503,
                        content={"detail": "State store (Redis) unavailable. Try again shortly.",
                                 "error": type(exc).__name__})


# ------------------------------------------------------------------ models
class CheckPolicyIn(BaseModel):
    merchant: str
    category: NonEmpty                        # empty/blank would skip the category blacklist, so reject it
    amount: float = Field(ge=0)               # total_landed_cost
    currency: Literal["HKD"] = "HKD"
    sku: str = ""
    qty: int = Field(default=1, ge=1)
    monthly_spent: float = Field(default=0, ge=0)


class LogEventIn(BaseModel):
    event: str = Field(min_length=1)
    status: str = Field(min_length=1)
    reason: str = ""
    thought: str = ""                         # optional, shown in the UI trace; not hashed


class CreateEscalationIn(BaseModel):
    amount: float = Field(gt=0)
    currency: Literal["HKD"] = "HKD"
    merchant: str
    category: NonEmpty                        # needed to re-run the full policy server-side
    sku: str
    qty: int = Field(default=1, ge=1)
    reason: str
    monthly_spent: float = Field(default=0, ge=0)


class DecisionIn(BaseModel):
    decision: Literal["APPROVE", "REFUSE"]
    signature: str | None = None              # optional unless REQUIRE_SIGNATURE=true


# ------------------------------------------------------------------ routes
@app.get("/health")
def health() -> dict:
    try:
        redis_ok = bool(escalations.r.ping())
    except redis.RedisError:
        redis_ok = False
    return {"ok": redis_ok, "audit_entries": len(audit.entries()), "redis": redis_ok,
            "store": "fakeredis" if USING_FAKEREDIS else "redis"}


@app.post("/check_policy")
def check_policy(body: CheckPolicyIn) -> dict:
    return policy_engine.evaluate(body.merchant, body.category, body.amount, body.monthly_spent)


@app.post("/log_event")
def log_event(body: LogEventIn) -> dict:
    return audit.append(body.event, body.status, body.reason, body.thought)


@app.get("/audit_log")
def get_audit_log() -> list[dict]:
    return audit.entries()


@app.get("/audit_log/verify")
def verify_audit_log() -> dict:
    return audit.verify()


@app.post("/create_escalation")
def create_escalation(body: CreateEscalationIn) -> dict:
    # Server-side guard: re-run the whole policy. Only an ESCALATE verdict may open an approval request.
    check = policy_engine.evaluate(body.merchant, body.category, body.amount, body.monthly_spent)
    if check["status"] != "ESCALATE":
        raise HTTPException(422, f"Cannot escalate: {check['reason']}")
    return escalations.create(body.amount, body.currency, body.merchant, body.sku, body.qty, body.reason)


@app.get("/escalations/{escalation_id}")
def get_escalation(escalation_id: str) -> dict:
    try:
        return escalations.get(escalation_id)
    except NotFound:
        raise HTTPException(404, f"Unknown escalation: {escalation_id}")


@app.post("/escalations/{escalation_id}/decision")
def decide_escalation(escalation_id: str, body: DecisionIn) -> dict:
    try:
        return escalations.decide(escalation_id, body.decision, body.signature, S["require_signature"])
    except NotFound:
        raise HTTPException(404, f"Unknown escalation: {escalation_id}")
    except BadSignature:
        raise HTTPException(403, "Invalid approval signature")


@app.get("/rules")
def get_rules() -> dict:
    return {"currency": CURRENCY, "per_transaction_cap": PER_TRANSACTION_CAP, "bulk_ceiling": BULK_CEILING,
            "monthly_cap": MONTHLY_CAP, "escalation_ttl_seconds": S["ttl"],
            "merchant_whitelist": MERCHANT_WHITELIST, "merchant_blacklist": MERCHANT_BLACKLIST,
            "category_blacklist": CATEGORY_BLACKLIST}


# ------------------------------------------------------------------ demo helpers
@app.post("/demo/tamper/{index}")
def demo_tamper(index: int) -> dict:
    if not S["demo_mode"]:
        raise HTTPException(404)
    if not 0 <= index < len(audit.entries()):
        raise HTTPException(422, "No such audit index")
    audit.tamper(index)
    return audit.verify()


@app.post("/demo/reset")
def demo_reset() -> dict:
    if not S["demo_mode"]:
        raise HTTPException(404)
    audit.reset()
    escalations.r.flushdb()
    return {"reset": True}
