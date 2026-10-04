"""One approval for merchant-scoped payment drafts, with resumable partial captures.

Single and basket drafts accept optional lines: [{sku, qty}]. Purchased quantities
are quoted server-side through PERSISTANCE_API_BASE_URL (default localhost:8003).
Basket groups must exactly match the quote's merchant totals. A changed amount
returns 409 with {message, quote} in detail. market_quote is saved on parent and
children; settlement verifies its frozen rules and prices and saves gift lines.
Caller-supplied snapshots are ignored. Legacy amount-only drafts remain supported
but do not provide catalog promotion verification.
"""
from __future__ import annotations

from decimal import Decimal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator


def money(value):
    amount = Decimal(str(value))
    if not amount.is_finite() or amount <= 0 or amount != amount.quantize(Decimal('0.01')):
        raise ValueError('Amount must be positive HKD with at most two decimal places')
    return value


class MerchantPayment(BaseModel):
    merchant: str = Field(min_length=1)
    amount: float = Field(gt=0, allow_inf_nan=False)
    rail: str = Field(min_length=1)

    _validate_amount = field_validator('amount')(money)


class BasketDraftIn(BaseModel):
    account_id: str
    intent: str = ""
    groups: list[MerchantPayment] = Field(min_length=1, max_length=20)
    lines: list[dict] | None = None


def _public(record):
    return {key: value for key, value in record.items() if key != "token"}


def basket_router(store, create_draft, draft_model, fetch_quote=None):
    router = APIRouter()

    @router.post("/payment/basket/draft")
    def create_basket(body: BasketDraftIn):
        if len({group.merchant for group in body.groups}) != len(body.groups):
            raise HTTPException(422, "Each merchant must have one payment allocation")
        groups = [group.model_dump() for group in body.groups]
        quote = fetch_quote(body.lines) if body.lines is not None else None
        if quote is not None:
            amounts = {row["merchant"]: Decimal(str(row["total"])) for row in quote["merchants"]}
            if amounts != {row["merchant"]: Decimal(str(row["amount"])) for row in groups}:
                raise HTTPException(409, {"message": "Catalog price or promotion changed; approve a new quote", "quote": quote})
        children = []
        for group in groups:
            row = create_draft(draft_model(account_id=body.account_id, amount=group["amount"],
                               merchant=group["merchant"], rail=group["rail"], intent=body.intent))
            if quote is not None:
                child = store.get(row["payment_id"])
                child["market_quote"] = quote
                child["market_merchant"] = group["merchant"]
                store.put(child)
            children.append(row["payment_id"])
        total = float(sum(Decimal(str(group["amount"])) for group in groups))
        parent = create_draft(draft_model(account_id=body.account_id, amount=total,
                              merchant=", ".join(group["merchant"] for group in groups),
                              rail=groups[0]["rail"], intent=body.intent, purpose="merchant_basket"))
        record = store.get(parent["payment_id"])
        if quote is not None:
            record["market_quote"] = quote
        record.update(children=children, allocations=groups, rail="split",
                      step_up_required=total >= 400 or any(store.get(pid).get("step_up_required") for pid in children),
                      step_up_reason="Approve the merchant payment allocations together" if total >= 400 else "")
        store.put(record)
        return _public(record)

    return router


def authorize_basket(store, authorize_one, authorize_model, record, step_up_confirmed, prepare_one=None):
    if record.get("status") == "CAPTURED":
        return _public(record)
    if record.get("status") not in {"DRAFT", "PENDING", "FAILED"}:
        raise HTTPException(409, "Basket cannot be authorized from this status")
    approved = step_up_confirmed or record.get("step_up_confirmed", False)
    if record.get("step_up_required") and not approved:
        raise HTTPException(403, "step_up_required")
    record["step_up_confirmed"] = approved
    record["attempt_started"] = True
    record["status"] = "PENDING"
    store.put(record)
    if prepare_one is not None:
        for payment_id in record["children"]:
            child = store.get(payment_id)
            if child is None or child.get("account_id") != record["account_id"]:
                raise HTTPException(409, "Merchant payment account mismatch")
            prepare_one(child, authorize_model(payment_id=payment_id, step_up_confirmed=approved))
    results = []
    for payment_id in record["children"]:
        try:
            child = authorize_one(authorize_model(payment_id=payment_id, step_up_confirmed=approved))
        except HTTPException as exc:
            record["error"] = f"Merchant payment needs attention: {exc.detail}"
            record["partial_captures"] = [row["payment_id"] for row in results if row.get("status") == "CAPTURED"]
            store.put(record)
            return _public(record)
        results.append(child)
        if child.get("status") != "CAPTURED":
            record["error"] = child.get("error") or "Merchant payment pending"
            record["partial_captures"] = [row["payment_id"] for row in results if row.get("status") == "CAPTURED"]
            store.put(record)
            return _public(record)
    if any(row.get("account_id") != record["account_id"] or row.get("rail_verified") is not True
           or row.get("charged_currency") != record["currency"] for row in results):
        raise HTTPException(409, "Merchant capture evidence mismatch")
    charged = sum(Decimal(str(row["charged"])) for row in results)
    if charged != Decimal(str(record["amount"])):
        raise HTTPException(409, "Merchant captures do not match the basket amount")
    record.update(status="CAPTURED", charged=float(charged), rail_verified=True,
                  charged_currency=record["currency"], captures=results,
                  order_id="BASKET-" + record["payment_id"], receipt_id="RCPT-" + record["payment_id"],
                  error=None, partial_captures=[], evidence=["merchant_allocations_approved", "captured"],
                  updated_at=results[-1].get("updated_at"))
    store.put(record)
    return _public(record)
