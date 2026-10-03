"""
HacKU Time-Grocer mock-api — fake HKTV Mall + payment gateway (offline).

Assumptions:
- Cart `merchant` is optional (acceptance curls omit it); line items use each product's merchant.
- Pay `idempotency_key` is optional; when absent, every call creates a new order.
- Free-shipping threshold is fixed at HK$400; tax is always 0.
- Product filters (q/merchant/category) are case-insensitive.
- No auth, no DB, no outbound network — JSON seed data only.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from data_loader import MerchantsPayload, Product, load_merchants, load_products

FREE_SHIPPING_THRESHOLD = 400.0
SHIPPING_FEE_BELOW_THRESHOLD = 30.0


class CartItemIn(BaseModel):
    sku: str
    qty: int = Field(gt=0)


class CartRequest(BaseModel):
    items: list[CartItemIn]
    merchant: str | None = None


class LineItem(BaseModel):
    sku: str
    name: str
    merchant: str
    category: str
    unit_price: float
    qty: int
    line_total: float


class CartResponse(BaseModel):
    line_items: list[LineItem]
    subtotal: float
    shipping_fee: float
    tax: float
    total_landed_cost: float
    currency: str
    free_shipping_threshold: float


class PayRequest(BaseModel):
    cart_total: float
    payment_route: str
    idempotency_key: str | None = None


class PayResponse(BaseModel):
    success: bool
    order_id: str | None = None
    charged: float | None = None
    currency: str | None = None
    payment_route: str | None = None
    reward_points_earned: int | None = None
    ts: str | None = None
    error: str | None = None


products: list[Product] = []
products_by_id: dict[str, Product] = {}
merchants: MerchantsPayload = MerchantsPayload(whitelist=[], blacklist=[])
idempotency_store: dict[str, PayResponse] = {}


def _money(value: float) -> float:
    return round(float(value), 2)


app = FastAPI(title="HacKU Time-Grocer Mock API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    global products, products_by_id, merchants
    products, products_by_id = load_products()
    merchants = load_merchants()


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.get("/products", response_model=list[Product])
def list_products(
    q: str | None = Query(default=None),
    merchant: str | None = Query(default=None),
    category: str | None = Query(default=None),
) -> list[Product]:
    results = products
    if q:
        needle = q.casefold()
        results = [p for p in results if needle in p.name.casefold()]
    if merchant:
        m = merchant.casefold()
        results = [p for p in results if p.merchant.casefold() == m]
    if category:
        c = category.casefold()
        results = [p for p in results if p.category.casefold() == c]
    return results


@app.get("/products/{sku}", response_model=Product)
def get_product(sku: str) -> Product:
    product = products_by_id.get(sku)
    if product is None:
        raise HTTPException(status_code=404, detail=f"Unknown SKU: {sku}")
    return product


@app.get("/merchants", response_model=MerchantsPayload)
def get_merchants() -> MerchantsPayload:
    return merchants


@app.post("/cart", response_model=CartResponse)
def create_cart(body: CartRequest) -> CartResponse:
    line_items: list[LineItem] = []
    for item in body.items:
        product = products_by_id.get(item.sku)
        if product is None:
            raise HTTPException(status_code=404, detail=f"Unknown SKU: {item.sku}")
        unit = _money(product.price)
        line_items.append(
            LineItem(
                sku=product.id,
                name=product.name,
                merchant=product.merchant,
                category=product.category,
                unit_price=unit,
                qty=item.qty,
                line_total=_money(unit * item.qty),
            )
        )
    subtotal = _money(sum(li.line_total for li in line_items))
    shipping = 0.0 if subtotal >= FREE_SHIPPING_THRESHOLD else SHIPPING_FEE_BELOW_THRESHOLD
    tax = 0.0
    return CartResponse(
        line_items=line_items,
        subtotal=subtotal,
        shipping_fee=_money(shipping),
        tax=_money(tax),
        total_landed_cost=_money(subtotal + shipping + tax),
        currency="HKD",
        free_shipping_threshold=FREE_SHIPPING_THRESHOLD,
    )


@app.post("/pay", response_model=PayResponse)
async def pay(body: PayRequest) -> PayResponse:
    await asyncio.sleep(0.5)

    key = body.idempotency_key
    if key and key in idempotency_store:
        return idempotency_store[key]

    cart_total = _money(body.cart_total)
    if cart_total == 666.0:
        return PayResponse(success=False, error="card_declined", order_id=None)

    order_id = "ORD-" + uuid.uuid4().hex[:8]
    response = PayResponse(
        success=True,
        order_id=order_id,
        charged=cart_total,
        currency="HKD",
        payment_route=body.payment_route,
        reward_points_earned=int(cart_total // 10),
        ts=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    if key:
        idempotency_store[key] = response
    return response
