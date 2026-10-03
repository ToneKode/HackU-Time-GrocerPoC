"""Persistance API — Postgres audit/spend + Redis health. Port 8003.

Owns the durable stores. Person 2 (backend-policy :8001) owns the public contract
for policy checks and escalation TTL decisions; this service exposes:

  - health / demo reset
  - hash-chained audit ledger (Postgres)
  - monthly spend (Postgres) — agent reads before policy, writes after pay

Escalation HTTP create/decide live only on :8001 so the agent has one owner.
Redis keys are still shared when REDIS_URL points at the same instance.
"""
from __future__ import annotations

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
from redis_client import flush_escalations, make_redis
from spend_store import SpendStore

log = logging.getLogger("persistance")
S = settings()

audit = PostgresAuditLog(S["database_url"])
spend = SpendStore(S["database_url"])
redis_client = make_redis(S["redis_url"])
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
        log.warning("REDIS_URL is fakeredis — use persistance Redis for real TTLs")
    else:
        try:
            redis_client.ping()
            log.info("Redis ready at %s (escalation API is on policy :8001)", S["redis_url"])
        except redis.RedisError as exc:
            log.error("Redis unavailable at %s: %s", S["redis_url"], exc)
    yield


app = FastAPI(
    title="HacKU Time-Grocer Persistance API",
    version="0.2.0",
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


class LogEventIn(BaseModel):
    event: str = Field(min_length=1)
    status: str = Field(min_length=1)
    reason: str = ""
    thought: str = ""


class SpendRecordIn(BaseModel):
    account_id: str = Field(min_length=1)
    amount: float = Field(gt=0)
    currency: Literal["HKD"] = "HKD"
    year_month: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    payment_id: str | None = None
    idempotency_key: str | None = None
    note: str = ""


@app.get("/health")
def health() -> dict:
    postgres_ok = False
    redis_ok = False
    try:
        postgres_ok = pg_ping(S["database_url"])
    except Exception:
        postgres_ok = False
    try:
        redis_ok = bool(redis_client.ping())
    except redis.RedisError:
        redis_ok = False
    return {
        "ok": postgres_ok and redis_ok,
        "postgres": postgres_ok,
        "redis": redis_ok,
        "audit_entries": len(audit.entries()) if postgres_ok else None,
        "store": {
            "audit": "postgres",
            "escalations": "policy:8001+redis",
            "spend": "postgres",
        },
        "escalation_owner": "backend-policy:8001",
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
    removed = flush_escalations(redis_client)
    return {"reset": True, "escalation_keys_removed": removed}


@app.get("/_meta/hash_fields")
def hash_fields() -> dict:
    sample = {
        "index": 0,
        "ts": "2026-10-03T12:00:00Z",
        "event": "INTENT_RECEIVED",
        "status": "PARSED",
        "reason": "Model may decide query and qty only",
        "prev_hash": "0" * 64,
    }
    return {
        "hash_fields_in_order": [
            "index",
            "ts",
            "event",
            "status",
            "reason",
            "prev_hash",
        ],
        "contract_example_hash": compute_hash(sample),
        "escalation_owner": "backend-policy:8001",
    }
