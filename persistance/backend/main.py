"""Persistance API — MySQL audit/spend/catalog + Redis health. Port 8003.

Owns the durable stores. Person 2 (backend-policy :8001) owns the public contract
for policy checks and escalation TTL decisions; this service exposes:

  - health / demo reset
  - hash-chained audit ledger (MySQL)
  - monthly spend (MySQL) — agent reads before policy, writes after pay
  - product shelf (MySQL) — the shop reads GET /catalog/products

Escalation HTTP create/decide live only on :8001 so the agent has one owner.
Redis keys are still shared when REDIS_URL points at the same instance.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Literal

import redis
from pymysql.err import InterfaceError, OperationalError
from fastapi import FastAPI, HTTPException, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from audit_store import PostgresAuditLog, compute_hash
from catalog_store import CatalogStore
from market_store import MarketStore, MarketRules, QuoteLine
from config import settings
from dashboard_store import DashboardStore
from db import apply_schema, ensure_database, ping as pg_ping
from profile_store import AccountExists, BadPayment, NotFound, ProfileStore
from redis_client import flush_escalations, make_redis
from spend_store import SpendStore
from settlement_verifier import fetch_payment, verified_settlement

log = logging.getLogger("persistance")
S = settings()

audit = PostgresAuditLog(S["database_url"])
spend = SpendStore(S["database_url"])
profile = ProfileStore(S["database_url"])
catalog = CatalogStore(S["database_url"])
market = MarketStore(S["database_url"])
dashboards = DashboardStore(S["database_url"])
redis_client = make_redis(S["redis_url"])
USING_FAKEREDIS = S["redis_url"].startswith("fakeredis")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        ensure_database(S["database_url"])
        apply_schema(S["database_url"], S["schema_path"])
    except Exception as exc:
        log.error("MySQL schema was not applied: %s", exc)
    try:
        pg_ping(S["database_url"])
        log.info("MySQL ready")
    except Exception as exc:
        log.error("MySQL unavailable: %s", exc)
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
    mysql_ok = False
    redis_ok = False
    try:
        mysql_ok = pg_ping(S["database_url"])
    except Exception:
        mysql_ok = False
    try:
        redis_ok = bool(redis_client.ping())
    except redis.RedisError:
        redis_ok = False
    catalog_products = None
    if mysql_ok:
        try:
            catalog_products = catalog.count()
        except Exception:
            catalog_products = None
    return {
        "ok": mysql_ok and redis_ok,
        "mysql": mysql_ok,
        "redis": redis_ok,
        "audit_entries": len(audit.entries()) if mysql_ok else None,
        "catalog_products": catalog_products,
        "store": {
            "audit": "mysql",
            "escalations": "policy:8001+redis",
            "spend": "mysql",
            "profile": "mysql",
            "catalog": "mysql",
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


class RegisterIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=8, max_length=200)
    name: str = Field(min_length=1, max_length=80)
    phone: str = ""
    marketing: bool = False


class LoginIn(BaseModel):
    email: str = Field(min_length=1)
    password: str = Field(min_length=1)


class LimitsIn(BaseModel):
    monthly_cap: float | None = Field(default=None, ge=0)
    per_order_cap: float | None = Field(default=None, ge=0)
    bulk_ceiling: float | None = Field(default=None, ge=0)
    membership: str | None = None


class PaymentMethodIn(BaseModel):
    route: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=80)
    last4: str = ""
    connected: bool = True
    is_default: bool = False


class OrderOpenIn(BaseModel):
    account_id: str = Field(min_length=1)
    intent: str = Field(min_length=1)


class CheckpointIn(BaseModel):
    step: str = Field(min_length=1)
    status: str = Field(min_length=1)
    snapshot: dict = Field(default_factory=dict)
    amount: float | None = Field(default=None, ge=0)
    merchant: str | None = None
    payment_route: str | None = None
    payment_id: str | None = None
    escalation_id: str | None = None
    lines: list[dict] | None = None


class ChatIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)
    order_id: str | None = None


class TaskIn(BaseModel):
    intent: str = Field(min_length=1)
    cadence: str = "monthly"


class PreferenceMethodIn(BaseModel):
    id: str | None = None
    route: str | None = None
    connected: bool = True


class PreferencesIn(BaseModel):
    benefit_rank: list[str] | None = None
    methods: list[PreferenceMethodIn] | None = None


class SettleLineIn(BaseModel):
    sku: str = ""
    name: str = ""
    merchant: str = ""
    category: str = ""
    qty: int = 1
    unit_price: float = 0
    line_total: float = 0


class BenefitIn(BaseModel):
    kind: str
    amount: float = 0
    detail: str = ""


class SettleIn(BaseModel):
    amount: float = Field(gt=0)
    currency: Literal["HKD"] = "HKD"
    merchant: str = ""
    payment_route: str = ""
    payment_id: str = Field(min_length=1, pattern=r"^pay_[A-Za-z0-9_-]+$")
    intent: str = ""
    lines: list[SettleLineIn] = Field(default_factory=list)
    settlement: dict | None = None
    benefits: list[BenefitIn] = Field(default_factory=list)


def _profile_call(fn):
    try:
        return fn()
    except AccountExists:
        raise HTTPException(409, "An account with this email already exists")
    except NotFound:
        raise HTTPException(404, "Unknown account or order")
    except BadPayment as exc:
        raise HTTPException(422, str(exc))
    except (OperationalError, InterfaceError):
        raise HTTPException(503, "Database unavailable")


def _email_ok(email: str) -> bool:
    host = email.split("@")[-1] if "@" in email else ""
    return "@" in email and not email.startswith("@") and "." in host


@app.post("/accounts/register")
def register_account(body: RegisterIn) -> dict:
    email = body.email.strip().lower()
    if not _email_ok(email):
        raise HTTPException(422, "Enter a valid email address")
    return _profile_call(
        lambda: profile.register(email, body.password, body.name, body.phone, body.marketing)
    )


@app.post("/accounts/login")
def login_account(body: LoginIn) -> dict:
    found = _profile_call(lambda: profile.authenticate(body.email, body.password))
    if found is None:
        raise HTTPException(401, "Email or password is wrong")
    found["role"] = "admin" if found["email"].lower() in S["demo_admin_emails"] else "shopper"
    return found


@app.get("/accounts/{account_id}/profile")
def get_profile(account_id: str) -> dict:
    found = _profile_call(lambda: profile.profile(account_id))
    found["role"] = "admin" if found["email"].lower() in S["demo_admin_emails"] else "shopper"
    return found


@app.patch("/accounts/{account_id}/limits")
def patch_limits(account_id: str, body: LimitsIn) -> dict:
    return _profile_call(
        lambda: profile.update_limits(
            account_id,
            monthly_cap=body.monthly_cap,
            per_order_cap=body.per_order_cap,
            bulk_ceiling=body.bulk_ceiling,
            membership=body.membership,
        )
    )


@app.post("/accounts/{account_id}/payment-methods")
def add_payment_method(account_id: str, body: PaymentMethodIn) -> dict:
    return _profile_call(
        lambda: profile.add_payment_method(
            account_id,
            body.route,
            body.label,
            body.last4,
            connected=body.connected,
            is_default=body.is_default,
        )
    )


@app.patch("/accounts/{account_id}/preferences")
def patch_preferences(account_id: str, body: PreferencesIn) -> dict:
    methods = [item.model_dump() for item in body.methods] if body.methods is not None else None
    return _profile_call(
        lambda: profile.save_preferences(account_id, body.benefit_rank, methods)
    )


@app.post("/accounts/{account_id}/orders/settle")
def settle_order(account_id: str, body: SettleIn) -> dict:
    payment = fetch_payment(S["payment_url"], body.payment_id)
    try:
        authoritative = verified_settlement(payment, account_id, body.payment_id, body.amount, body.currency)
        saved = profile.record_paid(
            account_id,
            body.amount,
            currency=body.currency,
            merchant=authoritative["merchant"],
            payment_route=authoritative["payment_route"],
            payment_id=body.payment_id,
            intent=payment.get("intent") or body.intent,
            lines=authoritative.get("lines", [line.model_dump() for line in body.lines]),
            settlement=authoritative,
            benefits=authoritative["benefits"],
        )
    except NotFound:
        raise HTTPException(404, "Unknown account or order")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except (OperationalError, InterfaceError):
        raise HTTPException(503, "Database unavailable")
    if not saved["duplicate"]:
        saved["audit"] = audit.append(
            "ORDER_PAID",
            "COMPLETED",
            f"{saved['order_id']} HK${body.amount:.2f}",
            body.intent or "approved basket",
        )
    return saved


@app.get("/accounts/{account_id}/orders")
def list_orders(
    account_id: str,
    status: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
) -> list[dict]:
    return _profile_call(lambda: profile.list_orders(account_id, status=status, limit=limit))


@app.get("/accounts/{account_id}/dashboard")
def account_dashboard(account_id: str, recent: int = Query(default=20, ge=1, le=100)) -> dict:
    """Order history, spend by category, lifetime spend and benefits for one shopper."""
    return _profile_call(lambda: dashboards.dashboard(account_id, recent=recent))


@app.get("/accounts/{account_id}/chat")
def list_chat(account_id: str, limit: int = Query(default=50, ge=1, le=200)) -> list[dict]:
    return _profile_call(lambda: profile.list_chat(account_id, limit))


@app.post("/accounts/{account_id}/chat")
def add_chat(account_id: str, body: ChatIn) -> dict:
    return _profile_call(lambda: profile.add_chat(account_id, body.role, body.content, body.order_id))


@app.delete("/accounts/{account_id}/chat")
def delete_chat(account_id: str) -> dict:
    removed = _profile_call(lambda: profile.clear_chat(account_id))
    return {"cleared": True, "removed": removed}


@app.get("/accounts/{account_id}/tasks")
def list_tasks(account_id: str) -> list[dict]:
    return _profile_call(lambda: profile.list_tasks(account_id))


@app.post("/accounts/{account_id}/tasks")
def add_task(account_id: str, body: TaskIn) -> dict:
    return _profile_call(lambda: profile.add_task(account_id, body.intent, body.cadence))


@app.get("/accounts/{account_id}/agent-history")
def agent_history(account_id: str, limit: int = Query(default=20, ge=1, le=50)) -> list[dict]:
    return _profile_call(lambda: profile.list_agent_history(account_id, limit))


@app.post("/orders")
def open_order(body: OrderOpenIn) -> dict:
    return _profile_call(lambda: profile.open_order(body.account_id, body.intent))


@app.get("/orders/{order_id}")
def get_order(order_id: str) -> dict:
    return _profile_call(lambda: profile.get_order(order_id))


@app.post("/orders/{order_id}/checkpoint")
def save_checkpoint(order_id: str, body: CheckpointIn) -> dict:
    return _profile_call(
        lambda: profile.checkpoint(
            order_id,
            step=body.step,
            status=body.status,
            snapshot=body.snapshot,
            amount=body.amount,
            merchant=body.merchant,
            payment_route=body.payment_route,
            payment_id=body.payment_id,
            escalation_id=body.escalation_id,
            lines=body.lines,
        )
    )


@app.get("/catalog/categories")
def catalog_categories() -> list[dict]:
    return _profile_call(lambda: catalog.categories())


@app.get("/catalog/products")
def catalog_products(
    q: str = "",
    merchant: str = "",
    category: str = "",
    limit: int = Query(default=48, ge=1, le=6000),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    return _profile_call(
        lambda: catalog.search(q, merchant=merchant, category=category, limit=limit, offset=offset)
    )


@app.get("/catalog/search")
def catalog_search(
    q: str = "", merchant: str = "", category: str = "",
    limit: int = Query(default=40, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    return _profile_call(lambda: catalog.search_page(q, merchant, category, limit, offset))


@app.get("/catalog/products/{sku}")
def catalog_product(sku: str) -> dict:
    row = _profile_call(lambda: catalog.get(sku))
    if row is None:
        raise HTTPException(404, "Unknown SKU")
    return row


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


class AdminRulesIn(BaseModel):
    account_id: str = Field(min_length=1)
    rules: MarketRules


class AdminPriceIn(BaseModel):
    account_id: str = Field(min_length=1)
    price: float = Field(gt=0, allow_inf_nan=False, multiple_of=0.01)


class MarketQuoteIn(BaseModel):
    lines: list[QuoteLine] = Field(min_length=1, max_length=200)


def require_admin(account_id: str, password: str | None):
    actor = _profile_call(lambda: profile.profile(account_id))
    if actor["email"].lower() not in S["demo_admin_emails"]:
        raise HTTPException(403, "Market administration requires the demo admin role")
    verified = _profile_call(lambda: profile.authenticate(actor["email"], password or ""))
    if verified is None or verified["id"] != account_id:
        raise HTTPException(401, "Admin account password required in X-Admin-Password")
    return actor


@app.get("/market/rules")
def market_rules():
    return _profile_call(market.get)


@app.get("/admin/market/rules")
def admin_market_rules(account_id: str, x_admin_password: str | None = Header(default=None)):
    require_admin(account_id, x_admin_password)
    return _profile_call(market.get)


@app.put("/admin/market/rules")
def admin_put_market_rules(body: AdminRulesIn, x_admin_password: str | None = Header(default=None)):
    require_admin(body.account_id, x_admin_password)
    try:
        return _profile_call(lambda: market.put(body.rules.model_dump(), body.account_id))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.patch("/admin/catalog/{sku}")
def admin_catalog_price(sku: str, body: AdminPriceIn, x_admin_password: str | None = Header(default=None)):
    require_admin(body.account_id, x_admin_password)
    result = _profile_call(lambda: catalog.update_price(sku, body.price))
    if result is None:
        raise HTTPException(404, "Unknown SKU")
    return result


@app.post("/market/quote")
def market_quote(body: MarketQuoteIn):
    try:
        return _profile_call(lambda: market.quote([line.model_dump() for line in body.lines]))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
