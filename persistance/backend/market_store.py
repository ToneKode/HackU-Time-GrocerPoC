"""Shared live market rules and deterministic catalog pricing.

GET /market/rules returns version, merchant_discounts and sku_gifts.
GET /admin/market/rules takes account_id query and X-Admin-Password header.
PUT /admin/market/rules takes {account_id, rules: {merchant_discounts:
[{merchant, percent, threshold}], sku_gifts: [{sku, gift_sku}], payment_promotions:
[{route, kind, rate, merchant, enabled}]}} and that header. Payment rates are
reward units per discounted goods HKD; merchant-specific rates override general
rates of the same route and kind. An empty promotion list disables rewards.
PATCH /admin/catalog/{sku} takes {account_id, price} and that header.
POST /market/quote takes {lines: [{sku, qty}]} and returns lines, merchants,
subtotal, discount, total, rules_version and promotion_snapshot.

DEMO_ADMIN_EMAILS is the server-side email role allowlist. Demo credentials are
demo-admin@example.com / DemoAdminOnly!; provision with seed_test_accounts.py
--admin-only. Accounts have password hashes but no session tokens. Admin requests
verify both the allowlisted database account and its password. Existing account
APIs retain their PoC account-ID authorization limitations.

Absent stored overrides preserve the default discounts. Empty saved rules disable
offers. Gifts are one unit per purchased unit at the same merchant, without
recursion. Prices and rules are read from MySQL for each quote, without a daily
script. Quotes contain no shipping or tax. Payment drafts with optional lines
fetch and persist the server quote; settlement uses its exact rules and prices.
"""
from __future__ import annotations

import json
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from pydantic import BaseModel, Field, model_validator

from db import connect
from catalog_store import _SELECT, _public


class MerchantDiscount(BaseModel):
    merchant: str = Field(min_length=1, max_length=80)
    percent: float = Field(ge=0, le=100, allow_inf_nan=False)
    threshold: float = Field(ge=0, allow_inf_nan=False)


class SkuGift(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    gift_sku: str = Field(min_length=1, max_length=64)


DEFAULT_PAYMENT_PROMOTIONS = [
    {"route": "mastercard", "kind": "membership_points", "rate": 2, "merchant": "Watsons", "enabled": True},
    {"route": "mastercard", "kind": "membership_points", "rate": 1, "merchant": "", "enabled": True},
    {"route": "mastercard", "kind": "cash", "rate": 0.024, "merchant": "", "enabled": True},
    {"route": "visa", "kind": "asiamiles", "rate": 0.125, "merchant": "", "enabled": True},
    {"route": "alipay", "kind": "loyalty_points", "rate": 0.25, "merchant": "", "enabled": True},
    {"route": "mastercard", "kind": "asiamiles", "rate": 0.1, "merchant": "", "enabled": False},
]


class PaymentPromotion(BaseModel):
    route: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    kind: Literal["cash", "asiamiles", "membership_points", "loyalty_points"]
    rate: float = Field(ge=0, allow_inf_nan=False)
    merchant: str = Field(default="", max_length=80)
    enabled: bool = True

    @model_validator(mode="after")
    def supported_rate(self):
        maximum = 1 if self.kind == "cash" else 1000000
        if self.rate > maximum:
            raise ValueError("Cashback cannot exceed 100%; miles and points must stay within supported rates")
        return self


class MarketRules(BaseModel):
    merchant_discounts: list[MerchantDiscount] = Field(default_factory=list, max_length=100)
    sku_gifts: list[SkuGift] = Field(default_factory=list, max_length=1000)
    payment_promotions: list[PaymentPromotion] = Field(
        default_factory=lambda: deepcopy(DEFAULT_PAYMENT_PROMOTIONS), max_length=1000, validate_default=True)

    @model_validator(mode="after")
    def unique_rules(self):
        if any(rule.sku != rule.gift_sku for rule in self.sku_gifts):
            raise ValueError("This demo supports buy-one-get-one of the same product")
        for values in ([r.merchant for r in self.merchant_discounts], [r.sku for r in self.sku_gifts]):
            if len(values) != len(set(values)):
                raise ValueError("Only one rule per merchant or purchased SKU")
        keys = [(r.route, r.kind, r.merchant) for r in self.payment_promotions]
        if len(keys) != len(set(keys)):
            raise ValueError("Only one payment promotion per route, reward kind and merchant")
        return self


class QuoteLine(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    qty: int = Field(ge=1, le=10000)


DEFAULT_RULES = {"version": 0, "merchant_discounts": [
    {"merchant": "Watsons", "percent": 15, "threshold": 300},
    {"merchant": "PARKnSHOP", "percent": 10, "threshold": 300}], "sku_gifts": [],
    "payment_promotions": deepcopy(DEFAULT_PAYMENT_PROMOTIONS)}


def money(value):
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def price_quote(requested: list[dict], products: dict, rules: dict) -> dict:
    discounts = {r["merchant"]: r for r in rules["merchant_discounts"]}
    gifts = {r["sku"]: r["gift_sku"] for r in rules["sku_gifts"]}
    quantities = {}
    for raw in requested:
        line = QuoteLine.model_validate(raw)
        quantities[line.sku] = quantities.get(line.sku, 0) + line.qty
    lines = []
    for sku, qty in quantities.items():
        product = products.get(sku)
        if not product or not product["in_stock"] or product["currency"] != "HKD":
            raise ValueError(f"Unavailable HKD SKU: {sku}")
        if product.get("stock") is not None and qty > product["stock"]:
            raise ValueError(f"Insufficient stock: {sku}")
        unit = money(product["price"])
        lines.append({"sku": sku, "name": product["name"], "merchant": product["merchant"],
                      "category": product["category"], "qty": qty, "unit_price": float(unit),
                      "line_total": float(unit * qty), "is_gift": False})
        if sku in gifts:
            gift = products.get(gifts[sku])
            if not gift or not gift["in_stock"] or gift["currency"] != "HKD" or gift["merchant"] != product["merchant"]:
                raise ValueError(f"Unavailable gift for SKU: {sku}")
            lines.append({"sku": gift["id"], "name": gift["name"], "merchant": gift["merchant"],
                          "category": gift["category"], "qty": qty, "unit_price": 0.0,
                          "line_total": 0.0, "is_gift": True, "gift_for_sku": sku})
    required = {}
    for line in lines:
        required[line["sku"]] = required.get(line["sku"], 0) + line["qty"]
    for sku, qty in required.items():
        stock = products[sku].get("stock")
        if stock is not None and qty > stock:
            raise ValueError(f"Insufficient stock including gifts: {sku}")
    merchants = []
    for merchant in dict.fromkeys(line["merchant"] for line in lines):
        subtotal = sum((money(line["line_total"]) for line in lines if line["merchant"] == merchant), Decimal(0))
        rule = discounts.get(merchant)
        discount = money(subtotal * Decimal(str(rule["percent"])) / 100) if rule and subtotal >= Decimal(str(rule["threshold"])) else Decimal(0)
        merchants.append({"merchant": merchant, "subtotal": float(subtotal), "discount": float(discount),
                          "total": float(subtotal - discount)})
    subtotal = sum((money(r["subtotal"]) for r in merchants), Decimal(0))
    shipping = Decimal(0) if subtotal >= Decimal(400) else Decimal(30)
    if merchants:
        host = max(merchants, key=lambda row: row["total"])
        host["total"] = float(money(host["total"]) + shipping)
    return {"currency": "HKD", "rules_version": rules["version"], "lines": lines, "merchants": merchants,
            "subtotal": float(subtotal), "shipping_fee": float(shipping), "tax": 0.0,
            "discount": float(sum((money(r["discount"]) for r in merchants), Decimal(0))),
            "total": float(sum((money(r["total"]) for r in merchants), Decimal(0))),
            "promotion_snapshot": deepcopy({"rules": rules, "products": products, "requested_lines": requested})}


class MarketStore:
    def __init__(self, database_url):
        self.database_url = database_url

    def _read(self, cur):
        cur.execute("SELECT version, rules_json FROM market_rules WHERE id = 1")
        row = cur.fetchone()
        if row:
            rules = MarketRules.model_validate(json.loads(row["rules_json"])).model_dump()
            return dict(rules, version=int(row["version"]))
        return deepcopy(DEFAULT_RULES)

    def get(self):
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                return self._read(cur)

    def put(self, rules: dict, actor: str):
        validated = MarketRules.model_validate(rules).model_dump()
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                for rule in validated["sku_gifts"]:
                    cur.execute("SELECT id, merchant FROM catalog_products WHERE id IN (%s, %s)", (rule["sku"], rule["gift_sku"]))
                    rows = {r["id"]: r for r in cur.fetchall()}
                    if rule["sku"] not in rows or rule["gift_sku"] not in rows or rows[rule["sku"]]["merchant"] != rows[rule["gift_sku"]]["merchant"]:
                        raise ValueError("Gift and purchased SKU must exist at the same merchant")
                cur.execute("INSERT INTO market_rules (id, version, rules_json, updated_by) VALUES (1, 1, %s, %s) ON DUPLICATE KEY UPDATE version = version + 1, rules_json = %s, updated_by = %s", (json.dumps(validated), actor, json.dumps(validated), actor))
                return self._read(cur)

    def quote(self, requested):
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                rules = self._read(cur)
                skus = {r["sku"] for r in requested}
                skus.update(r["gift_sku"] for r in rules["sku_gifts"] if r["sku"] in skus)
                cur.execute(_SELECT + " WHERE id IN (" + ",".join(["%s"] * len(skus)) + ")", tuple(skus))
                products = {row["id"]: _public(row) for row in cur.fetchall()}
                return price_quote(requested, products, rules)
