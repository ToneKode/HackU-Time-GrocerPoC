"""Persistance API — Postgres audit/spend + Redis escalation TTL. Port 8003.

Owns the durable stores. Policy (8001) can either:
  1. Point DATABASE_URL / REDIS_URL at the same Postgres / Redis and keep serving
     the contract endpoints itself, or
  2. Call this service for ledger / spend / escalation state.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Literal

import redis
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from audit_store import PostgresAuditLog, compute_hash
from config import settings
from db import apply_schema, ping as pg_ping
from escalations import BadSignature, Escalations, NotFound, build_escalations
from redis_client import flush_escalations, make_redis, ping as redis_ping
from spend_store import SpendStore

log = logging.getLogger("persistance")
S = settings()

audit = PostgresAuditLog(S["database_url"])
spend = SpendStore(S["database_url"])
escalations: Escalations = build_escalations(
    S["redis_url"], audit, S["ttl"], S["signing_secret"]
)
USING_FAKEREDIS = S["redis_url"].startswith("fakeredis")


@asynccontextmanager
async def lifespan(app: FastAPI):
    apply_schema(S["database_url"], S["schema_path"])
    try:
        pg_ping(S["database_url"])
        log.info("Postgres ready")
    except Exception as exc:
        log.error("Postgres unavailable: %s", exc)
    if USING_FAKEREDIS:
        log.warning("REDIS_URL is fakeredis — escalations will not survive restarts")
    else:
        try:
            escalations.r.ping()
            log.info("Redis ready at %s", S["redis_url"])
        except redis.RedisError as exc:
            log.error("Redis unavailable at %s: %s", S["redis_url"], exc)

    async def sweeper():
        failing = False
        while True:
            try:
                await asyncio.to_thread(escalations.sweep)
                if failing:
                    log.info("sweeper: recovered")
                    failing = False
            except Exception as exc:
                if not failing:
                    log.error(
                        "sweeper: %s: %s. Retrying every second.",
                        type(exc).__name__,
                        exc,
                    )
                    failing = True
            await asyncio.sleep(1)

    task = asyncio.create_task(sweeper())
    yield
    task.cancel()


app = FastAPI(
    title="HacKU Time-Grocer Persistance API",
    version="0.1.0",
    lifespan=lifespan,
)
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


@app.exception_handler(redis.RedisError)
async def redis_unavailable(_request, exc: redis.RedisError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "detail": "State store (Redis) unavailable. Try again shortly.",
            "error": type(exc).__name__,
        },
    )


# ------------------------------------------------------------------ models
class LogEventIn(BaseModel):
    event: str = Field(min_length=1)
    status: str = Field(min_length=1)
    reason: str = ""
    thought: str = ""


class CreateEscalationIn(BaseModel):
    amount: float = Field(gt=0)
    currency: Literal["HKD"] = "HKD"
    merchant: str
    sku: str
    qty: int = Field(default=1, ge=1)
    reason: str


class DecisionIn(BaseModel):
    decision: Literal["APPROVE", "REFUSE"]
    signature: str | None = None


class SpendRecordIn(BaseModel):
    account_id: str = Field(min_length=1)
    amount: float = Field(gt=0)
    currency: Literal["HKD"] = "HKD"
    year_month: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    payment_id: str | None = None
    idempotency_key: str | None = None
    note: str = ""


# ------------------------------------------------------------------ routes
@app.get("/health")
def health() -> dict:
    postgres_ok = False
    redis_ok = False
    try:
        postgres_ok = pg_ping(S["database_url"])
    except Exception:
        postgres_ok = False
    try:
        redis_ok = bool(escalations.r.ping())
    except redis.RedisError:
        redis_ok = False
    return {
        "ok": postgres_ok and redis_ok,
        "postgres": postgres_ok,
        "redis": redis_ok,
        "audit_entries": len(audit.entries()) if postgres_ok else None,
        "store": {
            "audit": "postgres",
            "escalations": "fakeredis" if USING_FAKEREDIS else "redis",
            "spend": "postgres",
        },
    }


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
    # Store-only: no policy re-check here. Policy owns the ESCALATE guard.
    return escalations.create(
        body.amount, body.currency, body.merchant, body.sku, body.qty, body.reason
    )


@app.get("/escalations/{escalation_id}")
def get_escalation(escalation_id: str) -> dict:
    try:
        return escalations.get(escalation_id)
    except NotFound:
        raise HTTPException(404, f"Unknown escalation: {escalation_id}")


@app.post("/escalations/{escalation_id}/decision")
def decide_escalation(escalation_id: str, body: DecisionIn) -> dict:
    try:
        return escalations.decide(
            escalation_id, body.decision, body.signature, S["require_signature"]
        )
    except NotFound:
        raise HTTPException(404, f"Unknown escalation: {escalation_id}")
    except BadSignature:
        raise HTTPException(403, "Invalid approval signature")


@app.get("/spend/{account_id}")
def get_spend(
    account_id: str,
    year_month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
) -> dict:
    return spend.get(account_id, year_month)


@app.post("/spend")
def record_spend(body: SpendRecordIn) -> dict:
    try:
        return spend.record(
            body.account_id,
            body.amount,
            currency=body.currency,
            year_month=body.year_month,
            payment_id=body.payment_id,
            idempotency_key=body.idempotency_key,
            note=body.note,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))


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
    spend.reset()
    removed = flush_escalations(escalations.r)
    return {"reset": True, "escalation_keys_removed": removed}


@app.get("/_meta/hash_fields")
def hash_fields() -> dict:
    # Handy for cross-checking the contract without importing audit_store.
    sample = {
        "index": 0,
        "ts": "2026-10-03T12:00:00Z",
        "event": "INTENT_RECEIVED",
        "status": "PARSED",
        "reason": "Model may decide query and qty only",
        "prev_hash": "0" * 64,
    }
    return {
        "hash_fields_in_order": list(
            ("index", "ts", "event", "status", "reason", "prev_hash")
        ),
        "contract_example_hash": compute_hash(sample),
    }
